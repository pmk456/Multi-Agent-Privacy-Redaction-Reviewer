"""Turn uploaded bytes (.txt, .pdf, annotated .json) into `Document`s.

Privacy rules this module follows:

* The filename is used for one thing only: picking the parser from its extension. It is
  never stored on the document, never put in a message, never logged.
* doc_id is taken from the input when supplied, otherwise a random uuid4. It is never
  derived from the content or the filename.
* Error messages and warnings describe the problem without quoting any content.
* Nothing here logs.
"""

from __future__ import annotations

import codecs
import json
import re
import unicodedata
import uuid
from typing import Any, Literal, Optional

import pymupdf
from pydantic import BaseModel, Field

from privacy_review.config import Settings, get_settings
from privacy_review.ingestion.errors import (
    CorruptFileError,
    DocumentTooLongError,
    DuplicateDocIdError,
    EmptyDocumentError,
    EncryptedPDFError,
    FileTooLargeError,
    InvalidDocIdError,
    MalformedJSONError,
    MultipleDocumentsError,
    ScannedPDFError,
    TooManyDocumentsError,
    UnsupportedFormatError,
)
from privacy_review.schemas import Annotation, Document

# MuPDF otherwise prints its own diagnostics to stderr.
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

Format = Literal["txt", "pdf", "json"]
SUPPORTED_FORMATS: dict[str, Format] = {"txt": "txt", "pdf": "pdf", "json": "json"}
DOC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class IngestedDocument(BaseModel):
    """A `Document` plus what we learned while reading it. Backend-only."""

    document: Document
    format: Format
    page_count: Optional[int] = None
    encoding: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)

    def __repr__(self) -> str:      # Document's own repr already hides the text
        return (
            f"IngestedDocument({self.document!r}, format={self.format!r}, "
            f"pages={self.page_count}, encoding={self.encoding!r}, warnings={len(self.warnings)})"
        )

    __str__ = __repr__


# ------------------------------------------------------------------- public API

def ingest_bytes(
    data: bytes, filename: str, *, settings: Settings | None = None, source: str = "upload"
) -> IngestedDocument:
    """Ingest a file that holds exactly one document."""
    docs = ingest_many(data, filename, settings=settings, source=source)
    if len(docs) != 1:
        raise MultipleDocumentsError()
    return docs[0]


def ingest_many(
    data: bytes, filename: str, *, settings: Settings | None = None, source: str = "upload"
) -> list[IngestedDocument]:
    """Ingest a file. A .json file may hold a list of documents; other formats hold one."""
    settings = settings or get_settings()
    fmt = detect_format(filename)
    if len(data) > settings.max_upload_bytes:
        raise FileTooLargeError(
            f"The file exceeds the maximum upload size of {_human_bytes(settings.max_upload_bytes)}."
        )
    if not data:
        raise EmptyDocumentError("The file is empty.")

    if fmt == "txt":
        return [_ingest_txt(data, settings, source)]
    if fmt == "pdf":
        return [_ingest_pdf(data, settings, source)]
    return _ingest_json(data, settings, source)


def ingest_record(
    obj: Any, *, settings: Settings | None = None, source: str = "api", path: str = ""
) -> IngestedDocument:
    """Validate one annotated record ``{"doc_id"?, "text", "annotations"?}``.

    The text is NOT normalised: annotation offsets must stay valid. Annotations are checked
    for structure only. Out-of-bounds or inverted spans are kept - Agent 1 marks them
    INVALID, and that behaviour is evaluated.
    """
    settings = settings or get_settings()
    at = path or "document"
    if not isinstance(obj, dict):
        raise MalformedJSONError(f"{at} must be an object with a 'text' field.")

    text = obj.get("text")
    if not isinstance(text, str):
        raise MalformedJSONError(f"{_join(path, 'text')} is required and must be a string.")
    _check_text(text, settings, where=at)

    doc_id = _doc_id(obj.get("doc_id"), where=_join(path, "doc_id"))

    raw_annotations = obj.get("annotations")
    annotations: Optional[list[Annotation]] = None
    if raw_annotations is not None:
        if not isinstance(raw_annotations, list):
            raise MalformedJSONError(f"{_join(path, 'annotations')} must be a list.")
        annotations = [
            _annotation(a, where=f"{_join(path, 'annotations')}[{j}]")
            for j, a in enumerate(raw_annotations)
        ]

    document = Document(
        doc_id=doc_id,
        text=text,
        annotations=annotations,
        source=source,
        metadata={"format": "json"},
    )
    return IngestedDocument(document=document, format="json")


def detect_format(filename: str) -> Format:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    fmt = SUPPORTED_FORMATS.get(ext)
    if fmt is None:
        raise UnsupportedFormatError()
    return fmt


def normalise_text(text: str) -> str:
    """Strip NUL, normalise line endings to \\n, then Unicode NFC."""
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def decode_text(data: bytes) -> tuple[str, str, list[str]]:
    """Return (text, encoding, warnings). UTF-8 (with or without BOM), UTF-16 with BOM,
    then Windows-1252 as a last resort, with a warning."""
    try:
        encoding = "utf-8-sig" if data.startswith(codecs.BOM_UTF8) else "utf-8"
        return data.decode("utf-8-sig"), encoding, []
    except UnicodeDecodeError:
        pass

    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), "utf-16", []
        except UnicodeDecodeError:
            raise CorruptFileError(
                "The text file starts with a UTF-16 byte-order mark but is not valid UTF-16."
            ) from None

    text = data.decode("cp1252", errors="replace")
    warnings = ["The file is not valid UTF-8; it was decoded as Windows-1252 (cp1252)."]
    bad = text.count("�")
    if bad:
        warnings.append(f"{bad} byte(s) could not be decoded and were replaced.")
    return text, "cp1252", warnings


# ------------------------------------------------------------------- formats

def _ingest_txt(data: bytes, settings: Settings, source: str) -> IngestedDocument:
    text, encoding, warnings = decode_text(data)
    text = normalise_text(text)
    _check_text(text, settings)
    document = Document(
        doc_id=_new_doc_id(),
        text=text,
        source=source,
        metadata={"format": "txt", "encoding": encoding},
    )
    return IngestedDocument(document=document, format="txt", encoding=encoding, warnings=warnings)


def _ingest_pdf(data: bytes, settings: Settings, source: str) -> IngestedDocument:
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise CorruptFileError("The PDF could not be opened; it may be damaged.") from None

    with pdf:
        if pdf.needs_pass:
            raise EncryptedPDFError()
        page_count = pdf.page_count
        if page_count == 0:
            raise EmptyDocumentError("The PDF has no pages.")
        try:
            pages = [normalise_text(page.get_text("text")) for page in pdf]
        except Exception:
            raise CorruptFileError("Text could not be extracted from the PDF.") from None

    with_text = [p.strip("\n") for p in pages if p.strip()]
    if not with_text:
        raise ScannedPDFError()

    warnings: list[str] = []
    missing = page_count - len(with_text)
    if missing:
        warnings.append(
            f"{missing} of {page_count} page(s) have no text layer and were skipped (no OCR)."
        )

    text = "\n\n".join(with_text)
    _check_text(text, settings)
    document = Document(
        doc_id=_new_doc_id(),
        text=text,
        source=source,
        metadata={"format": "pdf", "page_count": str(page_count)},
    )
    return IngestedDocument(document=document, format="pdf", page_count=page_count, warnings=warnings)


def _ingest_json(data: bytes, settings: Settings, source: str) -> list[IngestedDocument]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise MalformedJSONError("JSON input must be UTF-8 encoded.") from None
    except json.JSONDecodeError as exc:
        # line/column are positions, not content - safe to report.
        raise MalformedJSONError(
            f"The file is not valid JSON (line {exc.lineno}, column {exc.colno})."
        ) from None

    if isinstance(payload, dict):
        return [ingest_record(payload, settings=settings, source=source)]

    if not isinstance(payload, list):
        raise MalformedJSONError("JSON input must be an object or a list of objects.")
    if not payload:
        raise EmptyDocumentError("The JSON list contains no documents.")
    if len(payload) > settings.max_files_per_batch:
        raise TooManyDocumentsError(
            f"The JSON list holds {len(payload)} documents; the limit per batch is "
            f"{settings.max_files_per_batch}."
        )

    docs = [
        ingest_record(item, settings=settings, source=source, path=f"[{i}]")
        for i, item in enumerate(payload)
    ]
    seen: set[str] = set()
    for i, d in enumerate(docs):
        if d.document.doc_id in seen:
            raise DuplicateDocIdError(f"[{i}].doc_id repeats an earlier doc_id in this file.")
        seen.add(d.document.doc_id)
    return docs


# ------------------------------------------------------------------- helpers

def _check_text(text: str, settings: Settings, where: str = "") -> None:
    prefix = f"{where}: " if where else ""
    if not text.strip():
        raise EmptyDocumentError(f"{prefix}the document is empty or contains only whitespace.")
    if len(text) > settings.max_document_chars:
        raise DocumentTooLongError(
            f"{prefix}the document has {len(text):,} characters; the limit is "
            f"{settings.max_document_chars:,}."
        )


def _doc_id(value: Any, where: str) -> str:
    if value is None:
        return _new_doc_id()
    if not isinstance(value, str) or not DOC_ID_PATTERN.fullmatch(value):
        raise InvalidDocIdError(f"{where}: {InvalidDocIdError.default_message}")
    return value


def _annotation(obj: Any, where: str) -> Annotation:
    if not isinstance(obj, dict):
        raise MalformedJSONError(f"{where} must be an object with start, end and label.")
    for key in ("start", "end"):
        v = obj.get(key)
        if not isinstance(v, int) or isinstance(v, bool):
            raise MalformedJSONError(f"{where}.{key} is required and must be an integer.")
    if not isinstance(obj.get("label"), str):
        raise MalformedJSONError(f"{where}.label is required and must be a string.")
    return Annotation(start=obj["start"], end=obj["end"], label=obj["label"])


def _new_doc_id() -> str:
    return uuid.uuid4().hex


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _human_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):g} MB"
    if n >= 1024:
        return f"{n / 1024:g} KB"
    return f"{n} bytes"

"""Ingestion tests. Every fixture is generated in tmp_path; all data is fictional."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from privacy_review.config import Settings
from privacy_review.ingestion import (
    ALL_ERRORS,
    CorruptFileError,
    DocumentTooLongError,
    DuplicateDocIdError,
    EmptyDocumentError,
    EncryptedPDFError,
    FileTooLargeError,
    IngestionError,
    InvalidDocIdError,
    MalformedJSONError,
    MultipleDocumentsError,
    ScannedPDFError,
    TooManyDocumentsError,
    UnsupportedFormatError,
    ingest_bytes,
    ingest_many,
    normalise_text,
)

SAMPLE = "Contact Alice Example at alice@example.com or +1-202-555-0143. Café résumé."


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(protected_store_dir=tmp_path / "store", _env_file=None)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _ingest(path: Path, settings: Settings):
    return ingest_bytes(path.read_bytes(), path.name, settings=settings)


# ------------------------------------------------------------------ PDF fixtures

def _text_pdf(*pages: str) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _image_only_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64), False)
    pix.clear_with(180)
    page.insert_image(pymupdf.Rect(72, 72, 300, 300), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def _encrypted_pdf(user_pw: str = "user-secret", owner_pw: str = "owner-secret") -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Fictional confidential memo.")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw=owner_pw)
    doc.close()
    return data


# ------------------------------------------------------------------ error contract

class TestErrorContract:
    def test_all_errors_subclass_ingestion_error(self):
        assert all(issubclass(e, IngestionError) for e in ALL_ERRORS)

    def test_codes_are_stable_and_unique(self):
        codes = {e.code for e in ALL_ERRORS}
        assert len(codes) == len(ALL_ERRORS)
        assert {
            "empty_document", "file_too_large", "unsupported_format", "encrypted_pdf",
            "scanned_pdf", "malformed_json", "document_too_long", "invalid_doc_id",
        } <= codes


# ------------------------------------------------------------------ txt

class TestText:
    def test_utf8(self, tmp_path, settings):
        doc = _ingest(_write(tmp_path, "a.txt", SAMPLE.encode("utf-8")), settings)
        assert doc.document.text == SAMPLE
        assert doc.format == "txt" and doc.encoding == "utf-8" and doc.warnings == []

    def test_utf8_bom_is_stripped(self, tmp_path, settings):
        doc = _ingest(_write(tmp_path, "a.txt", SAMPLE.encode("utf-8-sig")), settings)
        assert doc.document.text == SAMPLE
        assert doc.encoding == "utf-8-sig"

    @pytest.mark.parametrize("codec", ["utf-16", "utf-16-le", "utf-16-be"])
    def test_utf16_with_bom(self, tmp_path, settings, codec):
        import codecs as _c
        bom = {"utf-16-le": _c.BOM_UTF16_LE, "utf-16-be": _c.BOM_UTF16_BE}.get(codec, b"")
        doc = _ingest(_write(tmp_path, "a.txt", bom + SAMPLE.encode(codec)), settings)
        assert doc.document.text == SAMPLE
        assert doc.encoding == "utf-16" and doc.warnings == []

    def test_cp1252_falls_back_with_warning(self, tmp_path, settings):
        text = "Résumé – “quoted” café"          # en dash and curly quotes are cp1252-only bytes
        doc = _ingest(_write(tmp_path, "a.txt", text.encode("cp1252")), settings)
        assert doc.document.text == text
        assert doc.encoding == "cp1252"
        assert len(doc.warnings) == 1 and "cp1252" in doc.warnings[0]

    def test_undecodable_cp1252_bytes_are_counted_not_quoted(self, tmp_path, settings):
        doc = _ingest(_write(tmp_path, "a.txt", b"abc \x81\x8d def \xff\xfe"[:-2] + b"\x90"), settings)
        assert doc.encoding == "cp1252"
        assert any("3 byte(s)" in w for w in doc.warnings)

    def test_normalisation(self, tmp_path, settings):
        raw = "line one\r\nline\x00 two\rthree café"
        doc = _ingest(_write(tmp_path, "a.txt", raw.encode("utf-8")), settings)
        assert doc.document.text == "line one\nline two\nthree café"
        assert normalise_text("é") == "é"

    def test_metadata_has_no_filename(self, tmp_path, settings):
        doc = _ingest(_write(tmp_path, "alice_example_discharge.txt", SAMPLE.encode()), settings)
        assert "alice" not in json.dumps(doc.document.model_dump(exclude={"text"})).lower()
        assert doc.document.metadata == {"format": "txt", "encoding": "utf-8"}

    def test_doc_id_is_random_uuid(self, tmp_path, settings):
        p = _write(tmp_path, "a.txt", SAMPLE.encode())
        a, b = _ingest(p, settings), _ingest(p, settings)
        assert a.document.doc_id != b.document.doc_id
        assert len(a.document.doc_id) == 32

    def test_empty_file(self, tmp_path, settings):
        with pytest.raises(EmptyDocumentError) as e:
            _ingest(_write(tmp_path, "a.txt", b""), settings)
        assert e.value.code == "empty_document"

    def test_whitespace_only_file(self, tmp_path, settings):
        with pytest.raises(EmptyDocumentError):
            _ingest(_write(tmp_path, "a.txt", b" \r\n\t\x00 \n"), settings)

    def test_oversize_file(self, tmp_path):
        small = Settings(max_upload_bytes=1024, _env_file=None)
        with pytest.raises(FileTooLargeError) as e:
            _ingest(_write(tmp_path, "a.txt", b"x" * 1025), small)
        assert e.value.code == "file_too_large"
        assert "1 KB" in e.value.message

    def test_too_many_characters(self, tmp_path):
        small = Settings(max_document_chars=10, _env_file=None)
        with pytest.raises(DocumentTooLongError):
            _ingest(_write(tmp_path, "a.txt", b"x" * 11), small)

    def test_bad_utf16(self, tmp_path, settings):
        import codecs as _c
        with pytest.raises(CorruptFileError):
            _ingest(_write(tmp_path, "a.txt", _c.BOM_UTF16_LE + b"\x00\xd8"), settings)

    @pytest.mark.parametrize("name", ["a.docx", "a", "a.txt.exe", ""])
    def test_unsupported_format(self, tmp_path, settings, name):
        with pytest.raises(UnsupportedFormatError):
            ingest_bytes(b"hello", name, settings=settings)

    def test_extension_is_case_insensitive(self, settings):
        assert ingest_bytes(b"hello", "NOTES.TXT", settings=settings).format == "txt"


# ------------------------------------------------------------------ pdf

class TestPDF:
    def test_text_pdf(self, tmp_path, settings):
        p = _write(tmp_path, "a.pdf", _text_pdf("Page one fictional text.", "Page two text."))
        doc = _ingest(p, settings)
        assert doc.format == "pdf" and doc.page_count == 2
        assert "Page one fictional text." in doc.document.text
        assert "Page two text." in doc.document.text
        assert doc.document.text.index("Page one") < doc.document.text.index("Page two")
        assert doc.document.metadata == {"format": "pdf", "page_count": "2"}
        assert doc.warnings == []

    def test_partially_scanned_pdf_warns(self, tmp_path, settings):
        doc = _ingest(_write(tmp_path, "a.pdf", _text_pdf("Has text.", "")), settings)
        assert doc.page_count == 2
        assert doc.warnings == ["1 of 2 page(s) have no text layer and were skipped (no OCR)."]

    def test_image_only_pdf(self, tmp_path, settings):
        with pytest.raises(ScannedPDFError) as e:
            _ingest(_write(tmp_path, "a.pdf", _image_only_pdf()), settings)
        assert e.value.code == "scanned_pdf"
        assert "OCR" in e.value.message

    def test_encrypted_pdf(self, tmp_path, settings):
        with pytest.raises(EncryptedPDFError) as e:
            _ingest(_write(tmp_path, "a.pdf", _encrypted_pdf()), settings)
        assert e.value.code == "encrypted_pdf"

    def test_owner_password_only_pdf_is_readable(self, tmp_path, settings):
        doc = _ingest(_write(tmp_path, "a.pdf", _encrypted_pdf(user_pw="")), settings)
        assert "Fictional confidential memo." in doc.document.text

    def test_corrupt_pdf(self, tmp_path, settings):
        with pytest.raises(CorruptFileError):
            _ingest(_write(tmp_path, "a.pdf", b"this is not a pdf at all"), settings)


# ------------------------------------------------------------------ json

class TestJSON:
    def _j(self, tmp_path, settings, payload, name="a.json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return ingest_many(_write(tmp_path, name, data).read_bytes(), name, settings=settings)

    def test_single_object(self, tmp_path, settings):
        text = "Email alice@example.com\r\nnow"
        [doc] = self._j(tmp_path, settings, {
            "doc_id": "hr-001", "text": text,
            "annotations": [{"start": 6, "end": 23, "label": "EMAIL"}],
        })
        assert doc.document.doc_id == "hr-001"
        assert doc.document.text == text           # NOT normalised: offsets must stay valid
        assert doc.document.text[6:23] == "alice@example.com"
        assert doc.document.annotations[0].label == "EMAIL"
        assert doc.document.is_annotated

    def test_list_of_objects(self, tmp_path, settings):
        docs = self._j(tmp_path, settings, [
            {"text": "first"}, {"doc_id": "b", "text": "second", "annotations": []},
        ])
        assert [d.document.text for d in docs] == ["first", "second"]
        assert docs[0].document.annotations is None and not docs[0].document.is_annotated
        assert docs[1].document.annotations == [] and docs[1].document.is_annotated
        assert len(docs[0].document.doc_id) == 32 and docs[1].document.doc_id == "b"

    def test_out_of_bounds_annotation_is_kept(self, tmp_path, settings):
        [doc] = self._j(tmp_path, settings, {
            "text": "short", "annotations": [{"start": 3, "end": 999, "label": "PERSON"},
                                             {"start": 4, "end": 2, "label": "AGE"},
                                             {"start": -1, "end": 2, "label": ""}],
        })
        assert [(a.start, a.end) for a in doc.document.annotations] == [(3, 999), (4, 2), (-1, 2)]

    def test_ingest_bytes_rejects_multi_document_file(self, tmp_path, settings):
        p = _write(tmp_path, "a.json", json.dumps([{"text": "a"}, {"text": "b"}]).encode())
        with pytest.raises(MultipleDocumentsError):
            _ingest(p, settings)

    @pytest.mark.parametrize("payload, fragment", [
        (b"{not json", "line 1"),
        (b"\xff\xfe{}", "UTF-8"),
        ("just a string", "object or a list"),
        ({"annotations": []}, "text is required"),
        ({"text": 5}, "text is required"),
        ({"text": "x", "annotations": {"start": 0}}, "annotations must be a list"),
        ({"text": "x", "annotations": ["oops"]}, "annotations[0] must be an object"),
        ({"text": "x", "annotations": [{"start": "0", "end": 1, "label": "A"}]},
         "annotations[0].start"),
        ({"text": "x", "annotations": [{"start": 0, "end": 1.5, "label": "A"}]},
         "annotations[0].end"),
        ({"text": "x", "annotations": [{"start": True, "end": 1, "label": "A"}]},
         "annotations[0].start"),
        ({"text": "x", "annotations": [{"start": 0, "end": 1, "label": 7}]},
         "annotations[0].label"),
        ([{"text": "ok"}, {"txt": "typo"}], "[1].text"),
    ])
    def test_malformed(self, tmp_path, settings, payload, fragment):
        with pytest.raises(MalformedJSONError) as e:
            self._j(tmp_path, settings, payload)
        assert e.value.code == "malformed_json"
        assert fragment in e.value.message

    def test_error_messages_never_quote_content(self, tmp_path, settings):
        secret = "alice@example.com"
        cases = [
            {"text": secret, "annotations": [{"start": 0, "end": 1, "label": secret}, {"start": secret}]},
            {"text": secret, "doc_id": secret},
            {"text": secret, "annotations": [{"start": 0, "end": secret, "label": "x"}]},
            ("{\"text\": \"" + secret + "\" oops").encode(),
        ]
        for payload in cases:
            with pytest.raises(IngestionError) as e:
                self._j(tmp_path, settings, payload)
            assert secret not in str(e.value)

    @pytest.mark.parametrize("doc_id", ["", "../etc/passwd", "a/b", ".hidden", "x" * 129, 7, "a b"])
    def test_invalid_doc_id(self, tmp_path, settings, doc_id):
        with pytest.raises(InvalidDocIdError):
            self._j(tmp_path, settings, {"doc_id": doc_id, "text": "x"})

    def test_duplicate_doc_id(self, tmp_path, settings):
        with pytest.raises(DuplicateDocIdError):
            self._j(tmp_path, settings, [{"doc_id": "a", "text": "x"}, {"doc_id": "a", "text": "y"}])

    def test_empty_list_and_empty_text(self, tmp_path, settings):
        with pytest.raises(EmptyDocumentError):
            self._j(tmp_path, settings, [])
        with pytest.raises(EmptyDocumentError):
            self._j(tmp_path, settings, {"text": "   "})

    def test_too_many_documents(self, tmp_path):
        small = Settings(max_files_per_batch=2, _env_file=None)
        with pytest.raises(TooManyDocumentsError):
            self._j(tmp_path, small, [{"text": "a"}, {"text": "b"}, {"text": "c"}])

"""Ingestion errors.

Every error carries a stable machine-readable ``code`` that the API returns to clients.
Messages describe the *problem*, never the content: they must not quote document text,
annotation labels, doc_ids taken from content, or the uploaded filename.
"""

from __future__ import annotations


class IngestionError(Exception):
    code: str = "ingestion_error"
    default_message: str = "The document could not be ingested."

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)


class EmptyDocumentError(IngestionError):
    code = "empty_document"
    default_message = "The document is empty or contains only whitespace."


class FileTooLargeError(IngestionError):
    code = "file_too_large"
    default_message = "The file exceeds the maximum upload size."


class DocumentTooLongError(IngestionError):
    code = "document_too_long"
    default_message = "The document text exceeds the maximum number of characters."


class TooManyDocumentsError(IngestionError):
    code = "too_many_documents"
    default_message = "The batch contains more documents than allowed."


class UnsupportedFormatError(IngestionError):
    code = "unsupported_format"
    default_message = "Unsupported file type. Use .txt, .pdf or .json."


class CorruptFileError(IngestionError):
    code = "corrupt_file"
    default_message = "The file is damaged or not in the format its extension claims."


class EncryptedPDFError(IngestionError):
    code = "encrypted_pdf"
    default_message = (
        "The PDF is protected with a password. Remove the password and upload it again."
    )


class ScannedPDFError(IngestionError):
    code = "scanned_pdf"
    default_message = (
        "The PDF has no text layer (it looks scanned or image-only). OCR is not supported; "
        "upload a text-based PDF or a .txt file instead."
    )


class MalformedJSONError(IngestionError):
    code = "malformed_json"
    default_message = "The JSON is not valid annotated input."


class InvalidDocIdError(IngestionError):
    code = "invalid_doc_id"
    default_message = (
        "doc_id must be 1-128 characters of letters, digits, '.', '_' or '-', "
        "starting with a letter or digit."
    )


class DuplicateDocIdError(IngestionError):
    code = "duplicate_doc_id"
    default_message = "The same doc_id appears more than once in this batch."


class MultipleDocumentsError(IngestionError):
    code = "multiple_documents"
    default_message = "The file contains several documents; use ingest_many()."


ALL_ERRORS: tuple[type[IngestionError], ...] = (
    EmptyDocumentError,
    FileTooLargeError,
    DocumentTooLongError,
    TooManyDocumentsError,
    UnsupportedFormatError,
    CorruptFileError,
    EncryptedPDFError,
    ScannedPDFError,
    MalformedJSONError,
    InvalidDocIdError,
    DuplicateDocIdError,
    MultipleDocumentsError,
)

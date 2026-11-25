"""FastAPI service.

Run from the repository root:

    uvicorn --factory privacy_review.api:create_app --app-dir backend

Privacy rules enforced here:

* result endpoints return `BatchResult` (response_model) and nothing else
* request bodies are never logged; validation errors never echo input values
* uploaded filenames are used only to pick a parser - they are never stored, logged or
  returned; problems are reported by file index
* unhandled exceptions are logged by type name only (messages can carry content) and the
  client gets a generic 500
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from privacy_review import __version__
from privacy_review.api.models import (
    ErrorResponse,
    HealthResponse,
    ItemError,
    ReviewRequest,
)
from privacy_review.api.pipeline import (
    PipelineMode,
    adapt,
    enforce_release_gate,
    load_pipeline,
    stub_run_batch,
)
from privacy_review.api.store import ProtectedStore
from privacy_review.config import Settings, get_settings
from privacy_review.config.settings import REPO_DIR
from privacy_review.ingestion import (
    DuplicateDocIdError,
    IngestedDocument,
    IngestionError,
    TooManyDocumentsError,
    ingest_many,
    ingest_record,
)
from privacy_review.schemas import BatchResult, Document

log = logging.getLogger("privacy_review.api")

FRONTEND_DIR = REPO_DIR / "frontend"
MULTIPART_OVERHEAD = 256 * 1024
ERROR_RESPONSES = {422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}


def create_app(
    run_batch: Optional[Callable] = None,
    *,
    settings: Optional[Settings] = None,
    frontend_dir: Optional[Path] = FRONTEND_DIR,
) -> FastAPI:
    """Build the app. `run_batch` is injectable so tests can pass fakes."""
    settings = settings or get_settings()
    mode: PipelineMode
    if run_batch is None:
        run_batch, mode = load_pipeline()
    else:
        mode = "stub" if run_batch is stub_run_batch else "live"
        run_batch = adapt(run_batch)

    store = ProtectedStore(settings.protected_store_dir)
    max_body = settings.max_upload_bytes * settings.max_files_per_batch + MULTIPART_OVERHEAD

    app = FastAPI(
        title="PS 247 - Multi-Agent Privacy Redaction Review",
        version=__version__,
        description="Original documents stay in the backend. Responses carry redacted text, "
        "entity categories, risks, decisions and verification findings only.",
    )
    app.state.settings = settings
    app.state.store = store
    app.state.pipeline_mode = mode
    app.add_middleware(BoundaryMiddleware, max_body_bytes=max_body)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default handler echoes the offending input back. Ours doesn't.
        errors = [
            {"loc": [str(p) for p in e.get("loc", ())], "type": e.get("type"), "msg": e.get("msg")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": "The request failed validation.", "code": "invalid_request",
                     "errors": errors},
        )

    def _run(documents: list[Document], originals: list[tuple[str, str, bytes]]):
        batch_id = uuid.uuid4().hex
        for doc_id, ext, payload in originals:
            store.save_original(batch_id, doc_id, ext, payload)
        log.info("batch %s: %d document(s), pipeline=%s", batch_id, len(documents), mode)
        try:
            result = enforce_release_gate(run_batch(documents, batch_id), batch_id)
        except Exception as exc:
            log.error("batch %s: pipeline failed (%s)", batch_id, type(exc).__name__)
            store.record_failure(batch_id, [d.doc_id for d in documents])
            return _error(500, "pipeline_error", "The review pipeline failed; nothing was released.")
        store.record_batch(result)
        log.info(
            "batch %s: %d released, %d blocked", batch_id,
            result.aggregate.documents_released, result.aggregate.documents_blocked,
        )
        return result

    # ------------------------------------------------------------ endpoints

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(pipeline=mode, llm=settings.llm_available)

    @app.post("/review", response_model=BatchResult, responses=ERROR_RESPONSES)
    def review(request: ReviewRequest):
        if len(request.documents) > settings.max_files_per_batch:
            return _error(422, TooManyDocumentsError.code,
                          f"At most {settings.max_files_per_batch} documents per batch.")
        ingested: list[IngestedDocument] = []
        errors: list[ItemError] = []
        seen: set[str] = set()
        for i, item in enumerate(request.documents):
            try:
                doc = ingest_record(item.model_dump(), settings=settings, source="api",
                                    path=f"documents[{i}]")
                if doc.document.doc_id in seen:
                    raise DuplicateDocIdError(f"documents[{i}].doc_id repeats an earlier doc_id.")
                seen.add(doc.document.doc_id)
                ingested.append(doc)
            except IngestionError as exc:
                errors.append(ItemError(document_index=i, code=exc.code, message=exc.message))
        if errors:
            return _error(422, "ingestion_failed", "One or more documents were rejected.", errors)

        documents = [d.document for d in ingested]
        return _run(documents, [(d.doc_id, "json", _record_bytes(d)) for d in documents])

    @app.post("/upload", response_model=BatchResult, responses=ERROR_RESPONSES)
    def upload(files: list[UploadFile] = File(...)):
        if len(files) > settings.max_files_per_batch:
            return _error(422, "too_many_files",
                          f"At most {settings.max_files_per_batch} files per batch.")
        errors: list[ItemError] = []
        documents: list[Document] = []
        originals: list[tuple[str, str, bytes]] = []
        seen: set[str] = set()

        for i, f in enumerate(files):
            try:
                data = f.file.read(settings.max_upload_bytes + 1)
                # The filename is used only to choose a parser. It goes no further.
                docs = ingest_many(data, f.filename or "", settings=settings, source="upload")
                for d in docs:
                    if d.document.doc_id in seen:
                        raise DuplicateDocIdError()
                    seen.add(d.document.doc_id)
            except IngestionError as exc:
                errors.append(ItemError(file_index=i, code=exc.code, message=exc.message))
                continue
            except Exception as exc:     # parser bug or exotic file: report by index only
                log.warning("file #%d: unexpected %s during ingestion", i, type(exc).__name__)
                errors.append(ItemError(file_index=i, code="unreadable_file",
                                        message="The file could not be read."))
                continue
            finally:
                f.file.close()

            for d in docs:
                documents.append(d.document)
                if d.format == "json":
                    originals.append((d.document.doc_id, "json", _record_bytes(d.document)))
                else:
                    originals.append((d.document.doc_id, d.format, data))

        if not errors and len(documents) > settings.max_files_per_batch:
            return _error(422, TooManyDocumentsError.code,
                          f"The files hold {len(documents)} documents; the limit per batch is "
                          f"{settings.max_files_per_batch}.")
        if errors:
            return _error(422, "ingestion_failed", "One or more files were rejected.", errors)
        return _run(documents, originals)

    @app.get("/batches/{batch_id}", response_model=BatchResult,
             responses={404: {"model": ErrorResponse}})
    def get_batch(batch_id: str):
        result = store.get_result(batch_id)
        if result is None:
            # don't echo the id back
            return _error(404, "batch_not_found", "No batch with that id.")
        return result

    # ------------------------------------------------------------ frontend

    if frontend_dir is not None and Path(frontend_dir).is_dir():
        app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse(url="/ui/")

    return app


def _error(status: int, code: str, detail: str, errors: list[ItemError] | None = None) -> JSONResponse:
    body = ErrorResponse(detail=detail, code=code, errors=errors or [])
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True))


def _record_bytes(doc: Document) -> bytes:
    record = {
        "doc_id": doc.doc_id,
        "text": doc.text,
        "annotations": None if doc.annotations is None else [a.model_dump() for a in doc.annotations],
    }
    return json.dumps(record, ensure_ascii=False).encode("utf-8")


class BoundaryMiddleware:
    """Outermost guard (inside Starlette's error middleware).

    * rejects POST bodies with no Content-Length (411) or over the limit (413)
    * turns any unhandled exception into a generic 500, logging only its type name, so
      exception messages - which may carry content - never reach logs or clients
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["method"] in {"POST", "PUT", "PATCH"}:
            length = dict(scope.get("headers") or []).get(b"content-length")
            if length is None:
                await _send_error(scope, receive, send, 411, "length_required",
                                  "Content-Length is required.")
                return
            try:
                too_big = int(length) > self.max_body_bytes
            except ValueError:
                too_big = True
            if too_big:
                await _send_error(scope, receive, send, 413, "request_too_large",
                                  "The request body is too large.")
                return

        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            log.error("unhandled %s on %s %s", type(exc).__name__, scope["method"], scope["path"])
            if not started:
                await _send_error(scope, receive, send, 500, "internal_error", "Internal error.")


async def _send_error(scope: Scope, receive: Receive, send: Send, status: int, code: str,
                      detail: str) -> None:
    response = JSONResponse(status_code=status, content={"detail": detail, "code": code,
                                                         "errors": []})
    await response(scope, receive, send)

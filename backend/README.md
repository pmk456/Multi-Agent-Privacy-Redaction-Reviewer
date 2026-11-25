# Backend

FastAPI service plus the agent workflow. Run from the repository root:

```bash
uvicorn --factory privacy_review.api:create_app --app-dir backend --reload
# then open http://127.0.0.1:8000/ui/   (the frontend is served by the same app)

cd backend && pytest
```

`privacy_review/schemas/` is shared by every slice - read CONTRIBUTING.md before changing it.

## API

| Method | Path | Body | Returns |
|---|---|---|---|
| GET  | `/health` | | `{"status": "ok", "pipeline": "stub" \| "live", "llm": bool}` |
| POST | `/review` | JSON `{"documents": [{"doc_id"?, "text", "annotations"?}]}` | `BatchResult` |
| POST | `/upload` | multipart `files` (.txt / .pdf / .json) | `BatchResult` |
| GET  | `/batches/{batch_id}` | | stored `BatchResult`, 404 if unknown |
| GET  | `/` → `/ui/` | | the frontend |

Errors are `{"detail", "code", "errors": [...]}`. A rejected upload returns 422 with one
entry per bad file: `{"file_index", "code", "message"}` (0-based index, never the
filename). `/review` uses `document_index` instead.

**Pipeline.** At startup the app tries `privacy_review.orchestration.runner.run_batch`.
Until that exists, a stub withholds every document (`released=false`,
`redacted_text=null`, status `blocked`). Tests inject fakes with `create_app(run_batch=...)`.

**Storage** (`protected_store/`, git-ignored): originals at `<batch_id>/<doc_id>.<ext>`
(mode 0600), and `api.sqlite` with an `audit` table (ids, status, counts, never values or
filenames) and a `results` table (sanitized `BatchResult` JSON).

**Limits** (settings / env): `MAX_UPLOAD_BYTES` (5 MB), `MAX_DOCUMENT_CHARS` (200 000),
`MAX_FILES_PER_BATCH` (20).

## Ingestion

`privacy_review.ingestion.ingest_bytes(data, filename)` → `IngestedDocument` (or
`ingest_many` for a .json list). The filename is only used to pick a parser. Every error
subclasses `IngestionError` and has a stable `.code`: `empty_document`, `file_too_large`,
`document_too_long`, `unsupported_format`, `corrupt_file`, `encrypted_pdf`, `scanned_pdf`,
`malformed_json`, `invalid_doc_id`, `duplicate_doc_id`, `too_many_documents`.

## Frontend mock

`frontend/mock/batch_result.json` is generated from the Pydantic models:
`python scripts/make_frontend_mock.py`. `tests/test_frontend_mock.py` fails if it drifts
from the schema or from the generator.

# Handoff: PS 247 – who is doing what

Paste this into your own Claude session (or just read it) before picking up work.

## Already being built – do NOT work on these

Patan's session is building the AI backend in `backend/privacy_review/`:

- `schemas/`: Pydantic contracts between agents (done)
- `knowledge_base/`: policies.json (22 entity types), SQLite store, policy engine, conflict validator (done, 64 tests passing)
- `datasets/`: ai4privacy sample (400 rows, split 200 dev / 100 validation / 100 test) + PIIMB independent test (300 rows: gretel, nemotron-pii, privy), label mapping (done)
- `detection/` + Agent 1 (Presidio + spaCy): in progress
- Agents 2–5, `redaction/`, `orchestration/` (LangGraph), `evaluation/`, and their tests: next

Don't edit those folders. If you need a schema change, ask Patan first. Every agent depends on the schemas.

## Rules for everything

- No raw identifier ever leaves the backend: not in API responses, logs, screenshots, commits or issues.
- Never commit anything under `data/`. The ai4privacy licence forbids redistributing derived data.
- Branch per task (`feature/<area>-<name>`), open a PR into `main`, get one review.
- Python 3.12. Clone into a path without `:` in it, or venv creation fails.
- No Claude API key is needed; the deterministic path works without one.
- Never write metrics into documents until the evaluation report produces them.

## Contracts to build against

- Input: `Document(doc_id: str, text: str, annotations: list[{start, end, label}] | None)` in `privacy_review/schemas/documents.py`
- Output: `BatchResult` in `privacy_review/schemas/outputs.py`, containing:
  - `documents`: list of `SanitizedDocument` with `doc_id`, `released`, `redacted_text` (null if blocked), `entities` (PublicEntity, with **no value field**), `risks`, `decisions`, `verification`, `release`
  - `adversarial` report
  - `aggregate` counts
- Pipeline entry point (coming soon): `run_batch(documents: list[Document]) -> BatchResult`. Mock it until it lands.

## Pick from these (no overlap with Patan's work)

1. **Document ingestion**: new `backend/privacy_review/ingestion/`. Turn .pdf (PyMuPDF), .txt and annotated .json into `Document`. Scanned or encrypted PDFs with no text layer → clear error. Handle encoding, size limits and empty files. pytest with generated fixtures.
2. **FastAPI service**: new `backend/privacy_review/api/`.
   - Endpoints: `POST /review` (JSON), `POST /upload` (multi-file), `GET /batches/{id}`, `GET /health`.
   - `response_model=BatchResult` only.
   - Originals go in `protected_store/` (git-ignored).
   - SQLite audit table: batch_id, doc_id, status, counts. Never values.
   - Mock `run_batch` until it lands.
3. **Frontend**: `frontend/`, HTML + Tailwind. Upload page; per-document view (redacted text, entity chips by type/risk, release status, verification findings); aggregate Plotly charts. Build against a mock `BatchResult` JSON.
4. **Synthetic cross-document dataset** (tell Patan before starting so it isn't built twice): `backend/tests/fixtures/synthetic_cross_document.json`
   - Size: 20–30 documents, ~8 fictional people, each spread across 3–4 documents (HR record, achievement news, event attendance, support ticket…).
   - Format:
     ```
     {"persons": [{"person_id", "attributes": {occupation, organization, city, age, events...}}],
      "documents": [{"doc_id", "text", "person_ids": [...]}],      // person_ids = hidden ground truth
      "planted_risks": [{"risk_id", "person_id", "doc_ids", "combined_attributes": ["OCCUPATION", "ORGANIZATION", "LOCATION", "AGE"], "reidentifiable": true|false, "why"}],
      "expected_strategies": [{"doc_id", "start", "end", "entity_type", "expected_strategy"}]}
     ```
   - Each document is fairly harmless alone; combined, some people become identifiable.
   - Include control cases too: attributes shared by 3+ people (e.g. several nurses in Mumbai) that must NOT be flagged.
   - Fictional names only. Emails `@example.com`, phones in the 555-01xx range. Never real people.
5. **Review 2 documentation**: `docs/review-2/`. Skeleton of Document 2 (Implementation and Prototype Development Report), a demo script, and slots for screenshots and results. Fill in results only from the generated evaluation report.

## Getting started

```bash
git pull
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && python -m spacy download en_core_web_lg
cd backend && pytest
```

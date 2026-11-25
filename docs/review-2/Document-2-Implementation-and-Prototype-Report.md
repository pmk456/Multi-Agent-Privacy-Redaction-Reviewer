# Document 2: Implementation and Prototype Development Report

**PS 247: Multi-Agent Privacy Redaction Review**
Generative AI Semester-End Hackathon, Alliance University

> **Status: draft skeleton.** Sections marked **[PLACEHOLDER]** are waiting on work that is
> still in progress. **Do not fill any metric, score or count from memory or estimate.**
> Every number in Section 6 must come from the generated evaluation report.

| | |
|---|---|
| Team | See the team table in the repository README |
| Repository | `pmk456/Multi-Agent-Privacy-Redaction-Reviewer` |
| Review 1 design report | `docs/review-1/Problem-Analysis-and-Solution-Design-Report.docx` |
| Demo script | [`demo-script.md`](demo-script.md) |

---

## 1. Introduction

### 1.1 What Review 2 covers
The prototype turns the Review 1 design into running code. This document covers:
- what has been implemented
- how each part enforces the project's central rule
- how the parts are tested
- what is still to come

### 1.2 The central rule
Original documents and raw identifiers stay inside the protected backend. The only things
that cross the API boundary are:
- redacted text
- entity categories
- risk levels
- redaction strategies
- verification findings
- aggregate counts

This applies to log lines, error messages, the audit database and temporary files as much
as to HTTP responses.

---

## 2. Architecture as implemented

![System architecture](../assets/system-architecture.png)

### 2.1 Module map

| Module | Responsibility | Status at time of writing |
|---|---|---|
| `schemas/` | Pydantic contracts between agents and at the API boundary | Done |
| `knowledge_base/` | `policies.json`, SQLite store, policy engine, conflict validator | Done |
| `datasets/` | ai4privacy + PIIMB sampling, label mapping, splits; synthetic cross-document set | Done |
| `ingestion/` | `.txt` / `.pdf` / annotated `.json` → `Document` | Done |
| `api/` | FastAPI service, protected store, audit DB, frontend hosting | Done (pipeline stubbed) |
| `frontend/` | Upload, per-document and aggregate views | Done (against mock + stub) |
| `detection/`, Agent 1 | Presidio + spaCy + pattern detectors, annotation validation, clustering | **[PLACEHOLDER: status]** |
| Agents 2–5 | Risk/policy, redaction, verification, adversarial | **[PLACEHOLDER: status]** |
| `orchestration/` | LangGraph workflow, remediation loop, `run_batch` | **[PLACEHOLDER: status]** |
| `evaluation/` | Metrics and reports | **[PLACEHOLDER: status]** |

### 2.2 Data flow
1. **Ingest.** A client uploads files or posts JSON. Ingestion validates each file and turns it into a `Document`.
2. **Store originals.** Each original is written to `protected_store/<batch_id>/<doc_id>.<ext>` with owner-only permissions.
3. **Run the pipeline.** `run_batch(documents, batch_id)` returns a `BatchResult`.
4. **Release gate.** At the API boundary, the gate re-validates the result and strips text from every document that is not released.
5. **Record.** The sanitized result and audit rows (ids, statuses and counts only) go to SQLite.
6. **Respond.** The client receives the `BatchResult` and nothing else.

---

## 3. Implementation: agents and policy

### 3.1 Contracts (`schemas/`)
- `Document` is the input contract.
- `BatchResult`, holding `SanitizedDocument` records, is the output contract.
- `PublicEntity`, the entity type that crosses the boundary, deliberately has **no value field**.
- `DetectedEntity.value` is a `SecretStr`, so printing or JSON-dumping an entity shows a mask. The raw text is reachable only through `.raw()`, which keeps every access explicit and greppable.

### 3.2 Privacy knowledge base (`knowledge_base/`)
**[PLACEHOLDER: Patan]** Summarise:
- the entity policies, context rules (CTX-01 to CTX-06), exceptions (EXC-01, EXC-02), linkage rules and policy constraints
- the JSON → SQLite → policy engine path
- the conflict validator
- the hand-written expected-decisions fixture

### 3.3 Agent 1: Privacy Intelligence
**[PLACEHOLDER: Patan]** Cover:
- the detectors
- annotation validation statuses
- cross-document clustering
- the entity graph

### 3.4 Agent 2: Risk and Policy
**[PLACEHOLDER]**

### 3.5 Agent 3: Redaction
**[PLACEHOLDER]** Cover masking, generalisation and pseudonymisation, and segment mapping.

### 3.6 Agent 4: Verification
**[PLACEHOLDER]**

### 3.7 Agent 5: Adversarial / re-identification
**[PLACEHOLDER]** Reference the synthetic dataset (§4.5) as its ground truth.

### 3.8 Orchestration and remediation loop
**[PLACEHOLDER]** Cover the LangGraph graph, routing, remediation rounds and the release decision.

### 3.9 Optional LLM reasoning
**[PLACEHOLDER]** Cover what the LLM sees, and confirm it never receives raw identifiers by default.

---

## 4. Implementation: ingestion, service, storage and interface

### 4.1 Document ingestion (`backend/privacy_review/ingestion/`)

**Entry points**
- `ingest_bytes(data, filename) -> IngestedDocument` handles a file with exactly one document.
- `ingest_many(data, filename)` handles a `.json` file that may hold a list of documents.
- `IngestedDocument` wraps the `Document` with `format`, `page_count`, `encoding` and `warnings`.

| Format | Handling |
|---|---|
| `.txt` | Decoded as UTF-8 (with or without BOM), then UTF-16 with a BOM, then Windows-1252 with a warning. Bytes that can't be decoded are counted, not quoted. Text is normalised: NUL stripped, `\r\n` → `\n`, Unicode NFC. |
| `.pdf` | PyMuPDF extracts each page's text and joins the pages. A PDF that needs a user password raises `EncryptedPDFError`. A PDF with no text layer (scanned or image-only) raises `ScannedPDFError`; there is no OCR. A PDF with only some pages blank is accepted with a warning. PDFs locked only by an owner password still open. |
| `.json` | One object `{doc_id?, text, annotations?}` or a list of them. The structure is validated, but the text is **not** normalised, because annotation offsets must stay valid. Annotations that are out of bounds or inverted are **kept**: Agent 1 marks them INVALID, and that behaviour is evaluated. |

**Privacy decisions**
- **Filenames are treated as possibly identifying.** For example, `<name>_discharge.pdf` names the patient. The filename is used only to choose a parser. It is never stored on the document, never logged and never put in an error message.
- **doc_id** is the one supplied, or a random UUID4. It is never derived from the content or the filename. A supplied doc_id is restricted to a safe character set, because it becomes a file path.
- **Error messages never quote content.** They report positions instead, such as `documents[2].annotations[0].start must be an integer` or `line 4, column 9`.
- **Limits come from settings:**
  - `MAX_UPLOAD_BYTES` (default 5 MB)
  - `MAX_DOCUMENT_CHARS` (default 200,000)
  - `MAX_FILES_PER_BATCH` (default 20)

**Error codes.** Every error subclasses `IngestionError` and carries a stable `.code`:

| Code | Raised when |
|---|---|
| `empty_document` | The file or text is empty or only whitespace |
| `file_too_large` | The file exceeds `MAX_UPLOAD_BYTES` |
| `document_too_long` | The text exceeds `MAX_DOCUMENT_CHARS` |
| `unsupported_format` | The extension is not `.txt`, `.pdf` or `.json` |
| `corrupt_file` | The file is damaged or not the format its extension claims |
| `encrypted_pdf` | The PDF needs a user password |
| `scanned_pdf` | The PDF has no text layer |
| `malformed_json` | The JSON is invalid or doesn't match the annotated-input structure |
| `invalid_doc_id` | A supplied doc_id has an unsafe format |
| `duplicate_doc_id` | The same doc_id appears twice in a batch |
| `too_many_documents` | A batch holds more than `MAX_FILES_PER_BATCH` documents |

### 4.2 API service (`backend/privacy_review/api/`)

`create_app(run_batch=None)` builds the app. The pipeline is injected, so tests can pass
fakes.

| Endpoint | Purpose |
|---|---|
| `GET /health` | `{"status", "pipeline": "stub" \| "live", "llm"}` |
| `POST /review` | JSON documents → `BatchResult` |
| `POST /upload` | Multipart files → ingestion → `BatchResult`. If any file fails, the response is 422 with `{file_index, code, message}` per file. |
| `GET /batches/{id}` | The stored `BatchResult`, or 404 |
| `/` → `/ui/` | The frontend, served from the same origin (no CORS configuration needed) |

Result endpoints declare `response_model=BatchResult` and nothing else.

**Pipeline stub.** The real `run_batch` hasn't landed yet. Until it does, the app falls back
to a stub that withholds every document: `released=false`, `redacted_text=null`, status
`blocked`. The stub reads only doc_ids. A mock that echoed its input would leak exactly
what it stands in for. When `orchestration.runner.run_batch` becomes importable, the app
uses it automatically.

### 4.3 Protected storage and audit
- **Originals:** `protected_store/<batch_id>/<doc_id>.<ext>`. Files are created with mode `0600` and directories with `0700`. Existing files are never overwritten.
- **`api.sqlite`**, also `0600`, holds two tables:
  - `audit(batch_id, doc_id, status, entity_count, finding_count, created_at)`: never values, never filenames.
  - `results(batch_id, json)`: `BatchResult` JSON only, which is already sanitized.
- `protected_store/` is git-ignored.

### 4.4 Security additions beyond the brief
Each of these closes a specific leak path we found while building the service:

| Leak path | Mitigation |
|---|---|
| FastAPI's default 422 handler echoes the offending input back to the client | A custom handler returns only location, type and message. Unknown request keys are ignored rather than echoed. |
| Exception messages can contain document text, which then reaches logs | An outer middleware logs only the exception's type name and returns a generic 500. Pipeline failures get a dedicated `pipeline_error` response. |
| A pipeline bug could return text for a blocked document | The release gate re-validates every result. It drops `redacted_text` from any document that is not released, and marks inconsistent release decisions as blocked. |
| Unbounded request bodies | Bodies over the limit get 413. Bodies without a Content-Length get 411. |
| A path supplied as doc_id could escape the store | doc_ids are validated with a strict pattern, and paths are resolved and checked against the store root. |
| Batch ids echoed in 404 responses | 404 bodies don't repeat the requested id. |

### 4.5 Synthetic cross-document dataset (ground truth for Agent 5)
`backend/tests/fixtures/synthetic_cross_document.json` is generated by
`backend/scripts/make_synthetic_dataset.py`. The generator is seeded and deterministic, and
all data is fictional. Its format is defined in `privacy_review/datasets/synthetic_schema.py`.

**Composition** (design facts, not metrics):
- 28 documents of 8 types
- a 40-person hidden registry: 9 targets and 31 others
- 208 annotated mentions, each with a hidden `person_id`

**Planted risks**
- **5 re-identifiable targets (k = 1).** For 4 of them, each document shows fewer than three quasi-identifier types, kept out of the sentence that names the person. First-pass policy therefore keeps those values, and only the combination across documents is unique. That is precisely the gap Agent 5 exists to close. The fifth is identified by a document that names nobody; CTX-01 catches it in the first pass.
- **4 controls (k ≥ 3).** Even everything their documents reveal together is shared by at least three registry people, so they must not be flagged.

**Edge cases.** These map to knowledge-base rules:
- name variants of one person
- two people who share a surname
- one email address in two documents
- a document with no name that still identifies someone
- date of birth, postcode and gender in one document
- a medical condition alongside a name
- a nationality stated about a named person
- isolated datelines
- conflicting cities for one person
- a document about an organisation only

**Independence.** k is recomputed in the tests from the registry, not trusted from the
file. The generator derives expected strategies with its own implementation of the
`policies.json` rules, and a test cross-checks every one against the knowledge base's
`PolicyEngine`.

### 4.6 Frontend (`frontend/`)
- Plain HTML with Tailwind and Plotly from CDNs, and no build step. It is served by the API at `/ui/`.
- **Upload view:** multi-file picker and a paste box. A rejected upload shows a per-file error by index. The filename is shown from the browser's own file picker, because the server never sends it back.
- **Per-document view:**
  - release status and reason
  - redacted text, with placeholders and pseudonyms highlighted
  - entity chips by type, coloured by risk (risks and decisions joined on `entity_id`)
  - the strategy applied to each entity
  - verification and adversarial findings, with severity
- **Spans are never displayed.** They refer to the original text, not the redacted text.
- **Aggregate view:** Plotly charts of entities by type, risks by level, strategies and findings, plus released/blocked counts and a cross-document linkage table.
- **Demo mode** loads `frontend/mock/batch_result.json`. The mock is generated from the real Pydantic models with fictional data. A test fails if it drifts from the schema.
- **Rendering safety:** all API data is rendered with `textContent`, never `innerHTML`.

**[PLACEHOLDER: screenshots]** Use demo mode only. See `demo-script.md`.

---

## 5. Testing

| Suite | What it checks |
|---|---|
| `test_knowledge_base.py` | Policies, context rules, exceptions and constraints, against a hand-written expected-decisions fixture |
| `test_ingestion.py` | Every format and failure mode, with fixtures generated in `tmp_path`: text, image-only and encrypted PDFs; UTF-8, UTF-16 and cp1252 text; empty and oversize files; valid and malformed JSON; out-of-bounds annotations kept. Also checks that error messages never quote content. |
| `test_api.py` | Fictional identifiers posted through the stub, a masking fake and a deliberately broken echoing pipeline never appear in responses, audit rows, result rows or captured logs. Also covers file permissions, error indexes and codes, round-tripping through `GET /batches/{id}`, and health reporting. |
| `test_frontend_mock.py` | The demo mock validates and round-trips against `BatchResult` and matches its generator |
| `test_synthetic_dataset.py` | Offsets, determinism, recomputed k, fictional-data rules, edge-case content, and agreement with `PolicyEngine` |
| Agents / orchestration / evaluation | **[PLACEHOLDER]** |

**Test run at submission:** **[PLACEHOLDER: paste the `pytest` summary line from the final run]**

---

## 6. Evaluation

> **[PLACEHOLDER: fill only from the generated evaluation report.]** No number belongs in
> this section until `evaluation/` has produced it.

- **6.1 Datasets and splits** (ai4privacy dev/validation/test; PIIMB independent test): [PLACEHOLDER]
- **6.2 Detection metrics** (precision / recall / F1, per entity type): [PLACEHOLDER]
- **6.3 Annotation-validation results:** [PLACEHOLDER]
- **6.4 Redaction correctness and residual-PII rate:** [PLACEHOLDER]
- **6.5 Re-identification detection on the synthetic set** (planted risks flagged vs controls not flagged): [PLACEHOLDER]
- **6.6 Utility retained:** [PLACEHOLDER]
- **6.7 Runtime and LLM usage:** [PLACEHOLDER]

---

## 7. Prototype demonstration
See [`demo-script.md`](demo-script.md). The demo uses demo mode and fictional data only.

---

## 8. Limitations and next steps

**Known now**
- The API serves a withholding stub until the real pipeline lands. Documents are blocked, not redacted.
- No OCR: scanned PDFs are rejected with a clear error.
- No authentication, rate limiting or retention policy for `protected_store/` yet.
- The 0600 permission test is skipped on Windows, which doesn't enforce POSIX mode bits. It must be run on macOS or Linux.
- In the synthetic dataset, k for planted risks is measured against a closed 40-person registry. It shows the mechanism, not real-world population uniqueness.

**[PLACEHOLDER]** Limitations from agents, orchestration and evaluation.

---

## 9. Contributions
**[PLACEHOLDER: one line per team member, matching the README team table.]**

---

## Appendix A: Running the prototype

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn --factory privacy_review.api:create_app --app-dir backend
# open http://127.0.0.1:8000/ui/

cd backend && pytest
python scripts/make_frontend_mock.py        # regenerate the demo mock
python scripts/make_synthetic_dataset.py    # regenerate the synthetic dataset
```

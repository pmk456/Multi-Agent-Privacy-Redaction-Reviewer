# Multi-Agent Privacy Redaction Review

**Problem statement PS 247** — Generative AI Semester-End Hackathon, Alliance University.

A multi-agent system that finds personal information in documents, judges how risky each
piece of it is, applies an appropriate redaction, and then independently verifies that
what came out is actually safe to release.

> **Status — Review 1 (design).** Nothing under `backend/` is implemented yet. The modules
> are stubs with the interfaces we agreed, so the four of us can build in parallel without
> waiting on each other. The design is written up in [`docs/review-1`](docs/review-1).

## The one rule

Original documents and raw identifiers stay inside the protected backend.

What crosses the API boundary is redacted text, entity *categories*, risk scores,
verification findings and aggregate counts. Never an original identifier value.

This applies to log lines and temporary files as much as to HTTP responses. If you are
about to `print()` or log an entity's `value`, don't — log its `entity_id` instead.
`backend/tests/test_no_raw_pii_in_responses.py` exists to keep us honest about this.

## Team

| Member | Registration No. | Area | Works mostly in |
|---|---|---|---|
| Patan Musthakheem | 2023LCSE07AED636 | Architecture and integration | `backend/app/orchestrator/` |
| Pulagampalli Sai Mahima | 2023LCSE07AED635 | Frontend | `frontend/` |
| Diddekunta Jagan Mohan Reddy | 2023BCSE07AED200 | Backend and APIs | `backend/app/api/`, `backend/app/storage/` |
| Nandha Jyothi E | 2023BCSE07AED156 | Privacy engine and testing | `backend/app/engines/`, `backend/tests/` |

Dataset preparation, prompt design, Responsible AI safeguards and the written submissions
are shared between all four of us.

## Layout

```
backend/app/
  main.py            FastAPI entry point
  api/routes/        HTTP endpoints — the only thing the frontend talks to
  schemas/           Pydantic contracts between stages. Change these together, not alone.
  agents/            The five agents, one file each
  orchestrator/      LangGraph workflow + shared state
  engines/           Deterministic Python: detection, redaction, verification rules
  analytics/         Aggregate statistics for the review report
  storage/           SQLite metadata + the protected document store
  llm/               Claude API client
frontend/            HTML + Tailwind
knowledge_base/      Entity categories, sensitivity levels, redaction policy rules
data/                Local only — git-ignored, never commit documents
docs/review-1/       Slide deck and design report
```

## Getting started

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_lg

cp .env.example .env        # then put your Anthropic API key in .env
uvicorn app.main:app --reload --app-dir backend
```

The API then runs on <http://127.0.0.1:8000>, with docs at `/docs`.
Open `frontend/index.html` in a browser for the interface.

```bash
pytest backend/tests          # run the tests
```

## How we work

- `main` stays working. Nobody pushes to it directly.
- Branch per piece of work: `feature/<area>-<short-name>`, e.g. `feature/agents-risk-policy`.
- Open a pull request, get one review from somebody else, then merge.
- If you need to change anything in `backend/app/schemas/`, say so in the group first —
  those are the contracts every other slice is built against.

## Documents

| | |
|---|---|
| Review 1 slide deck | [`docs/review-1/Multi-Agent-Privacy-Redaction-Review.pptx`](docs/review-1/Multi-Agent-Privacy-Redaction-Review.pptx) |
| Review 1 design report | [`docs/review-1/Problem-Analysis-and-Solution-Design-Report.docx`](docs/review-1/Problem-Analysis-and-Solution-Design-Report.docx) |
| Architecture diagram | [`docs/assets/system-architecture.png`](docs/assets/system-architecture.png) |

![System architecture](docs/assets/system-architecture.png)

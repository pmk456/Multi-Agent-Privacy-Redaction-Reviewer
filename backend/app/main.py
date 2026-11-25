"""FastAPI entry point.

Run from the repository root:

    uvicorn app.main:app --reload --app-dir backend
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analytics, documents

app = FastAPI(
    title="Multi-Agent Privacy Redaction Review",
    description=(
        "PS 247. Detects personal information, assesses privacy risk, applies an "
        "adaptive redaction and independently verifies the result. Raw identifiers do "
        "not cross this boundary."
    ),
    version="0.1.0",
)

# The frontend is a static page opened from disk during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # TODO(Review 3): narrow this before the final demo
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(analytics.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}

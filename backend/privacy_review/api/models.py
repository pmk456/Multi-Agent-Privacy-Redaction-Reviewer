"""Request and error models for the HTTP layer. Result endpoints use `BatchResult` only."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from privacy_review.schemas import Annotation


class ReviewDocumentIn(BaseModel):
    # extra="ignore": unknown keys are dropped rather than echoed back in a validation error
    model_config = ConfigDict(extra="ignore")

    doc_id: Optional[str] = None
    text: str = Field(repr=False)
    annotations: Optional[list[Annotation]] = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    documents: list[ReviewDocumentIn] = Field(min_length=1)


class ItemError(BaseModel):
    """One rejected file or document. Identified by position - never by name or content."""

    file_index: Optional[int] = Field(default=None, description="0-based position in files[]")
    document_index: Optional[int] = Field(
        default=None, description="0-based position in documents[]"
    )
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: str
    code: str
    errors: list[ItemError] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    pipeline: Literal["stub", "live"]
    llm: bool

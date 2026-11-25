"""The output of the Adaptive Redaction Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.entities import Span
from app.schemas.policy import RedactionStrategy


class AppliedRedaction(BaseModel):
    entity_id: str
    strategy: RedactionStrategy
    original_span: Span
    output_span: Span = Field(description="Where it landed after earlier edits shifted offsets.")
    replacement: str = Field(description="What was written in. Safe to show.")


class RedactedDocument(BaseModel):
    document_id: str
    text: str = Field(description="Redacted text. Safe to return.")
    redactions: list[AppliedRedaction] = Field(default_factory=list)
    revision: int = Field(default=1, description="Increments on each remediation pass.")

"""Agent 3 output."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from privacy_review.schemas.entities import EntityType, Span
from privacy_review.schemas.policy import Strategy


class AppliedRedaction(BaseModel):
    entity_id: str
    entity_type: EntityType
    strategy: Strategy
    original_span: Span
    output_span: Optional[Span] = None       # None only if the replacement is empty
    replacement: str                         # safe to show


class Segment(BaseModel):
    """Maps a stretch of the redacted text back to the original."""

    out_start: int
    out_end: int
    orig_start: int
    orig_end: int
    replaced: bool


class RedactedDocument(BaseModel):
    doc_id: str
    text: str = Field(description="Redacted text. Safe to release once verified.")
    redactions: list[AppliedRedaction] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    revision: int = 0

    def to_original_span(self, out_span: Span) -> Optional[Span]:
        """Translate a span in the redacted text to the original, if it lies in kept text."""
        for seg in self.segments:
            if not seg.replaced and seg.out_start <= out_span.start and out_span.end <= seg.out_end:
                shift = seg.orig_start - seg.out_start
                return Span(start=out_span.start + shift, end=out_span.end + shift)
        return None

    def in_replacement(self, out_span: Span) -> bool:
        return any(
            seg.replaced and seg.out_start < out_span.end and out_span.start < seg.out_end
            for seg in self.segments
        )

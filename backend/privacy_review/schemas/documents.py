"""Input documents and supplied annotations."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Annotation(BaseModel):
    """A supplied annotation. Validated by Agent 1, never trusted blindly."""

    start: int
    end: int
    label: str                       # as supplied - mapped to EntityType during validation


class Document(BaseModel):
    doc_id: str
    text: str = Field(description="Original text. Never leaves the backend.")
    annotations: Optional[list[Annotation]] = None
    source: str = "input"
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def is_annotated(self) -> bool:
        return self.annotations is not None

    def __repr__(self) -> str:       # keep raw text out of tracebacks and logs
        return f"Document(doc_id={self.doc_id!r}, chars={len(self.text)}, annotated={self.is_annotated})"

    __str__ = __repr__

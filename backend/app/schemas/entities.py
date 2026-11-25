"""Entity records produced by the Privacy Intelligence Agent.

These are the contract between detection and everything downstream. `value` holds the
original text and must never be serialised into an API response - see `PublicEntity`.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EntityCategory(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"
    ADDRESS = "ADDRESS"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    DATE = "DATE"
    NATIONAL_ID = "NATIONAL_ID"          # Aadhaar, PAN, passport, ...
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
    ROLE_TITLE = "ROLE_TITLE"            # quasi-identifier
    AFFILIATION = "AFFILIATION"          # quasi-identifier
    MEDICAL = "MEDICAL"
    OTHER = "OTHER"


class DetectionSource(str, Enum):
    ANNOTATION = "annotation"    # came with the input
    PRESIDIO = "presidio"
    SPACY = "spacy"
    PATTERN = "pattern"          # our own regex rules
    LLM = "llm"


class Span(BaseModel):
    """Character offsets into the document text. End is exclusive."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end


class Entity(BaseModel):
    """One detected piece of personal information. Backend-only."""

    entity_id: str
    document_id: str
    category: EntityCategory
    span: Span
    value: str = Field(description="Original text. Never return this through the API.")
    context: str = Field(default="", description="Surrounding text, for risk scoring.")
    confidence: float = Field(ge=0.0, le=1.0)
    sources: list[DetectionSource] = Field(default_factory=list)

    # Set by annotation validation: did the supplied annotation hold up?
    annotation_confirmed: Optional[bool] = None
    annotation_note: Optional[str] = None

    def public(self) -> "PublicEntity":
        return PublicEntity(
            entity_id=self.entity_id,
            document_id=self.document_id,
            category=self.category,
            span=self.span,
            confidence=self.confidence,
            sources=self.sources,
        )


class PublicEntity(BaseModel):
    """What the frontend is allowed to see. Deliberately has no `value` field."""

    entity_id: str
    document_id: str
    category: EntityCategory
    span: Span
    confidence: float
    sources: list[DetectionSource] = Field(default_factory=list)


class EntityLink(BaseModel):
    """An edge in the cross-document entity graph (NetworkX)."""

    source_entity_id: str
    target_entity_id: str
    relation: str = Field(description="e.g. same_person, employed_by, located_at")
    confidence: float = Field(ge=0.0, le=1.0)

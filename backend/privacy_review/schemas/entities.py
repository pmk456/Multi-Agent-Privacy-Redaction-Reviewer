"""Entities and spans.

`DetectedEntity.value` is a `SecretStr`. Printing, logging or JSON-dumping an entity shows
`**********`; the real text is only reachable through `.raw()`, which makes every access
to an original identifier explicit and greppable.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class EntityType(str, Enum):
    """Canonical categories. Dataset and detector labels are mapped onto these."""

    PERSON = "PERSON"
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    STREET_ADDRESS = "STREET_ADDRESS"
    LOCATION = "LOCATION"
    POSTAL_CODE = "POSTAL_CODE"
    GPS_COORDINATE = "GPS_COORDINATE"
    DATE = "DATE"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    AGE = "AGE"
    GOVERNMENT_ID = "GOVERNMENT_ID"
    RECORD_IDENTIFIER = "RECORD_IDENTIFIER"  # customer / employee / medical record numbers
    FINANCIAL_ACCOUNT = "FINANCIAL_ACCOUNT"
    CREDENTIAL = "CREDENTIAL"
    ONLINE_IDENTIFIER = "ONLINE_IDENTIFIER"
    URL = "URL"
    DEVICE_IDENTIFIER = "DEVICE_IDENTIFIER"
    ORGANIZATION = "ORGANIZATION"
    OCCUPATION = "OCCUPATION"
    DEMOGRAPHIC = "DEMOGRAPHIC"
    MEDICAL_CONDITION = "MEDICAL_CONDITION"
    EVENT = "EVENT"
    UNKNOWN = "UNKNOWN"


class IdentifierClass(str, Enum):
    DIRECT = "direct_identifier"
    INDIRECT = "indirect_identifier"          # quasi-identifier
    SENSITIVE_ATTRIBUTE = "sensitive_attribute"
    NON_IDENTIFYING = "non_identifying"


class DetectionSource(str, Enum):
    ANNOTATION = "annotation"
    PRESIDIO = "presidio"
    SPACY = "spacy"
    PATTERN = "pattern"
    GAZETTEER = "gazetteer"
    LLM = "llm"
    VERIFICATION = "verification"       # added during remediation from an Agent 4 finding
    ADVERSARIAL = "adversarial"         # added during remediation from an Agent 5 finding


class Span(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Span":
        if self.end <= self.start:
            raise ValueError(f"span end ({self.end}) must be greater than start ({self.start})")
        return self

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def overlap_len(self, other: "Span") -> int:
        return max(0, min(self.end, other.end) - max(self.start, other.start))

    def iou(self, other: "Span") -> float:
        inter = self.overlap_len(other)
        union = self.length + other.length - inter
        return inter / union if union else 0.0

    def contains(self, other: "Span") -> bool:
        return self.start <= other.start and other.end <= self.end


class AnnotationStatus(str, Enum):
    CONFIRMED = "confirmed"              # detector agrees on span and type
    SPAN_MISMATCH = "span_mismatch"      # detector overlaps, boundaries differ
    TYPE_MISMATCH = "type_mismatch"      # detector overlaps, category differs
    UNCONFIRMED = "unconfirmed"          # detector found nothing there - kept, flagged
    INVALID = "invalid"                  # out of bounds / empty / unparseable - rejected
    NOT_ANNOTATED = "not_annotated"      # detector found PII the annotations missed


class DetectedEntity(BaseModel):
    """One piece of personal information. Backend-only."""

    entity_id: str
    doc_id: str
    entity_type: EntityType
    span: Span
    value: SecretStr
    confidence: float = Field(ge=0.0, le=1.0)
    sources: list[DetectionSource] = Field(default_factory=list)
    identifier_class: IdentifierClass = IdentifierClass.DIRECT
    original_label: Optional[str] = None         # label as given by annotation/detector
    annotation_status: Optional[AnnotationStatus] = None
    cluster_id: Optional[str] = None             # same real-world entity across docs
    sentence_index: Optional[int] = None
    ambiguous_person: bool = False               # a lone NER org/place that may be someone's first name

    def raw(self) -> str:
        """The original text. Every call site is a place raw PII is handled."""
        return self.value.get_secret_value()

    def public(self) -> "PublicEntity":
        return PublicEntity(
            entity_id=self.entity_id,
            doc_id=self.doc_id,
            entity_type=self.entity_type,
            span=self.span,
            confidence=self.confidence,
            identifier_class=self.identifier_class,
            annotation_status=self.annotation_status,
            cluster_id=self.cluster_id,
        )


class PublicEntity(BaseModel):
    """What may leave the backend. Deliberately has no value field."""

    entity_id: str
    doc_id: str
    entity_type: EntityType
    span: Span
    confidence: float
    identifier_class: IdentifierClass
    annotation_status: Optional[AnnotationStatus] = None
    cluster_id: Optional[str] = None


class EntityLink(BaseModel):
    """Edge in the cross-document entity graph."""

    source_cluster: str
    target_cluster: str
    relation: str                 # co_occurs_sentence | co_occurs_document | same_entity
    doc_ids: list[str] = Field(default_factory=list)
    weight: float = 1.0


class EntityCluster(BaseModel):
    """All mentions of the same real-world entity across the batch."""

    cluster_id: str
    entity_type: EntityType
    entity_ids: list[str]
    doc_ids: list[str]

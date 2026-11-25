"""What leaves the backend. Nothing here may carry an original identifier."""

from __future__ import annotations

from pydantic import BaseModel, Field

from privacy_review.schemas.entities import PublicEntity
from privacy_review.schemas.policy import RedactionDecision, RiskAssessment
from privacy_review.schemas.verification import (
    AdversarialReport,
    ReleaseDecision,
    VerificationReport,
)


class SanitizedDocument(BaseModel):
    doc_id: str
    released: bool
    redacted_text: str | None = Field(
        description="Only populated when the document passed the release gate."
    )
    entities: list[PublicEntity] = Field(default_factory=list)
    risks: list[RiskAssessment] = Field(default_factory=list)
    decisions: list[RedactionDecision] = Field(default_factory=list)
    verification: VerificationReport | None = None
    release: ReleaseDecision


class AggregateStatistics(BaseModel):
    document_count: int
    documents_released: int
    documents_blocked: int
    entities_by_type: dict[str, int] = Field(default_factory=dict)
    risks_by_level: dict[str, int] = Field(default_factory=dict)
    strategies: dict[str, int] = Field(default_factory=dict)
    findings_by_type: dict[str, int] = Field(default_factory=dict)
    remediation_rounds: int = 0
    llm_used: bool = False


class BatchResult(BaseModel):
    batch_id: str
    documents: list[SanitizedDocument]
    adversarial: AdversarialReport | None = None
    aggregate: AggregateStatistics

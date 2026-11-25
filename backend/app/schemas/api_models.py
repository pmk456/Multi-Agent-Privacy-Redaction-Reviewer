"""Request and response bodies. Nothing here may carry a raw identifier value."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.entities import PublicEntity
from app.schemas.policy import PolicyDecision, RiskAssessment
from app.schemas.verification import AdversarialReport, VerificationReport


class ReviewRequest(BaseModel):
    text: str | None = None
    annotations: list[dict] | None = Field(
        default=None, description="Supplied annotations. Validated, not trusted."
    )


class DocumentResult(BaseModel):
    document_id: str
    filename: str
    redacted_text: str
    entities: list[PublicEntity] = Field(default_factory=list)
    risks: list[RiskAssessment] = Field(default_factory=list)
    decisions: list[PolicyDecision] = Field(default_factory=list)
    verification: VerificationReport | None = None
    adversarial: AdversarialReport | None = None
    released: bool = False


class AggregateReport(BaseModel):
    """Counts only - this is what makes a multi-document view safe to show."""

    document_count: int
    entity_counts_by_category: dict[str, int] = Field(default_factory=dict)
    risk_counts_by_level: dict[str, int] = Field(default_factory=dict)
    strategy_counts: dict[str, int] = Field(default_factory=dict)
    findings_by_type: dict[str, int] = Field(default_factory=dict)
    documents_released: int = 0
    documents_blocked: int = 0


class ReviewResponse(BaseModel):
    batch_id: str
    documents: list[DocumentResult] = Field(default_factory=list)
    aggregate: AggregateReport

"""Shared workflow state.

Every agent reads from and writes to this. Fields are grouped by which agent owns them,
so if you are adding a field, add it under the agent that produces it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.entities import Entity, EntityLink
from app.schemas.policy import PolicyDecision, RiskAssessment
from app.schemas.redaction import RedactedDocument
from app.schemas.verification import AdversarialReport, VerificationReport


class SourceDocument(BaseModel):
    document_id: str
    filename: str
    text: str = Field(description="Original text. Stays in the backend.")


class ReviewState(BaseModel):
    batch_id: str

    # input
    documents: list[SourceDocument] = Field(default_factory=list)
    annotations: dict[str, list[dict]] = Field(
        default_factory=dict, description="document_id -> supplied annotations"
    )

    # agent 01
    entities: list[Entity] = Field(default_factory=list)
    entity_links: list[EntityLink] = Field(default_factory=list)

    # agent 02
    risks: list[RiskAssessment] = Field(default_factory=list)
    decisions: list[PolicyDecision] = Field(default_factory=list)

    # agent 03
    redacted_documents: list[RedactedDocument] = Field(default_factory=list)

    # agent 04
    verification_reports: list[VerificationReport] = Field(default_factory=list)

    # agent 05
    adversarial_reports: list[AdversarialReport] = Field(default_factory=list)

    # orchestration
    remediation_count: int = 0
    max_remediations: int = 2
    released: bool = False
    blocked_reason: str | None = None

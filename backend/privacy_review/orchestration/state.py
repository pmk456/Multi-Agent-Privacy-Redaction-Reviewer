"""Shared LangGraph state. Grouped by the agent that writes each field."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from privacy_review.agents.privacy_intelligence import IntelligenceResult
from privacy_review.agents.risk_policy import Remediation, RiskPolicyResult
from privacy_review.schemas.documents import Document
from privacy_review.schemas.entities import DetectedEntity
from privacy_review.schemas.redaction import RedactedDocument
from privacy_review.schemas.verification import AdversarialReport, ReleaseDecision, VerificationReport


class RoundSummary(BaseModel):
    round: int
    stage: str
    blocking: int
    warnings: int
    finding_types: dict[str, int] = Field(default_factory=dict)


class PipelineState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    batch_id: str
    documents: list[Document]
    max_rounds: int = 2

    # agent 1
    intelligence: Optional[IntelligenceResult] = None
    entities: list[DetectedEntity] = Field(default_factory=list)       # grows during remediation
    # agent 2
    risk: Optional[RiskPolicyResult] = None
    # agent 3
    redacted: list[RedactedDocument] = Field(default_factory=list)
    # agent 4
    verification: list[VerificationReport] = Field(default_factory=list)
    # agent 5
    adversarial: Optional[AdversarialReport] = None
    # orchestration
    round: int = 0
    remediation: Remediation = Field(default_factory=Remediation)
    stalled: bool = False
    history: list[RoundSummary] = Field(default_factory=list)
    release: list[ReleaseDecision] = Field(default_factory=list)
    llm_used: bool = False

    def __repr__(self) -> str:
        return f"PipelineState(batch={self.batch_id}, docs={len(self.documents)}, round={self.round})"

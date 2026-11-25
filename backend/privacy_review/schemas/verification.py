"""Agent 4 and Agent 5 output, and the release decision."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from privacy_review.schemas.entities import EntityType, Span
from privacy_review.schemas.policy import Strategy


class FindingType(str, Enum):
    RESIDUAL_PII = "residual_pii"
    ORIGINAL_VALUE_PRESENT = "original_value_present"
    INVALID_SPAN = "invalid_span"
    WRONG_TRANSFORMATION = "wrong_transformation"
    POLICY_VIOLATION = "policy_violation"
    INCONSISTENT_PSEUDONYM = "inconsistent_pseudonym"
    PSEUDONYM_COLLISION = "pseudonym_collision"
    OVER_REDACTION = "over_redaction"
    QUASI_IDENTIFIER_COMBINATION = "quasi_identifier_combination"
    CROSS_DOCUMENT_LINKAGE = "cross_document_linkage"
    UNIQUE_FINGERPRINT = "unique_fingerprint"
    LLM_REVIEW = "llm_review"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class Finding(BaseModel):
    finding_type: FindingType
    severity: Severity
    doc_id: str
    description: str = Field(description="Describes the problem without quoting any value.")
    entity_ids: list[str] = Field(default_factory=list)
    entity_type: Optional[EntityType] = None
    span: Optional[Span] = None                     # in the redacted text
    original_span: Optional[Span] = None            # mapped back, when possible
    recommended_strategy: Optional[Strategy] = None
    rule_id: Optional[str] = None
    related_doc_ids: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    doc_id: str
    revision: int
    passed: bool
    findings: list[Finding] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)
    utility_retained: float = Field(ge=0.0, le=1.0, default=1.0)
    llm_reviewed: bool = False

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.BLOCKING]


class LinkageComponent(BaseModel):
    component_id: str
    doc_ids: list[str]
    linked_by: list[str]                            # what links them, as attribute *types*
    visible_quasi_types: list[str]
    anonymity_set_size: int                         # k: how many people share this fingerprint
    risk: str
    subject_entity_ids: list[str] = Field(default_factory=list)   # the person this is about, if any


class AdversarialReport(BaseModel):
    revision: int
    safe_to_release: bool
    findings: list[Finding] = Field(default_factory=list)
    components: list[LinkageComponent] = Field(default_factory=list)
    llm_probed: bool = False

    def for_doc(self, doc_id: str) -> list[Finding]:
        return [f for f in self.findings if f.doc_id == doc_id or doc_id in f.related_doc_ids]


class ReleaseStatus(str, Enum):
    RELEASED = "released"
    BLOCKED = "blocked"


class ReleaseDecision(BaseModel):
    doc_id: str
    status: ReleaseStatus
    reason: str
    remediation_rounds: int

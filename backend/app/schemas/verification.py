"""Findings from the Independent Verification Agent and the Adversarial Privacy Agent.

Verification asks "was the redaction performed correctly".
Adversarial testing asks "is the result actually safe".
They are different questions and are reported separately on purpose.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.entities import EntityCategory, Span


class FindingType(str, Enum):
    MISSED_IDENTIFIER = "missed_identifier"
    INCORRECT_SPAN = "incorrect_span"
    INCONSISTENT_REDACTION = "inconsistent_redaction"
    POLICY_VIOLATION = "policy_violation"
    RESIDUAL_IDENTIFIER = "residual_identifier"
    INDIRECT_IDENTIFICATION = "indirect_identification"
    CROSS_DOCUMENT_LINKAGE = "cross_document_linkage"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class Finding(BaseModel):
    finding_type: FindingType
    severity: Severity
    document_id: str
    span: Span | None = None
    category: EntityCategory | None = None
    description: str = Field(description="Must describe the problem without quoting the value.")


class VerificationReport(BaseModel):
    document_id: str
    revision: int
    passed: bool
    findings: list[Finding] = Field(default_factory=list)
    detection_recall_note: str = Field(
        default="",
        description="Independent pass vs. first pass - where they disagreed.",
    )


class AdversarialReport(BaseModel):
    document_id: str
    revision: int
    safe_to_release: bool
    findings: list[Finding] = Field(default_factory=list)
    linkage_notes: list[str] = Field(default_factory=list)

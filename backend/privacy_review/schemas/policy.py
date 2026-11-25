"""Risk assessments and redaction decisions (Agent 2 -> Agent 3)."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from privacy_review.schemas.entities import EntityType


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return ["low", "medium", "high", "critical"].index(self.value)

    @classmethod
    def max(cls, *levels: "RiskLevel") -> "RiskLevel":
        return max(levels, key=lambda l: l.rank)


class Strategy(str, Enum):
    KEEP = "keep"
    MASK = "mask"                    # typed placeholder:  [EMAIL_ADDRESS]
    GENERALIZE = "generalize"        # 34 -> 30-39, Bengaluru -> Karnataka
    PSEUDONYMIZE = "pseudonymize"    # consistent token:   PERSON_7F3A
    SUPPRESS = "suppress"            # untyped removal:    [REDACTED]

    @property
    def strength(self) -> int:
        """How much information the strategy removes. Used to escalate, never to relax."""
        return {"keep": 0, "generalize": 1, "pseudonymize": 2, "mask": 3, "suppress": 4}[self.value]


class PseudonymScope(str, Enum):
    DOCUMENT = "document"            # unlinkable across documents
    BATCH = "batch"                  # consistent across the batch - preserves linkage


class RiskAssessment(BaseModel):
    entity_id: str
    entity_type: EntityType
    base_risk: RiskLevel
    risk: RiskLevel
    fired_rules: list[str] = Field(default_factory=list)
    rationale: str = Field(description="Explanation. Never quotes the raw value.")
    llm_escalated: bool = False


class RedactionDecision(BaseModel):
    entity_id: str
    entity_type: EntityType
    strategy: Strategy
    risk: RiskLevel
    policy_id: str
    scope: PseudonymScope = PseudonymScope.DOCUMENT
    generalization_level: int = 1
    rationale: str = ""
    remediation_round: int = 0

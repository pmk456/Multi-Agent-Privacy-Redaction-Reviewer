"""Risk scores and redaction policy decisions.

Produced by the Privacy Risk and Policy Agent, consumed by the Adaptive Redaction Agent.
The split matters: the risk agent decides *what should happen*, the redaction agent only
carries it out.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RedactionStrategy(str, Enum):
    MASK = "mask"                      # Rajesh -> [REDACTED] / ****
    GENERALIZE = "generalize"          # 1998-04-12 -> age band 25-30
    PSEUDONYMIZE = "pseudonymize"      # Rajesh -> PERSON_01, consistently
    SUPPRESS = "suppress"              # remove the span entirely
    KEEP = "keep"                      # not personal information after all


class RiskAssessment(BaseModel):
    entity_id: str
    risk_level: RiskLevel
    risk_score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="Why. Must not quote the raw value.")
    is_quasi_identifier: bool = False
    contributes_to_linkage: bool = False


class PolicyDecision(BaseModel):
    entity_id: str
    strategy: RedactionStrategy
    policy_rule: str = Field(description="Which rule in knowledge_base fired.")
    # Pseudonyms stable across a batch keep it readable but preserve linkage.
    # See the open question in the Review 1 report before changing the default.
    scope: str = Field(default="document", description="document | batch")
    replacement_hint: Optional[str] = None

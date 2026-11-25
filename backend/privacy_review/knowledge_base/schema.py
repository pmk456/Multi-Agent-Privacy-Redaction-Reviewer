"""Schema for the privacy knowledge base, plus structural validation.

`validate_knowledge_base()` returns a list of `KBIssue`s rather than raising, so the test
suite can assert on exactly which conflicts a deliberately broken KB produces.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from privacy_review.schemas.entities import EntityType, IdentifierClass
from privacy_review.schemas.policy import PseudonymScope, RiskLevel, Strategy

RISK_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]


class Defaults(BaseModel):
    unsupported_entity_risk: RiskLevel
    unsupported_entity_strategy: Strategy
    default_pseudonym_scope: PseudonymScope
    max_remediation_rounds: int = Field(ge=0, le=10)
    min_utility_retained: float = Field(ge=0.0, le=1.0)


class EntityPolicy(BaseModel):
    entity_type: EntityType
    identifier_class: IdentifierClass
    sensitivity: RiskLevel
    default_strategy: Strategy
    allowed_strategies: list[Strategy] = Field(min_length=1)
    strategy_by_risk: dict[RiskLevel, Strategy]
    verification_required: bool
    pseudonym_scope: Optional[PseudonymScope] = None
    risk_rules: list[str] = Field(default_factory=list)

    @field_validator("strategy_by_risk")
    @classmethod
    def _all_levels(cls, v: dict) -> dict:
        missing = set(RISK_ORDER) - set(v)
        if missing:
            raise ValueError(f"strategy_by_risk missing levels: {sorted(m.value for m in missing)}")
        return v


class ContextRule(BaseModel):
    rule_id: str
    name: str
    description: str
    scope: Literal["document", "sentence"]
    trigger_types: list[EntityType] = Field(min_length=1)
    min_distinct_types: int = Field(ge=1)
    requires_all: list[EntityType] = Field(default_factory=list)
    applies_to: list[EntityType] = Field(min_length=1)
    escalate_to: RiskLevel


class TransformationRules(BaseModel):
    mask_format: str
    suppress_token: str
    pseudonym_format: str
    pseudonym_prefixes: dict[str, str]
    generalization: dict[EntityType, dict[str, dict]]


class VerificationRule(BaseModel):
    rule_id: str
    check: str
    description: str
    severity: Optional[Literal["blocking", "warning", "info"]] = None
    severity_direct: Optional[Literal["blocking", "warning", "info"]] = None
    severity_indirect: Optional[Literal["blocking", "warning", "info"]] = None


class SpecificityWeight(BaseModel):
    specific: float = Field(ge=0.0, le=1.0)
    generalized: float = Field(ge=0.0, le=1.0)


class LinkageRules(BaseModel):
    rule_id: str
    description: str
    specificity_weights: dict[EntityType, SpecificityWeight]
    link_on_shared_pseudonym: bool
    link_on_shared_specific_values: int = Field(ge=1)
    high_risk_threshold: float = Field(gt=0.0, le=1.0)
    medium_risk_threshold: float = Field(gt=0.0, le=1.0)
    min_anonymity_set: int = Field(ge=1)
    uniqueness_cues: list[str] = Field(default_factory=list)
    uniqueness_cue_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    high_risk_combinations: list[list[EntityType]]


class PolicyConstraint(BaseModel):
    constraint_id: str
    entity_types: list[EntityType]
    forbidden_strategies: list[Strategy]
    reason: str


class PolicyException(BaseModel):
    """Narrow, explicit relaxations. Applied after context escalation, so they are the
    last word - which is exactly why the validator forbids them on protected types."""

    exception_id: str
    entity_type: EntityType
    condition: Literal["isolated_in_sentence", "no_person_or_direct_identifier_in_document"]
    effect: Literal["cap_risk"]
    value: RiskLevel
    unless_rules: list[str] = Field(default_factory=list)
    description: str


class KnowledgeBase(BaseModel):
    version: str
    description: str
    defaults: Defaults
    entity_policies: list[EntityPolicy]
    context_rules: list[ContextRule]
    transformation_rules: TransformationRules
    verification_rules: list[VerificationRule]
    linkage_rules: LinkageRules
    policy_constraints: list[PolicyConstraint]
    exceptions: list[PolicyException]
    reference_data: dict

    @classmethod
    def from_json(cls, path: Path | str) -> "KnowledgeBase":
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    def policy_for(self, entity_type: EntityType) -> Optional[EntityPolicy]:
        return next((p for p in self.entity_policies if p.entity_type == entity_type), None)

    def forbidden_for(self, entity_type: EntityType) -> set[Strategy]:
        out: set[Strategy] = set()
        for c in self.policy_constraints:
            if entity_type in c.entity_types:
                out.update(c.forbidden_strategies)
        return out


# ---------------------------------------------------------------------------- validation

class IssueKind(str, Enum):
    MISSING_POLICY = "missing_policy"
    DUPLICATE_POLICY = "duplicate_policy"
    DEFAULT_NOT_ALLOWED = "default_not_allowed"
    RISK_STRATEGY_NOT_ALLOWED = "risk_strategy_not_allowed"
    NON_MONOTONIC = "non_monotonic_strategy"
    CONSTRAINT_CONFLICT = "constraint_conflict"
    DIRECT_IDENTIFIER_KEPT = "direct_identifier_kept"
    CRITICAL_KEPT = "critical_sensitivity_kept"
    DUPLICATE_RULE_ID = "duplicate_rule_id"
    RULE_REFERENCE = "invalid_rule_reference"
    CONTRADICTORY_CONTEXT_RULES = "contradictory_context_rules"
    THRESHOLD_ORDER = "threshold_order"
    MISSING_GENERALIZATION = "missing_generalization"
    DUPLICATE_REFERENCE = "duplicate_reference_entry"
    EXCEPTION_ON_PROTECTED = "exception_on_protected_type"


class KBIssue(BaseModel):
    kind: IssueKind
    subject: str
    detail: str


def validate_knowledge_base(kb: KnowledgeBase) -> list[KBIssue]:
    """Semantic checks the Pydantic schema cannot express on its own."""
    issues: list[KBIssue] = []
    add = lambda k, s, d: issues.append(KBIssue(kind=k, subject=s, detail=d))  # noqa: E731

    # coverage + duplicates
    seen: dict[EntityType, int] = {}
    for p in kb.entity_policies:
        seen[p.entity_type] = seen.get(p.entity_type, 0) + 1
    for et in EntityType:
        if et == EntityType.UNKNOWN:
            continue
        if seen.get(et, 0) == 0:
            add(IssueKind.MISSING_POLICY, et.value, "no entity policy defined")
        elif seen[et] > 1:
            add(IssueKind.DUPLICATE_POLICY, et.value, f"{seen[et]} policies defined")

    for p in kb.entity_policies:
        name = p.entity_type.value
        allowed = set(p.allowed_strategies)
        forbidden = kb.forbidden_for(p.entity_type)

        if p.default_strategy not in allowed:
            add(IssueKind.DEFAULT_NOT_ALLOWED, name, f"default '{p.default_strategy.value}' not in allowed_strategies")
        for lvl, strat in p.strategy_by_risk.items():
            if strat not in allowed:
                add(IssueKind.RISK_STRATEGY_NOT_ALLOWED, name, f"{lvl.value} -> '{strat.value}' not in allowed_strategies")

        # higher risk must never mean a weaker strategy
        prev = None
        for lvl in RISK_ORDER:
            s = p.strategy_by_risk[lvl]
            if prev is not None and s.strength < prev[1].strength:
                add(IssueKind.NON_MONOTONIC, name,
                    f"{lvl.value} -> '{s.value}' is weaker than {prev[0].value} -> '{prev[1].value}'")
            prev = (lvl, s)

        for s in {p.default_strategy, *p.strategy_by_risk.values(), *allowed} & forbidden:
            add(IssueKind.CONSTRAINT_CONFLICT, name, f"'{s.value}' is used or allowed but forbidden by a policy constraint")

        if p.identifier_class == IdentifierClass.DIRECT and Strategy.KEEP in {p.default_strategy, *p.strategy_by_risk.values()}:
            add(IssueKind.DIRECT_IDENTIFIER_KEPT, name, "a direct identifier may be released unchanged")
        if p.sensitivity == RiskLevel.CRITICAL and Strategy.KEEP in allowed:
            add(IssueKind.CRITICAL_KEPT, name, "critical sensitivity allows 'keep'")

        if Strategy.GENERALIZE in {p.default_strategy, *p.strategy_by_risk.values()} \
                and p.entity_type not in kb.transformation_rules.generalization:
            add(IssueKind.MISSING_GENERALIZATION, name, "uses 'generalize' but has no generalization rule")

    # rule ids
    ids = [r.rule_id for r in kb.context_rules] + [r.rule_id for r in kb.verification_rules] \
        + [c.constraint_id for c in kb.policy_constraints] + [e.exception_id for e in kb.exceptions] \
        + [kb.linkage_rules.rule_id]
    for rid in {i for i in ids if ids.count(i) > 1}:
        add(IssueKind.DUPLICATE_RULE_ID, rid, "rule id used more than once")

    for r in kb.context_rules:
        if not set(r.requires_all) <= set(r.trigger_types) | set(r.applies_to):
            add(IssueKind.RULE_REFERENCE, r.rule_id, "requires_all names a type that is neither a trigger nor a target")
        if r.min_distinct_types > len(r.trigger_types):
            add(IssueKind.RULE_REFERENCE, r.rule_id, "min_distinct_types exceeds the number of trigger types")

    # Two rules with the same trigger set and targets but different escalation are a
    # specification conflict: whichever the author meant, one of them is wrong.
    seen_ctx: dict[tuple, ContextRule] = {}
    for r in kb.context_rules:
        key = (r.scope, frozenset(r.trigger_types), frozenset(r.requires_all),
               r.min_distinct_types, frozenset(r.applies_to))
        if key in seen_ctx and seen_ctx[key].escalate_to != r.escalate_to:
            add(IssueKind.CONTRADICTORY_CONTEXT_RULES, f"{seen_ctx[key].rule_id}/{r.rule_id}",
                f"identical triggers escalate to '{seen_ctx[key].escalate_to.value}' and '{r.escalate_to.value}'")
        seen_ctx.setdefault(key, r)

    known_rules = {r.rule_id for r in kb.context_rules}
    for e in kb.exceptions:
        pol = kb.policy_for(e.entity_type)
        if pol is None or pol.identifier_class != IdentifierClass.INDIRECT \
                or pol.sensitivity.rank >= RiskLevel.HIGH.rank:
            add(IssueKind.EXCEPTION_ON_PROTECTED, e.exception_id,
                f"exceptions may only relax low/medium indirect identifiers, not {e.entity_type.value}")
        for rid in e.unless_rules:
            if rid not in known_rules:
                add(IssueKind.RULE_REFERENCE, e.exception_id, f"unless_rules names unknown rule '{rid}'")

    lr = kb.linkage_rules
    if lr.medium_risk_threshold >= lr.high_risk_threshold:
        add(IssueKind.THRESHOLD_ORDER, lr.rule_id, "medium_risk_threshold must be below high_risk_threshold")
    for et, w in lr.specificity_weights.items():
        if w.generalized > w.specific:
            add(IssueKind.THRESHOLD_ORDER, f"{lr.rule_id}:{et.value}", "generalized weight exceeds specific weight")

    for key in ("role_nouns", "seniority_words", "job_titles"):
        vals = kb.reference_data.get(key, [])
        for v in {x for x in vals if vals.count(x) > 1}:
            add(IssueKind.DUPLICATE_REFERENCE, f"{key}:{v}", "duplicate entry")

    return issues

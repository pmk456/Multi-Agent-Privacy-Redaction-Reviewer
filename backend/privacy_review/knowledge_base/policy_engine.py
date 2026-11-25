"""The single place agents ask "what does policy say?".

Agent 2 uses it to decide, Agent 4 uses it to check those decisions independently. Neither
hard-codes a strategy: change policies.json and both follow.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from privacy_review.knowledge_base.database import KnowledgeBaseDB
from privacy_review.knowledge_base.schema import KnowledgeBase, KBIssue, validate_knowledge_base
from privacy_review.schemas.entities import DetectedEntity, EntityType, IdentifierClass
from privacy_review.schemas.policy import PseudonymScope, RiskLevel, Strategy

DIRECT_CLASSES = {IdentifierClass.DIRECT}


@dataclass
class ContextOutcome:
    escalate_to: RiskLevel
    rule_ids: list[str] = field(default_factory=list)


class InvalidKnowledgeBase(ValueError):
    def __init__(self, issues: list[KBIssue]):
        self.issues = issues
        super().__init__("knowledge base failed validation:\n" + "\n".join(
            f"  - {i.kind.value}: {i.subject}: {i.detail}" for i in issues))


class PolicyEngine:
    def __init__(self, kb: KnowledgeBase, db: KnowledgeBaseDB | None = None, *, strict: bool = True):
        if strict:
            issues = validate_knowledge_base(kb)
            if issues:
                raise InvalidKnowledgeBase(issues)
        self.kb = kb
        self.db = db or KnowledgeBaseDB().build(kb)

    @classmethod
    def from_json(cls, path: Path | str, *, strict: bool = True) -> "PolicyEngine":
        return cls(KnowledgeBase.from_json(path), strict=strict)

    # ------------------------------------------------------------- per entity
    def is_supported(self, et: EntityType) -> bool:
        return self.db.has_policy(et)

    def identifier_class(self, et: EntityType) -> IdentifierClass:
        row = self.db.policy_row(et)
        # Unsupported types are treated as direct identifiers: fail closed.
        return IdentifierClass(row["identifier_class"]) if row else IdentifierClass.DIRECT

    def sensitivity(self, et: EntityType) -> RiskLevel:
        row = self.db.policy_row(et)
        return RiskLevel(row["sensitivity"]) if row else self.kb.defaults.unsupported_entity_risk

    def verification_required(self, et: EntityType) -> bool:
        row = self.db.policy_row(et)
        return bool(row["verification_required"]) if row else True

    def pseudonym_scope(self, et: EntityType) -> PseudonymScope:
        row = self.db.policy_row(et)
        if row and row["pseudonym_scope"]:
            return PseudonymScope(row["pseudonym_scope"])
        return self.kb.defaults.default_pseudonym_scope

    def allowed(self, et: EntityType) -> set[Strategy]:
        if not self.is_supported(et):
            return {self.kb.defaults.unsupported_entity_strategy, Strategy.SUPPRESS}
        return self.db.allowed_strategies(et) - self.db.forbidden_strategies(et)

    def is_compliant(self, et: EntityType, strategy: Strategy) -> bool:
        return strategy in self.allowed(et)

    def strategy_for(self, et: EntityType, risk: RiskLevel) -> Strategy:
        if not self.is_supported(et):
            return self.kb.defaults.unsupported_entity_strategy
        s = self.db.strategy_for(et, risk)
        if s is not None and self.is_compliant(et, s):
            return s
        # Policy lookup failed or is forbidden: take the strongest permitted strategy.
        return max(self.allowed(et), key=lambda x: x.strength)

    def escalate(self, et: EntityType, current: Strategy) -> Strategy:
        """Next strictly stronger permitted strategy, used in remediation. Never weakens."""
        stronger = sorted((s for s in self.allowed(et) if s.strength > current.strength), key=lambda s: s.strength)
        return stronger[0] if stronger else current

    # ------------------------------------------------------------- risk
    def assess(self, entity: DetectedEntity, doc_entities: list[DetectedEntity],
               escalations: dict[str, "ContextOutcome"]) -> tuple[RiskLevel, RiskLevel, list[str]]:
        """(base_risk, final_risk, rule_ids) for one entity.

        base = policy sensitivity; final = base raised by any context rule, then capped by an
        exception whose condition holds and whose unless_rules did not fire.
        """
        base = self.sensitivity(entity.entity_type)
        final, fired = base, []
        ctx = escalations.get(entity.entity_id)
        if ctx:
            final = RiskLevel.max(final, ctx.escalate_to)
            fired = list(ctx.rule_ids)
        doc_fired = {rid for outcome in escalations.values() for rid in outcome.rule_ids}
        for exc in self.kb.exceptions:
            if exc.entity_type != entity.entity_type:
                continue
            # "unless CTX-02" means unless this entity is *part of* a CTX-02 match - including
            # as a trigger the rule did not itself escalate (the location in a triangulation).
            if any(rid in doc_fired and entity.entity_type in self._participants(rid) for rid in exc.unless_rules):
                continue
            if self._exception_condition(exc.condition, entity, doc_entities) and exc.value.rank < final.rank:
                final = exc.value
                fired.append(exc.exception_id)
        return base, final, fired

    def _participants(self, rule_id: str) -> set[EntityType]:
        rule = next((r for r in self.kb.context_rules if r.rule_id == rule_id), None)
        return set() if rule is None else {*rule.trigger_types, *rule.requires_all, *rule.applies_to}

    def _exception_condition(self, condition: str, entity: DetectedEntity, doc_entities: list[DetectedEntity]) -> bool:
        others = [e for e in doc_entities if e.entity_id != entity.entity_id]
        if condition == "isolated_in_sentence":
            return entity.sentence_index is not None and not any(
                e.sentence_index == entity.sentence_index for e in others)
        if condition == "no_person_or_direct_identifier_in_document":
            return not any(self._identifies_person(e) for e in others)
        return False

    def _identifies_person(self, e: DetectedEntity) -> bool:
        return e.entity_type == EntityType.PERSON or self.identifier_class(e.entity_type) in DIRECT_CLASSES

    def context_escalations(self, doc_entities: list[DetectedEntity]) -> dict[str, ContextOutcome]:
        """Apply every context rule to one document's entities. entity_id -> escalation."""
        out: dict[str, ContextOutcome] = {}

        def fire(rule, group):
            present = {e.entity_type for e in group}
            trigger_hits = present & set(rule.trigger_types)
            if len(trigger_hits) < rule.min_distinct_types:
                return
            if not set(rule.requires_all) <= present:
                return
            for e in group:
                if e.entity_type in rule.applies_to:
                    cur = out.get(e.entity_id)
                    if cur is None:
                        out[e.entity_id] = ContextOutcome(rule.escalate_to, [rule.rule_id])
                    else:
                        cur.escalate_to = RiskLevel.max(cur.escalate_to, rule.escalate_to)
                        if rule.rule_id not in cur.rule_ids:
                            cur.rule_ids.append(rule.rule_id)

        for rule in self.kb.context_rules:
            if rule.scope == "document":
                fire(rule, doc_entities)
            else:
                by_sentence: dict[int | None, list[DetectedEntity]] = defaultdict(list)
                for e in doc_entities:
                    by_sentence[e.sentence_index].append(e)
                for sent_idx, group in by_sentence.items():
                    if sent_idx is not None:
                        fire(rule, group)
        return out

    # ------------------------------------------------------------- reference data
    @property
    def reference(self) -> dict:
        return self.kb.reference_data

    @property
    def transformation(self):
        return self.kb.transformation_rules

    @property
    def linkage(self):
        return self.kb.linkage_rules

    @property
    def defaults(self):
        return self.kb.defaults


@lru_cache
def default_engine() -> PolicyEngine:
    from privacy_review.config import get_settings
    return PolicyEngine.from_json(get_settings().knowledge_base_json)

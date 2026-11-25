"""Routing decisions and remediation planning. Pure functions - unit-testable without a graph."""

from __future__ import annotations

import re
from collections import Counter

from pydantic import SecretStr

from privacy_review.agents.risk_policy import Remediation
from privacy_review.detection.spacy_processor import SpacyProcessor
from privacy_review.knowledge_base import PolicyEngine
from privacy_review.orchestration.state import PipelineState, RoundSummary
from privacy_review.schemas.entities import DetectedEntity, DetectionSource, EntityType, Span
from privacy_review.schemas.policy import PseudonymScope, Strategy
from privacy_review.schemas.verification import Finding, FindingType, Severity


def blocking_verification(state: PipelineState) -> list[Finding]:
    return [f for r in state.verification for f in r.findings if f.severity == Severity.BLOCKING]


def blocking_adversarial(state: PipelineState) -> list[Finding]:
    if not state.adversarial:
        return []
    return [f for f in state.adversarial.findings if f.severity == Severity.BLOCKING]


def route_after_verification(state: PipelineState) -> str:
    if blocking_verification(state) and state.round < state.max_rounds and not state.stalled:
        return "remediate"
    return "adversarial"            # clean, or out of rounds: Agent 5 still reports, the gate decides


def route_after_adversarial(state: PipelineState) -> str:
    if (blocking_adversarial(state) or blocking_verification(state)) and state.round < state.max_rounds \
            and not state.stalled:
        return "remediate"
    return "release"


def summarise(round_: int, stage: str, findings: list[Finding]) -> RoundSummary:
    return RoundSummary(round=round_, stage=stage,
                        blocking=sum(f.severity == Severity.BLOCKING for f in findings),
                        warnings=sum(f.severity == Severity.WARNING for f in findings),
                        finding_types=dict(Counter(f.finding_type.value for f in findings)))


def plan_remediation(state: PipelineState, policy: PolicyEngine) -> tuple[Remediation, list[DetectedEntity], bool]:
    """Turn blocking findings into stricter decisions. Returns (remediation, new entities, changed?).

    Only ever tightens: floors rise, scopes narrow to document, entities are added - never removed.
    """
    rem = state.remediation.model_copy(deep=True)
    ents = {e.entity_id: e for e in state.entities}
    texts = {d.doc_id: d.text for d in state.documents}
    starts = state.intelligence.sentence_starts if state.intelligence else {}
    current = {d.entity_id: d for d in (state.risk.decisions if state.risk else [])}
    new: list[DetectedEntity] = []
    changed = False

    def raise_floor(eid: str, target: Strategy | None, why: str):
        nonlocal changed
        e = ents.get(eid)
        if e is None:
            return
        cur = current.get(eid)
        base = cur.strategy if cur else Strategy.KEEP
        if target is None or target.strength < base.strength or \
                (target == base and target != Strategy.GENERALIZE):
            target = policy.escalate(e.entity_type, base)
        if not policy.is_compliant(e.entity_type, target):
            target = policy.escalate(e.entity_type, base)
        old = rem.strategy_floor.get(eid)
        if old is None or target.strength > old.strength or (target == Strategy.GENERALIZE and old is None):
            rem.strategy_floor[eid] = target
            rem.reasons[eid] = why
            changed = True

    def add_entity(doc_id: str, span: Span, et: EntityType, source: DetectionSource, cluster: str | None, why: str,
                   floor: Strategy | None = None):
        nonlocal changed
        text = texts[doc_id]
        if span.end > len(text) or not text[span.start:span.end].strip():
            return
        for e in list(ents.values()) + new:
            if e.doc_id == doc_id and e.span.overlaps(span):
                raise_floor(e.entity_id, floor, why)
                return
        eid = f"{doc_id}:r{state.round}-{len(new)}"
        ent = DetectedEntity(entity_id=eid, doc_id=doc_id, entity_type=et, span=span,
                             value=SecretStr(text[span.start:span.end]), confidence=0.6, sources=[source],
                             identifier_class=policy.identifier_class(et), original_label=source.value,
                             cluster_id=cluster or f"R{state.round}-{len(new)}",
                             sentence_index=SpacyProcessor.sentence_index(starts.get(doc_id, [0]), span.start))
        new.append(ent)
        if floor is not None:
            rem.strategy_floor[eid] = floor
            rem.reasons[eid] = why
        changed = True

    for f in blocking_verification(state) + blocking_adversarial(state):
        why = f"{f.rule_id}:{f.finding_type.value}"
        if f.finding_type == FindingType.ORIGINAL_VALUE_PRESENT and not f.entity_ids and f.original_span and f.entity_type:
            add_entity(f.doc_id, f.original_span, f.entity_type, DetectionSource.VERIFICATION, None, why)
        elif f.finding_type == FindingType.ORIGINAL_VALUE_PRESENT:
            for eid in f.entity_ids:                       # redact every other occurrence too
                e = ents.get(eid)
                if e is None:
                    continue
                for m in re.finditer(rf"(?<!\w){re.escape(e.raw().strip())}(?!\w)", texts[e.doc_id], re.I):
                    add_entity(e.doc_id, Span(start=m.start(), end=m.end()), e.entity_type,
                               DetectionSource.VERIFICATION, e.cluster_id, why)
        elif (f.rule_id or "").endswith(":pseudonym"):
            for eid in f.entity_ids:
                e = ents.get(eid)
                if e is None:
                    continue
                for other in ents.values():                # the whole cluster, in every document
                    if other.cluster_id == e.cluster_id and rem.scope.get(other.entity_id) != PseudonymScope.DOCUMENT:
                        rem.scope[other.entity_id] = PseudonymScope.DOCUMENT
                        changed = True
        elif f.entity_ids:
            for eid in f.entity_ids:
                raise_floor(eid, f.recommended_strategy, why)
        elif f.original_span is not None and f.entity_type is not None:
            source = DetectionSource.ADVERSARIAL if f.finding_type in (
                FindingType.CROSS_DOCUMENT_LINKAGE, FindingType.QUASI_IDENTIFIER_COMBINATION,
                FindingType.UNIQUE_FINGERPRINT) else DetectionSource.VERIFICATION
            add_entity(f.doc_id, f.original_span, f.entity_type, source, None, why, f.recommended_strategy)
    return rem, new, changed

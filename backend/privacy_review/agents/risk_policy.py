"""Agent 2 - Privacy Risk and Policy.

Decides, per entity, how risky it is *in context* and what should happen to it. Every
decision comes from the knowledge base; this agent hard-codes no strategy.

  in : entities from Agent 1 (+ remediation overrides from later rounds)
  out: RiskAssessment and RedactionDecision per entity, with explanations that never quote
       a value

The optional LLM step sees tokenized text only ("[PERSON_1] works as [OCCUPATION_1] at
[ORGANIZATION_1]") and may only *raise* a risk level, never lower it below what policy set.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from pydantic import BaseModel, Field

from privacy_review.knowledge_base import PolicyEngine
from privacy_review.llm import Reasoner, tokenize
from privacy_review.schemas.entities import DetectedEntity, EntityType
from privacy_review.schemas.policy import PseudonymScope, RedactionDecision, RiskAssessment, RiskLevel, Strategy


class LLMRiskReview(BaseModel):
    class Item(BaseModel):
        placeholder: str = Field(description="A placeholder exactly as it appears, e.g. [OCCUPATION_1]")
        risk: RiskLevel
        reason: str = Field(description="Why. Refer to placeholders only.")

    items: list[Item] = Field(default_factory=list)


class Remediation(BaseModel):
    """What later rounds ask Agent 2 to do differently. Only ever makes decisions stricter."""

    strategy_floor: dict[str, Strategy] = Field(default_factory=dict)       # entity_id -> at least this
    scope: dict[str, PseudonymScope] = Field(default_factory=dict)          # entity_id -> forced scope
    reasons: dict[str, str] = Field(default_factory=dict)


class RiskPolicyResult(BaseModel):
    assessments: list[RiskAssessment]
    decisions: list[RedactionDecision]
    llm_used: bool = False


class PrivacyRiskPolicyAgent:
    name = "risk_policy"

    def __init__(self, policy: PolicyEngine, reasoner: Reasoner | None = None):
        self.policy = policy
        self.reasoner = reasoner

    def run(self, entities: list[DetectedEntity], texts: dict[str, str] | None = None,
            remediation: Remediation | None = None, round_: int = 0) -> RiskPolicyResult:
        remediation = remediation or Remediation()
        by_doc: dict[str, list[DetectedEntity]] = defaultdict(list)
        for e in entities:
            by_doc[e.doc_id].append(e)

        assessments, decisions, llm_used = [], [], False
        for doc_id, ents in by_doc.items():
            esc = self.policy.context_escalations(ents)
            llm = self._llm_review(texts.get(doc_id), ents) if texts else None
            llm_used = llm_used or llm is not None
            for e in ents:
                base, final, rules = self.policy.assess(e, ents, esc)
                llm_escalated = False
                if llm and e.entity_id in llm and llm[e.entity_id].rank > final.rank:
                    final, llm_escalated = llm[e.entity_id], True
                    rules = rules + ["LLM-ESCALATION"]
                assessments.append(RiskAssessment(
                    entity_id=e.entity_id, entity_type=e.entity_type, base_risk=base, risk=final,
                    fired_rules=rules, llm_escalated=llm_escalated,
                    rationale=self._rationale(e.entity_type, base, final, rules)))
                decisions.append(self._decide(e, base, final, rules, remediation, round_))
        return RiskPolicyResult(assessments=assessments, decisions=decisions, llm_used=llm_used)

    # ---------------------------------------------------------------- decide
    def _decide(self, e: DetectedEntity, base: RiskLevel, risk: RiskLevel, rules: list[str],
                remediation: Remediation, round_: int) -> RedactionDecision:
        et = e.entity_type
        strategy = self.policy.strategy_for(et, risk)
        policy_id = f"POLICY:{et.value}:{risk.value}" if self.policy.is_supported(et) else "DEFAULT:unsupported"
        rationale = f"policy maps {et.value} at {risk.value} risk to {strategy.value}"

        floor = remediation.strategy_floor.get(e.entity_id)
        if floor is not None and floor.strength > strategy.strength:
            strategy = floor if self.policy.is_compliant(et, floor) else self.policy.escalate(et, strategy)
            rationale += f"; raised to {strategy.value} in remediation ({remediation.reasons.get(e.entity_id, 'finding')})"

        scope = remediation.scope.get(e.entity_id, self.policy.pseudonym_scope(et))
        # Coarser generalisation only when *context* pushed the risk up to high - otherwise
        # an entity whose baseline is already high (date of birth) could never get level 1.
        level = 2 if risk.rank >= RiskLevel.HIGH.rank and risk.rank > base.rank else 1
        if e.entity_id in remediation.strategy_floor and strategy == Strategy.GENERALIZE:
            level = 2                                       # remediation asked for less detail
        return RedactionDecision(entity_id=e.entity_id, entity_type=et, strategy=strategy, risk=risk,
                                 policy_id=policy_id, scope=scope, generalization_level=level,
                                 rationale=rationale, remediation_round=round_)

    @staticmethod
    def _rationale(et: EntityType, base: RiskLevel, final: RiskLevel, rules: list[str]) -> str:
        msg = f"{et.value}: policy sensitivity {base.value}"
        if final != base:
            msg += f", {'raised' if final.rank > base.rank else 'capped'} to {final.value}"
        if rules:
            msg += f" by {', '.join(rules)}"
        return msg

    # ---------------------------------------------------------------- optional LLM
    def _llm_review(self, text: Optional[str], ents: list[DetectedEntity]) -> Optional[dict[str, RiskLevel]]:
        if not (self.reasoner and self.reasoner.available and text and ents):
            return None
        tokenized, keys = tokenize(text, ents)
        system = ("You assess re-identification risk. The document's personal information has been replaced "
                  "by placeholders. For each placeholder whose risk is HIGHER than its category suggests "
                  "because of the context it appears in, return the placeholder and a risk level. "
                  "Return nothing for placeholders that are not unusually risky.")
        out = self.reasoner.structured(purpose="agent2_risk", system=system,
                                       prompt=f"<document>\n{tokenized}\n</document>", output_format=LLMRiskReview)
        if out is None:
            return None
        cluster_of = {e.entity_id: (e.cluster_id or e.entity_id) for e in ents}
        result: dict[str, RiskLevel] = {}
        for item in out.items:
            eid = keys.get(item.placeholder)
            if eid is None:
                continue                                    # unknown placeholder: ignore, never guess
            for e in ents:                                  # same cluster shares the placeholder
                if cluster_of[e.entity_id] == cluster_of[eid]:
                    result[e.entity_id] = RiskLevel.max(result.get(e.entity_id, RiskLevel.LOW), item.risk)
        return result

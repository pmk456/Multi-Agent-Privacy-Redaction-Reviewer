"""LangGraph workflow. Orchestration only - every decision lives in an agent or the KB.

  START -> intelligence -> risk_policy -> redaction -> verification
             verification --(blocking, rounds left)--> remediate -> risk_policy ...
             verification --(otherwise)-------------> adversarial
             adversarial  --(blocking, rounds left)--> remediate
             adversarial  --(otherwise)-------------> release -> END
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from privacy_review.agents.adaptive_redaction import AdaptiveRedactionAgent
from privacy_review.agents.adversarial_privacy import AdversarialPrivacyAgent
from privacy_review.agents.independent_verification import IndependentVerificationAgent
from privacy_review.agents.privacy_intelligence import PrivacyIntelligenceAgent
from privacy_review.agents.risk_policy import PrivacyRiskPolicyAgent
from privacy_review.config import Settings, get_settings
from privacy_review.detection import EntityExtractor
from privacy_review.knowledge_base import PolicyEngine
from privacy_review.llm import ClaudeReasoner, Reasoner
from privacy_review.orchestration.routing import (
    blocking_adversarial, blocking_verification, plan_remediation, route_after_adversarial,
    route_after_verification, summarise,
)
from privacy_review.orchestration.state import PipelineState
from privacy_review.schemas.verification import ReleaseDecision, ReleaseStatus, Severity

log = logging.getLogger(__name__)


class Pipeline:
    """Builds the five agents once (models load once) and compiles the graph."""

    def __init__(self, policy: PolicyEngine, settings: Settings | None = None, reasoner: Reasoner | None = None):
        self.settings = settings or get_settings()
        self.policy = policy
        self.reasoner = reasoner if reasoner is not None else ClaudeReasoner(self.settings)
        primary = EntityExtractor(policy, self.settings)
        independent = EntityExtractor(policy, self.settings, threshold=self.settings.verification_score_threshold)
        self.a1 = PrivacyIntelligenceAgent(policy, extractor=primary, reasoner=self.reasoner, settings=self.settings)
        self.a2 = PrivacyRiskPolicyAgent(policy, reasoner=self.reasoner)
        self.a3 = AdaptiveRedactionAgent(policy, self.settings)
        self.a4 = IndependentVerificationAgent(policy, self.settings, extractor=independent, reasoner=self.reasoner)
        self.a5 = AdversarialPrivacyAgent(policy, self.settings, extractor=independent, reasoner=self.reasoner)
        self.graph = self._build()

    # ------------------------------------------------------------------ nodes
    def _intelligence(self, s: PipelineState) -> dict:
        res = self.a1.run(s.documents)
        return {"intelligence": res, "entities": res.entities, "llm_used": s.llm_used or res.llm_used}

    def _risk_policy(self, s: PipelineState) -> dict:
        texts = {d.doc_id: d.text for d in s.documents}
        res = self.a2.run(s.entities, texts, s.remediation, s.round)
        return {"risk": res, "llm_used": s.llm_used or res.llm_used}

    def _redaction(self, s: PipelineState) -> dict:
        return {"redacted": self.a3.run(s.documents, s.entities, s.risk.decisions, s.batch_id, s.round)}

    def _verification(self, s: PipelineState) -> dict:
        reps = self.a4.run(s.documents, s.redacted, s.entities, s.risk.decisions)
        hist = s.history + [summarise(s.round, "verification", [f for r in reps for f in r.findings])]
        return {"verification": reps, "history": hist, "llm_used": s.llm_used or any(r.llm_reviewed for r in reps)}

    def _adversarial(self, s: PipelineState) -> dict:
        rep = self.a5.run(s.documents, s.redacted, s.entities, s.risk.decisions, revision=s.round)
        hist = s.history + [summarise(s.round, "adversarial", rep.findings)]
        return {"adversarial": rep, "history": hist, "llm_used": s.llm_used or rep.llm_probed}

    def _remediate(self, s: PipelineState) -> dict:
        rem, new, changed = plan_remediation(s, self.policy)
        if not changed:
            log.info("remediation round %d produced no change; stopping", s.round + 1)
            return {"stalled": True}
        return {"remediation": rem, "entities": s.entities + new, "round": s.round + 1, "adversarial": None}

    def _release(self, s: PipelineState) -> dict:
        vrep = {r.doc_id: r for r in s.verification}
        adv = blocking_adversarial(s)
        out = []
        for d in s.documents:
            v = vrep.get(d.doc_id)
            doc_adv = [f for f in adv if f.doc_id == d.doc_id or d.doc_id in f.related_doc_ids]
            reasons = []
            if v is None or not v.passed:
                kinds = sorted({f.finding_type.value for f in (v.findings if v else []) if f.severity == Severity.BLOCKING})
                reasons.append(f"verification failed ({', '.join(kinds) or 'no report'})")
            if doc_adv:
                reasons.append(f"re-identification risk ({', '.join(sorted({f.finding_type.value for f in doc_adv}))})")
            status = ReleaseStatus.BLOCKED if reasons else ReleaseStatus.RELEASED
            reason = "; ".join(reasons) if reasons else "independently verified and adversarially checked"
            if reasons and s.stalled:
                reason += "; no further automatic remediation possible"
            elif reasons:
                reason += f"; still failing after {s.round} remediation round(s)"
            out.append(ReleaseDecision(doc_id=d.doc_id, status=status, reason=reason, remediation_rounds=s.round))
        return {"release": out}

    # ------------------------------------------------------------------ graph
    def _build(self):
        g = StateGraph(PipelineState)
        for name, fn in [("intelligence", self._intelligence), ("risk_policy", self._risk_policy),
                         ("redaction", self._redaction), ("verification", self._verification),
                         ("adversarial", self._adversarial), ("remediate", self._remediate), ("release", self._release)]:
            g.add_node(name, fn)
        g.add_edge(START, "intelligence")
        g.add_edge("intelligence", "risk_policy")
        g.add_edge("risk_policy", "redaction")
        g.add_edge("redaction", "verification")
        g.add_conditional_edges("verification", route_after_verification,
                                {"remediate": "remediate", "adversarial": "adversarial"})
        g.add_conditional_edges("adversarial", route_after_adversarial,
                                {"remediate": "remediate", "release": "release"})
        g.add_conditional_edges("remediate", lambda s: "release" if s.stalled else "risk_policy",
                                {"release": "adversarial_or_release", "risk_policy": "risk_policy"}
                                if False else {"release": "release", "risk_policy": "risk_policy"})
        g.add_edge("release", END)
        return g.compile()

    def invoke(self, state: PipelineState) -> PipelineState:
        # each round is 4-5 node visits; give generous head-room over max_rounds
        out = self.graph.invoke(state, config={"recursion_limit": 20 + 10 * state.max_rounds})
        return out if isinstance(out, PipelineState) else PipelineState(**out)

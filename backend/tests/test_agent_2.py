"""Agent 2 - Privacy Risk and Policy: sensitivity, policy selection, risk, strategy."""

from __future__ import annotations

import copy

import pytest

from privacy_review.agents.risk_policy import LLMRiskReview, PrivacyRiskPolicyAgent, Remediation
from privacy_review.knowledge_base import KnowledgeBase, PolicyEngine
from privacy_review.schemas import Document, EntityType as E, PseudonymScope, RiskLevel, Strategy
from tests.conftest import PROFILE_DOCS_TEXT


@pytest.fixture(scope="module")
def profile(agents):
    a1, a2, *_ = agents
    docs = [Document(doc_id=k, text=v) for k, v in PROFILE_DOCS_TEXT.items()]
    intel = a1.run(docs)
    res = a2.run(intel.entities, {d.doc_id: d.text for d in docs})
    text = {d.doc_id: d.text for d in docs}
    by_value = {(e.doc_id, text[e.doc_id][e.span.start:e.span.end]): e.entity_id for e in intel.entities}
    return intel, res, by_value


def _dec(profile, doc, value):
    _, res, by_value = profile
    eid = by_value[(doc, value)]
    return next(d for d in res.decisions if d.entity_id == eid), next(a for a in res.assessments if a.entity_id == eid)


@pytest.mark.parametrize("doc,value,strategy", [
    ("hr", "ananya.rao@example.com", Strategy.MASK),
    ("hr", "+1-202-555-0143", Strategy.MASK),
    ("hr", "906-43-6765", Strategy.SUPPRESS),
    ("hr", "Ananya Rao", Strategy.PSEUDONYMIZE),
    ("hr", "34 years old", Strategy.GENERALIZE),
    ("hr", "12/03/1989", Strategy.GENERALIZE),
    ("hr", "Principal Data Scientist", Strategy.GENERALIZE),
    ("news", "3 February 2025", Strategy.KEEP),
])
def test_strategy_selection(profile, doc, value, strategy):
    d, _ = _dec(profile, doc, value)
    assert d.strategy == strategy


def test_sensitivity_and_context_risk(profile):
    _, occ = _dec(profile, "hr", "Principal Data Scientist")
    assert occ.base_risk == RiskLevel.LOW and occ.risk == RiskLevel.HIGH
    assert "CTX-02" in occ.fired_rules                       # workplace triangulation
    _, gov = _dec(profile, "hr", "906-43-6765")
    assert gov.risk == RiskLevel.CRITICAL


def test_dateline_exception_applies(profile):
    _, a = _dec(profile, "news", "3 February 2025")
    assert "EXC-01" in a.fired_rules and a.risk == RiskLevel.LOW


def test_every_entity_gets_exactly_one_decision(profile):
    intel, res, _ = profile
    assert sorted(d.entity_id for d in res.decisions) == sorted(e.entity_id for e in intel.entities)


def test_every_decision_is_policy_compliant(profile, engine):
    _, res, _ = profile
    for d in res.decisions:
        assert engine.is_compliant(d.entity_type, d.strategy), d


def test_explanations_never_quote_values(profile):
    intel, res, _ = profile
    values = [e.raw() for e in intel.entities]
    for text in [a.rationale for a in res.assessments] + [d.rationale for d in res.decisions]:
        assert not [v for v in values if len(v) > 3 and v in text]


def test_person_pseudonyms_are_batch_scoped_by_policy(profile):
    d, _ = _dec(profile, "hr", "Ananya Rao")
    assert d.scope == PseudonymScope.BATCH


def test_context_escalation_uses_level_2_generalisation(profile):
    occ, _ = _dec(profile, "hr", "Principal Data Scientist")     # raised low -> high by context
    dob, _ = _dec(profile, "hr", "12/03/1989")                   # high by baseline, not raised
    assert occ.generalization_level == 2 and dob.generalization_level == 1


class TestRemediation:
    def test_floor_raises_strategy(self, profile, agents):
        intel, _, by_value = profile
        a2 = agents[1]
        eid = by_value[("news", "3 February 2025")]
        res = a2.run(intel.entities, remediation=Remediation(strategy_floor={eid: Strategy.GENERALIZE}), round_=1)
        d = next(x for x in res.decisions if x.entity_id == eid)
        assert d.strategy == Strategy.GENERALIZE and d.remediation_round == 1

    def test_floor_never_lowers(self, profile, agents):
        intel, _, by_value = profile
        eid = by_value[("hr", "906-43-6765")]
        res = agents[1].run(intel.entities, remediation=Remediation(strategy_floor={eid: Strategy.KEEP}))
        assert next(x for x in res.decisions if x.entity_id == eid).strategy == Strategy.SUPPRESS

    def test_scope_override(self, profile, agents):
        intel, _, by_value = profile
        eid = by_value[("hr", "Ananya Rao")]
        res = agents[1].run(intel.entities, remediation=Remediation(scope={eid: PseudonymScope.DOCUMENT}))
        assert next(x for x in res.decisions if x.entity_id == eid).scope == PseudonymScope.DOCUMENT


class TestLLMEscalation:
    def _agent(self, engine, fake_reasoner, items):
        return PrivacyRiskPolicyAgent(engine, reasoner=fake_reasoner({"agent2_risk": LLMRiskReview(items=items)}))

    def test_llm_can_raise_risk(self, profile, engine, fake_reasoner):
        intel, _, by_value = profile
        a2 = self._agent(engine, fake_reasoner, [LLMRiskReview.Item(placeholder="[DATE_1]", risk=RiskLevel.HIGH, reason="x")])
        res = a2.run(intel.entities, PROFILE_DOCS_TEXT)
        eid = by_value[("news", "3 February 2025")]
        a = next(x for x in res.assessments if x.entity_id == eid)
        assert a.llm_escalated and a.risk == RiskLevel.MEDIUM and res.llm_used   # low -> medium, not high

    def test_llm_cannot_lower_risk(self, profile, engine, fake_reasoner):
        intel, _, by_value = profile
        a2 = self._agent(engine, fake_reasoner, [LLMRiskReview.Item(placeholder="[GOVERNMENT_ID_1]", risk=RiskLevel.LOW, reason="x")])
        res = a2.run(intel.entities, PROFILE_DOCS_TEXT)
        eid = by_value[("hr", "906-43-6765")]
        assert next(x for x in res.decisions if x.entity_id == eid).strategy == Strategy.SUPPRESS

    def test_unknown_placeholder_ignored(self, profile, engine, fake_reasoner):
        intel, base, _ = profile
        a2 = self._agent(engine, fake_reasoner, [LLMRiskReview.Item(placeholder="[NOPE_9]", risk=RiskLevel.CRITICAL, reason="x")])
        res = a2.run(intel.entities, PROFILE_DOCS_TEXT)
        assert [d.strategy for d in res.decisions] == [d.strategy for d in base.decisions]

    def test_llm_only_sees_tokenized_text(self, profile, engine, fake_reasoner):
        intel, _, _ = profile
        fake = fake_reasoner({"agent2_risk": LLMRiskReview()})
        PrivacyRiskPolicyAgent(engine, reasoner=fake).run(intel.entities, PROFILE_DOCS_TEXT)
        sent = "\n".join(fake.prompts)
        assert "Ananya" not in sent and "ananya.rao@example.com" not in sent and "906-43-6765" not in sent
        assert "[PERSON_1]" in sent


def test_policy_change_changes_agent_decision(profile, kb_json):
    intel, _, by_value = profile
    data = copy.deepcopy(kb_json)
    p = next(x for x in data["entity_policies"] if x["entity_type"] == "EMAIL_ADDRESS")
    p["strategy_by_risk"]["high"] = "suppress"
    res = PrivacyRiskPolicyAgent(PolicyEngine(KnowledgeBase.model_validate(data))).run(intel.entities)
    eid = by_value[("hr", "ananya.rao@example.com")]
    assert next(x for x in res.decisions if x.entity_id == eid).strategy == Strategy.SUPPRESS


def test_unsupported_type_is_suppressed(engine, entity_factory):
    e = entity_factory("UNKNOWN", 0, value="mystery")
    res = PrivacyRiskPolicyAgent(engine).run([e])
    assert res.decisions[0].strategy == Strategy.SUPPRESS


@pytest.mark.parametrize("current,proposed,expected", [
    ("low", "critical", "medium"), ("medium", "critical", "high"), ("high", "critical", "critical"),
    ("high", "low", "high"), ("medium", "medium", "medium"),
])
def test_llm_raise_is_bounded_to_one_level(current, proposed, expected):
    assert RiskLevel(current).llm_raise(RiskLevel(proposed)) == RiskLevel(expected)

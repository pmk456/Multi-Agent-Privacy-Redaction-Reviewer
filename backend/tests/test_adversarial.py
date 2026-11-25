"""Adversarial tests: break the system on purpose, check it notices."""

from __future__ import annotations

import copy

import pytest

from privacy_review.agents.risk_policy import PrivacyRiskPolicyAgent
from privacy_review.knowledge_base import InvalidKnowledgeBase, KnowledgeBase, PolicyEngine
from privacy_review.orchestration.graph import Pipeline
from privacy_review.orchestration.runner import run_pipeline, to_batch_result
from privacy_review.schemas import Annotation, Document, ReleaseStatus, Strategy


def test_direct_removed_but_indirect_remain(pipeline):
    t = "The only female surgeon at Lakeview Clinic in Kochi, aged 52, led the transplant team."
    s = run_pipeline([Document(doc_id="d", text=t)], pipeline=pipeline)
    assert any(h.stage == "adversarial" and h.blocking for h in s.history)


def test_documents_that_together_reveal_identity(pipeline):
    docs = [Document(doc_id="a", text="Meera Iyer is the Lead Systems Architect at Kestrel Analytics."),
            Document(doc_id="b", text="Meera Iyer, 41, led the Kestrel Analytics cloud migration in Chennai."),
            Document(doc_id="c", text="Meera Iyer was the only woman on the Kestrel Analytics board in 2024.")]
    s = run_pipeline(docs, pipeline=pipeline)
    adv = [h for h in s.history if h.stage == "adversarial"]
    assert adv[0].blocking > 0                             # first look: linkable
    r = to_batch_result(s)
    released = [d for d in r.documents if d.released]
    for d in released:
        assert "Kestrel" not in d.redacted_text            # anything released has the link coarsened


class _WrongRiskAgent(PrivacyRiskPolicyAgent):
    """An Agent 2 that wrongly marks every email as safe to keep."""

    def run(self, *a, **kw):
        res = super().run(*a, **kw)
        res.decisions = [d.model_copy(update={"strategy": Strategy.KEEP}) if d.entity_type.value == "EMAIL_ADDRESS"
                         and d.remediation_round == 0 and not kw.get("remediation", None) else d for d in res.decisions]
        return res


def test_agent_wrongly_marking_safe_is_overruled(pipeline):
    bad = copy.copy(pipeline)
    bad.a2 = _WrongRiskAgent(pipeline.policy)
    bad.graph = bad._build()
    s = run_pipeline([Document(doc_id="d", text="Reach me at kiran.rao@example.com tomorrow.")], pipeline=bad)
    first = s.history[0]
    assert first.stage == "verification" and first.blocking >= 1       # Agent 4 caught it
    r = to_batch_result(s)
    assert "kiran.rao@example.com" not in (r.documents[0].redacted_text or "")


def test_incomplete_redaction_never_released(pipeline):
    """An Agent 3 that silently skips the phone number."""
    from privacy_review.agents.adaptive_redaction import AdaptiveRedactionAgent

    class Skipper(AdaptiveRedactionAgent):
        def run(self, documents, entities, decisions, batch_id, revision=0):
            return super().run(documents, [e for e in entities if e.entity_type.value != "PHONE_NUMBER"], decisions, batch_id, revision)

    bad = copy.copy(pipeline)
    bad.a3 = Skipper(pipeline.policy, pipeline.settings, registry=pipeline.a3.registry)
    bad.graph = bad._build()
    s = run_pipeline([Document(doc_id="d", text="Call +1-202-555-0188 for details.")], pipeline=bad)
    r = to_batch_result(s)
    d = r.documents[0]
    assert d.release.status == ReleaseStatus.BLOCKED and d.redacted_text is None


def test_over_redaction_is_reported(pipeline):
    docs = [Document(doc_id="d", text="Ravi Shah, ravi@example.com, +1-202-555-0123.")]
    s = run_pipeline(docs, pipeline=pipeline)
    assert any(f.finding_type.value == "over_redaction" for r in s.verification for f in r.findings)


def test_conflicting_kb_is_refused(kb_json):
    data = copy.deepcopy(kb_json)
    data["context_rules"].append({**copy.deepcopy(data["context_rules"][1]), "rule_id": "CTX-77", "escalate_to": "low"})
    with pytest.raises(InvalidKnowledgeBase):
        PolicyEngine(KnowledgeBase.model_validate(data))


@pytest.mark.parametrize("doc", [
    Document(doc_id="empty", text=""),
    Document(doc_id="space", text="   \n\t  "),
    Document(doc_id="unicode", text="Zoë Ångström (zoe@example.com) — 東京 🙂 visited."),
    Document(doc_id="ctrl", text="Name:\x00\x07 Arjun Das\r\nPhone: +1-202-555-0144"),
    Document(doc_id="bad_ann", text="Arjun Das", annotations=[Annotation(start=5, end=500, label="???"),
                                                                Annotation(start=3, end=1, label="PERSON")]),
    Document(doc_id="long", text=("Arjun Das wrote this. " * 400)),
])
def test_malformed_or_unusual_input_does_not_crash(pipeline, doc):
    s = run_pipeline([doc], pipeline=pipeline)
    r = to_batch_result(s)
    d = r.documents[0]
    assert d.release.status in (ReleaseStatus.RELEASED, ReleaseStatus.BLOCKED)
    if d.released and doc.doc_id in ("ctrl", "unicode", "long"):
        assert "Arjun" not in d.redacted_text and "zoe@example.com" not in d.redacted_text

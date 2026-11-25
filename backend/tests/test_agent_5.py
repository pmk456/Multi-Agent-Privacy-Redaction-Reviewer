"""Agent 5 - Adversarial Privacy: quasi-identifiers, linkage, re-identification, false positives."""

from __future__ import annotations

import pytest

from privacy_review.agents.adversarial_privacy import AdversarialPrivacyAgent, LLMAttackerProbe
from privacy_review.schemas import Document, FindingType, PseudonymScope, RiskLevel, Severity, Strategy
from tests.conftest import run_through

RISKY = [Document(doc_id="C", text="The only woman speaker from Orion Biolabs at the Global AI Summit 2024 was aged 34.")]
CROWD = [Document(doc_id=f"N{i}", text="A nurse at City Hospital in Mumbai submitted the weekly roster on Monday.") for i in range(3)]
LINKED = [Document(doc_id="hr", text="Meera Iyer is a Lead Systems Architect at Kestrel Analytics."),
          Document(doc_id="memo", text="Meera Iyer will present the Kestrel Analytics roadmap in Chennai on 4 March 2025."),
          Document(doc_id="bio", text="Meera Iyer, 41, previously led the Kestrel Analytics cloud migration in Chennai.")]


def adversary(agents, docs, hook=None):
    intel, risk, decisions, red = run_through(agents, docs, "A", hook)
    return agents[4].run(docs, red, intel.entities, decisions), intel, decisions


def test_crowd_is_not_flagged(agents):
    rep, _, _ = adversary(agents, CROWD)
    assert rep.safe_to_release
    assert all(c.anonymity_set_size >= 3 for c in rep.components)
    assert not [f for f in rep.findings if f.severity == Severity.BLOCKING]


def test_uniqueness_phrase_with_quasi_identifiers_is_flagged(agents):
    rep, _, _ = adversary(agents, RISKY)
    assert not rep.safe_to_release
    assert any(f.finding_type == FindingType.QUASI_IDENTIFIER_COMBINATION for f in rep.findings)


def test_recommendations_target_visible_attributes(agents):
    rep, intel, decisions = adversary(agents, RISKY)
    blocking = [f for f in rep.findings if f.severity == Severity.BLOCKING and f.entity_ids]
    assert blocking and all(f.recommended_strategy is not None for f in blocking)
    ids = {e.entity_id for e in intel.entities}
    assert all(set(f.entity_ids) <= ids for f in blocking)


def test_pseudonym_links_documents(agents):
    rep, _, _ = adversary(agents, LINKED)
    comp = max(rep.components, key=lambda c: len(c.doc_ids))
    assert set(comp.doc_ids) == {"hr", "memo", "bio"}
    assert "shared_pseudonym" in comp.linked_by


def test_document_scoped_pseudonyms_break_the_link(agents):
    hook = lambda ds, _: [d.model_copy(update={"scope": PseudonymScope.DOCUMENT}) for d in ds]
    rep, _, _ = adversary(agents, LINKED, hook)
    assert all("shared_pseudonym" not in c.linked_by for c in rep.components)


def test_shared_specific_values_link_without_pseudonyms(agents):
    """Even with names suppressed, identical visible employer + city can join documents."""
    docs = [Document(doc_id="x1", text="The architect at Kestrel Analytics in Chennai approved it."),
            Document(doc_id="x2", text="Kestrel Analytics in Chennai hired a new lead.")]
    hook = lambda ds, _: [d.model_copy(update={"strategy": Strategy.KEEP}) if d.entity_type.value in ("ORGANIZATION", "LOCATION")
                          else d for d in ds]
    rep, _, _ = adversary(agents, docs, hook)
    comp = max(rep.components, key=lambda c: len(c.doc_ids))
    assert set(comp.doc_ids) == {"x1", "x2"} and any(w.startswith("shared_") for w in comp.linked_by)


def test_visible_quasi_identifiers_reported_by_type_only(agents):
    rep, intel, _ = adversary(agents, LINKED)
    values = [e.raw() for e in intel.entities if len(e.raw()) > 3]
    blob = rep.model_dump_json()
    assert not [v for v in values if v in blob]


def test_llm_probe_can_raise_but_not_lower(engine, agents, fake_reasoner):
    intel, risk, decisions, red = run_through(agents, CROWD, "P")
    up = AdversarialPrivacyAgent(engine, extractor=agents[4].extractor,
                                 reasoner=fake_reasoner({"agent5_probe": LLMAttackerProbe(risk=RiskLevel.HIGH, reason="x")}))
    rep = up.run(CROWD, red, intel.entities, decisions)
    assert rep.llm_probed
    # one level at most: a crowd the deterministic score calls low becomes medium (a warning),
    # never a block on the LLM's word alone
    assert rep.safe_to_release and all(c.risk in ("low", "medium") for c in rep.components)
    intel2, _, d2, red2 = run_through(agents, RISKY, "P2")
    down = AdversarialPrivacyAgent(engine, extractor=agents[4].extractor,
                                   reasoner=fake_reasoner({"agent5_probe": LLMAttackerProbe(risk=RiskLevel.LOW, reason="x")}))
    assert not down.run(RISKY, red2, intel2.entities, d2).safe_to_release


def test_llm_probe_sees_only_redacted_text(engine, agents, fake_reasoner):
    intel, _, decisions, red = run_through(agents, LINKED, "P3")
    fake = fake_reasoner({"agent5_probe": LLMAttackerProbe(risk=RiskLevel.LOW, reason="x")})
    AdversarialPrivacyAgent(engine, extractor=agents[4].extractor, reasoner=fake).run(LINKED, red, intel.entities, decisions)
    sent = "\n".join(fake.prompts)
    assert "Meera" not in sent and "Iyer" not in sent

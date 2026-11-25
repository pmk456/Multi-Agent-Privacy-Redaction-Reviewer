"""Agent 4 - Independent Verification. Each test injects one specific fault and checks that
the matching rule catches it; the clean run must pass."""

from __future__ import annotations

import pytest

from privacy_review.schemas import Document, FindingType, Severity, Strategy
from privacy_review.schemas.redaction import AppliedRedaction
from tests.conftest import PROFILE_DOCS_TEXT, run_through

DOCS = [Document(doc_id=k, text=v) for k, v in PROFILE_DOCS_TEXT.items()]


def verify(agents, docs=DOCS, hook=None, tamper=None, drop_entity=None):
    if drop_entity is None:
        intel, risk, decisions, red = run_through(agents, docs, "V", hook)
        ents = intel.entities
    else:
        # simulate Agent 1 missing something: the entity never reaches Agents 2 and 3
        a1, a2, a3, _, _ = agents
        intel = a1.run(docs)
        ents = [e for e in intel.entities if not drop_entity(e)]
        decisions = a2.run(ents).decisions
        red = a3.run(docs, ents, decisions, "V")
    if tamper:
        red = tamper(red)
    return {r.doc_id: r for r in agents[3].run(docs, red, ents, decisions)}, intel


def kinds(rep, sev=Severity.BLOCKING):
    return {(f.rule_id, f.finding_type) for f in rep.findings if f.severity == sev}


def test_clean_run_passes(agents):
    reps, _ = verify(agents)
    assert all(r.passed for r in reps.values()), {k: kinds(r) for k, r in reps.items()}
    assert set(reps["hr"].checks_run) >= {f"VR-0{i}" for i in range(1, 9)}


def test_does_not_trust_a_wrong_decision(agents):
    """Agent 2 (faulty) decides KEEP for the email; Agent 4 must re-derive policy and block."""
    hook = lambda ds, _: [d.model_copy(update={"strategy": Strategy.KEEP}) if d.entity_type.value == "EMAIL_ADDRESS" else d for d in ds]
    reps, _ = verify(agents, hook=hook)
    assert ("VR-05", FindingType.POLICY_VIOLATION) in kinds(reps["hr"]) and not reps["hr"].passed


def test_weaker_but_permitted_strategy_is_caught(agents):
    """Generalising an age that context made 'high' is allowed in general but weaker than required."""
    hook = lambda ds, _: [d.model_copy(update={"strategy": Strategy.KEEP}) if d.entity_type.value == "OCCUPATION" else d for d in ds]
    reps, _ = verify(agents, hook=hook)
    assert ("VR-05", FindingType.POLICY_VIOLATION) in kinds(reps["hr"])


def test_entity_missed_by_agent_1_is_found_independently(agents):
    """Simulate Agent 1 missing the phone number entirely."""
    reps, _ = verify(agents, drop_entity=lambda e: e.entity_type.value == "PHONE_NUMBER")
    assert ("VR-01", FindingType.RESIDUAL_PII) in kinds(reps["hr"])
    f = next(f for f in reps["hr"].findings if f.finding_type == FindingType.RESIDUAL_PII and f.entity_type.value == "PHONE_NUMBER")
    assert f.original_span is not None                         # mapped back for remediation


def test_original_value_elsewhere_is_caught(agents):
    docs = [Document(doc_id="x", text="Ananya Rao (ananya.rao@example.com) applied. Copy sent to ananya.rao@example.com")]
    # the second email mention is hidden from Agent 3 by dropping its entity
    intel, risk, decisions, red = run_through(agents, docs, "V2")
    emails = sorted((e for e in intel.entities if e.entity_type.value == "EMAIL_ADDRESS"), key=lambda e: e.span.start)
    keep = [e for e in intel.entities if e.entity_id != emails[-1].entity_id]
    red = agents[2].run(docs, keep, decisions, "V2")
    rep = agents[3].run(docs, red, keep, [d for d in decisions if d.entity_id in {e.entity_id for e in keep}])[0]
    assert ("VR-02", FindingType.ORIGINAL_VALUE_PRESENT) in kinds(rep)


def test_tampered_replacement_is_caught(agents):
    def tamper(red):
        r = next(x for x in red if x.doc_id == "hr")
        a = next(a for a in r.redactions if a.strategy == Strategy.MASK)
        bad = a.model_copy(update={"replacement": "[EMAIL]"})                   # wrong format, wrong span text
        r.redactions = [bad if x is a else x for x in r.redactions]
        return red
    reps, _ = verify(agents, tamper=tamper)
    got = kinds(reps["hr"])
    assert ("VR-03", FindingType.INVALID_SPAN) in got and ("VR-04", FindingType.WRONG_TRANSFORMATION) in got


def test_generalisation_that_reproduces_the_value_is_caught(agents):
    def tamper(red):
        r = next(x for x in red if x.doc_id == "hr")
        a = next(a for a in r.redactions if a.strategy == Strategy.GENERALIZE and a.entity_type.value == "LOCATION")
        r.redactions = [x.model_copy(update={"replacement": "Pune"}) if x is a else x for x in r.redactions]
        return red
    reps, _ = verify(agents, tamper=tamper)
    assert ("VR-04", FindingType.WRONG_TRANSFORMATION) in kinds(reps["hr"])


def test_inconsistent_pseudonyms_are_caught(agents):
    def tamper(red):
        r = next(x for x in red if x.doc_id == "news")
        r.redactions = [x.model_copy(update={"replacement": "PERSON_07"}) if x.strategy == Strategy.PSEUDONYMIZE else x
                        for x in r.redactions]
        return red
    reps, _ = verify(agents, tamper=tamper)
    assert any(ft == FindingType.INCONSISTENT_PSEUDONYM for _, ft in kinds(reps["news"]))


def test_missing_decision_is_caught(agents):
    intel, risk, decisions, red = run_through(agents, DOCS, "V3")
    rep = {r.doc_id: r for r in agents[3].run(DOCS, red, intel.entities, decisions[1:])}
    assert any(rid == "VR-08" for r in rep.values() for rid, _ in kinds(r))


def test_over_redaction_is_a_warning_not_a_block(agents):
    hook = lambda ds, _: [d.model_copy(update={"strategy": Strategy.SUPPRESS}) for d in ds]
    reps, _ = verify(agents, hook=hook)
    warn = {ft for _, ft in kinds(reps["news"], Severity.WARNING)}
    assert FindingType.OVER_REDACTION in warn
    assert reps["news"].utility_retained < 1.0


def test_findings_never_quote_values(agents):
    reps, intel = verify(agents, drop_entity=lambda e: e.entity_type.value == "PHONE_NUMBER")
    values = [e.raw() for e in intel.entities if len(e.raw()) > 3]
    for r in reps.values():
        for f in r.findings:
            assert not [v for v in values if v in f.description]

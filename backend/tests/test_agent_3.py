"""Agent 3 - Adaptive Redaction: masking, generalisation, pseudonyms, suppression, integrity."""

from __future__ import annotations

import os
import sqlite3

import pytest

from privacy_review.redaction import PseudonymRegistry, generalize
from privacy_review.redaction.generalization import age_band, decade, month_year, prefix, round_coords
from privacy_review.schemas import Document, EntityType as E, PseudonymScope, Strategy
from tests.conftest import PROFILE_DOCS_TEXT, run_through


@pytest.fixture(scope="module")
def profile(agents):
    docs = [Document(doc_id=k, text=v) for k, v in PROFILE_DOCS_TEXT.items()]
    intel, risk, decisions, red = run_through(agents, docs, "B3")
    return docs, intel, decisions, {r.doc_id: r for r in red}


def test_masking_uses_typed_placeholders(profile):
    _, _, _, red = profile
    assert "[EMAIL_ADDRESS]" in red["hr"].text and "[PHONE_NUMBER]" in red["hr"].text


def test_suppression_hides_the_category(profile):
    _, _, _, red = profile
    t = red["hr"].text
    assert "SSN [REDACTED]" in t and "[GOVERNMENT_ID]" not in t and "906-43-6765" not in t


def test_generalisation_in_context(profile):
    _, _, _, red = profile
    t = red["hr"].text
    assert "30-39 years old" in t and "the 1980s" in t and "Maharashtra" in t
    assert "is a professional" in t and "a a " not in t          # article fitted


def test_pseudonym_consistent_across_documents(profile):
    _, _, _, red = profile
    assert red["hr"].text.startswith("PERSON_01") and "PERSON_01" in red["news"].text


def test_non_entity_text_is_byte_identical(profile):
    docs, _, _, red = profile
    for d in docs:
        r = red[d.doc_id]
        for seg in r.segments:
            if not seg.replaced:
                assert r.text[seg.out_start:seg.out_end] == d.text[seg.orig_start:seg.orig_end]
        # segments tile both texts completely
        assert sum(s.out_end - s.out_start for s in r.segments) == len(r.text)
        assert sum(s.orig_end - s.orig_start for s in r.segments) == len(d.text)


def test_kept_entities_are_untouched(profile):
    docs, _, _, red = profile
    assert "Report date: 3 February 2025." in red["news"].text


def test_deterministic(agents, profile):
    docs, intel, decisions, red = profile
    again = {r.doc_id: r for r in agents[2].run(docs, intel.entities, decisions, "B3")}
    assert all(again[k].text == red[k].text for k in red)


def test_output_spans_point_at_replacements(profile):
    _, _, _, red = profile
    for r in red.values():
        for a in r.redactions:
            assert r.text[a.output_span.start:a.output_span.end] == a.replacement


def test_overlapping_entities_merge_with_stronger_strategy(engine, agents, entity_factory):
    from privacy_review.redaction import apply_redactions
    from privacy_review.schemas import RedactionDecision, RiskLevel, Span
    text = "Ref: AB12345678 end."
    a = entity_factory("RECORD_IDENTIFIER", 0, value="AB12345678", start=5)
    b = entity_factory("GOVERNMENT_ID", 0, value="12345678", start=7)
    decs = {a.entity_id: RedactionDecision(entity_id=a.entity_id, entity_type=a.entity_type, strategy=Strategy.MASK,
                                           risk=RiskLevel.HIGH, policy_id="t"),
            b.entity_id: RedactionDecision(entity_id=b.entity_id, entity_type=b.entity_type, strategy=Strategy.SUPPRESS,
                                           risk=RiskLevel.CRITICAL, policy_id="t")}
    r = apply_redactions("d", text, [a, b], decs, engine, agents[2].registry, "b", 0)
    assert r.text == "Ref: [REDACTED] end."


@pytest.mark.parametrize("fn,args,expected", [
    (age_band, ("34", 10), "30-39"), (age_band, ("34 years old", 20), "20-39 years old"),
    (decade, ("12/03/1989",), "the 1980s"), (month_year, ("12 March 2024",), "March 2024"),
    (month_year, ("2024-07-04",), "July 2024"), (prefix, ("560034", 3), "560xxx"),
    (round_coords, ("[-71.6702,-107.6572]", 1), "-71.7, -107.7"),
])
def test_generalisation_functions(fn, args, expected):
    assert fn(*args) == expected


def test_generalise_refuses_identity_output(engine):
    tr, ref = engine.transformation.generalization, engine.reference
    assert generalize("2024", E.DATE, 1, tr, ref) is None               # already a year: no safe coarser form
    assert generalize("Atlantis", E.LOCATION, 1, tr, ref) is None       # unknown city: caller masks
    assert generalize("Pune", E.LOCATION, 1, tr, ref) == "Maharashtra"
    assert generalize("Pune", E.LOCATION, 2, tr, ref) == "India"
    assert generalize("senior staff nurse", E.OCCUPATION, 1, tr, ref) == "a healthcare professional"


def test_failed_generalisation_falls_back_to_mask(engine, agents, entity_factory):
    from privacy_review.redaction import apply_redactions
    from privacy_review.schemas import RedactionDecision, RiskLevel
    e = entity_factory("LOCATION", 0, value="Atlantis", start=8)
    d = RedactionDecision(entity_id=e.entity_id, entity_type=E.LOCATION, strategy=Strategy.GENERALIZE,
                          risk=RiskLevel.MEDIUM, policy_id="t")
    r = apply_redactions("d", "Born in Atlantis.", [e], {e.entity_id: d}, engine, agents[2].registry, "b", 0)
    assert r.text == "Born in [LOCATION]." and r.redactions[0].strategy == Strategy.MASK


class TestPseudonymRegistry:
    def test_batch_scope_links_document_scope_does_not(self):
        reg = PseudonymRegistry(b"k" * 32, {"PERSON": "PERSON"})
        b1 = reg.pseudonym(E.PERSON, "C1", PseudonymScope.BATCH, "B", "d1")
        b2 = reg.pseudonym(E.PERSON, "C1", PseudonymScope.BATCH, "B", "d2")
        d1 = reg.pseudonym(E.PERSON, "C1", PseudonymScope.DOCUMENT, "B", "d1")
        d2 = reg.pseudonym(E.PERSON, "C2", PseudonymScope.DOCUMENT, "B", "d2")
        assert b1 == b2
        assert d1 == "PERSON_01" and d2 == "PERSON_01"            # per-document numbering: unlinkable

    def test_different_entities_get_different_pseudonyms(self):
        reg = PseudonymRegistry(b"k" * 32, {"PERSON": "PERSON"})
        assert reg.pseudonym(E.PERSON, "C1", PseudonymScope.BATCH, "B", "d") != \
               reg.pseudonym(E.PERSON, "C2", PseudonymScope.BATCH, "B", "d")

    def test_store_holds_no_plaintext_and_is_private(self, tmp_path):
        path = tmp_path / "map.sqlite"
        reg = PseudonymRegistry(b"k" * 32, {"PERSON": "PERSON"}, store_path=path)
        reg.pseudonym(E.PERSON, "ananya rao", PseudonymScope.BATCH, "B", "d")
        raw = path.read_bytes()
        assert b"ananya" not in raw.lower()
        if os.name == "posix":
            assert oct(path.stat().st_mode & 0o777) == "0o600"
        rows = sqlite3.connect(path).execute("SELECT * FROM pseudonyms").fetchall()
        assert len(rows) == 1 and len(rows[0][0]) == 64             # HMAC-SHA256 hex digest

    def test_store_survives_restart(self, tmp_path):
        path = tmp_path / "map.sqlite"
        a = PseudonymRegistry(b"k" * 32, {"PERSON": "PERSON"}, store_path=path).pseudonym(E.PERSON, "C1", PseudonymScope.BATCH, "B", "d")
        b = PseudonymRegistry(b"k" * 32, {"PERSON": "PERSON"}, store_path=path).pseudonym(E.PERSON, "C1", PseudonymScope.BATCH, "B", "d")
        assert a == b

    def test_repr_hides_contents(self):
        reg = PseudonymRegistry(b"k" * 32)
        reg.pseudonym(E.PERSON, "ananya", PseudonymScope.BATCH, "B", "d")
        assert "ananya" not in repr(reg)


def test_persistent_registry_is_thread_safe(tmp_path):
    """The API serves requests from a thread pool; the SQLite-backed registry must survive that."""
    import threading
    reg = PseudonymRegistry(b"k" * 32, {"PERSON": "PERSON"}, store_path=tmp_path / "p.sqlite")
    errors, out = [], []

    def go(i):
        try:
            out.append((i % 5, reg.pseudonym(E.PERSON, f"C{i % 5}", PseudonymScope.BATCH, "B", "d")))
        except Exception as e:          # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    by_person = {}
    for person, p in out:
        by_person.setdefault(person, set()).add(p)
    assert all(len(ps) == 1 for ps in by_person.values())          # consistent under concurrency
    assert len({next(iter(ps)) for ps in by_person.values()}) == 5  # and never shared

"""Synthetic cross-document dataset: format, offsets, ground truth and fictional-data rules.

Anything the file claims about re-identification (k, reidentifiable, which attributes are
revealed) is recomputed here from the registry and the mentions, not trusted.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest
from pydantic import SecretStr

from privacy_review.datasets.synthetic_schema import SyntheticDataset
from privacy_review.schemas import DetectedEntity, EntityType, Span, Strategy
from scripts.make_synthetic_dataset import OUT, render

FIELD = {"OCCUPATION": "occupation", "ORGANIZATION": "organization", "DEPARTMENT": "department",
         "LOCATION": "city", "AGE": "age_band", "DEMOGRAPHIC": "gender", "EVENT": "events"}


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(Path(OUT).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ds(raw) -> SyntheticDataset:
    return SyntheticDataset.model_validate(raw)


@pytest.fixture(scope="module")
def texts(ds) -> dict[str, str]:
    return {d.doc_id: d.text for d in ds.documents}


@pytest.fixture(scope="module")
def strategy_at(ds) -> dict[tuple, Strategy]:
    return {(e.doc_id, e.start, e.end): e.expected_strategy for e in ds.expected_strategies}


def k_of(ds: SyntheticDataset, attrs: dict[str, str]) -> int:
    count = 0
    for p in ds.registry:
        ok = True
        for key, value in attrs.items():
            have = getattr(p, FIELD[key])
            ok &= (value in have) if key == "EVENT" else (have == value)
        count += ok
    return count


def revealed(ds, person_id, doc_ids, strategy_at=None) -> dict[str, str]:
    out: dict[str, set[str]] = defaultdict(set)
    for m in ds.mentions:
        if m.person_id != person_id or m.doc_id not in doc_ids or not m.attribute or m.contradicts_registry:
            continue
        if strategy_at is not None:
            s = strategy_at[(m.doc_id, m.start, m.end)]
            if not (s is Strategy.KEEP or (m.attribute == "AGE" and s is Strategy.GENERALIZE)):
                continue
        out[m.attribute].add(m.attribute_value)
    assert all(len(v) == 1 for v in out.values()), f"{person_id}: an attribute has two values"
    return {k: next(iter(v)) for k, v in out.items()}


# ====================================================================== format & offsets

def test_file_validates(raw):
    SyntheticDataset.model_validate(raw)


def test_file_round_trips_exactly(raw, ds):
    assert ds.model_dump(mode="json") == raw


def test_regenerating_with_the_same_seed_is_identical():
    assert Path(OUT).read_text(encoding="utf-8") == render(), (
        "fixture is stale - run: python scripts/make_synthetic_dataset.py"
    )
    assert render() == render()


def test_size(ds):
    assert 24 <= len(ds.documents) <= 30
    assert 35 <= len(ds.registry) <= 45
    assert 8 <= sum(p.is_target for p in ds.registry) <= 10
    assert len({d.doc_type for d in ds.documents}) == 8


def test_every_span_is_a_trimmed_non_empty_substring(ds, texts):
    for item in [*ds.mentions, *ds.expected_strategies]:
        piece = texts[item.doc_id][item.start:item.end]
        assert piece and piece == piece.strip(), (item.doc_id, item.start, item.end)


def test_spans_do_not_overlap(ds):
    by_doc = defaultdict(list)
    for m in ds.mentions:
        by_doc[m.doc_id].append((m.start, m.end))
    for spans in by_doc.values():
        spans.sort()
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_one_expected_strategy_per_mention(ds):
    mentions = {(m.doc_id, m.start, m.end, m.entity_type) for m in ds.mentions}
    expected = {(e.doc_id, e.start, e.end, e.entity_type) for e in ds.expected_strategies}
    assert mentions == expected and len(ds.expected_strategies) == len(ds.mentions)


def test_sentence_indexes_follow_text_order(ds):
    by_doc = defaultdict(list)
    for m in ds.mentions:
        by_doc[m.doc_id].append((m.start, m.sentence_index))
    for items in by_doc.values():
        idx = [s for _, s in sorted(items)]
        assert idx == sorted(idx)


# ====================================================================== people & registry

def test_every_target_appears_in_three_or_four_documents(ds):
    docs_of = defaultdict(set)
    for m in ds.mentions:
        if m.person_id:
            docs_of[m.person_id].add(m.doc_id)
    for p in ds.registry:
        if p.is_target:
            assert 3 <= len(docs_of[p.person_id]) <= 4, (p.person_id, sorted(docs_of[p.person_id]))


def test_attribute_mentions_agree_with_registry(ds):
    for m in ds.mentions:
        if m.attribute is None or m.contradicts_registry:
            continue
        have = getattr(ds.person(m.person_id), FIELD[m.attribute])
        assert (m.attribute_value in have) if m.attribute == "EVENT" else (have == m.attribute_value), m


def test_person_mentions_use_the_registry_name_or_a_variant(ds, texts):
    for m in ds.mentions:
        if m.entity_type == "PERSON":
            surface = texts[m.doc_id][m.start:m.end]
            assert surface.split()[-1] == ds.person(m.person_id).name.split()[-1], surface


# ====================================================================== planted risks

def test_anonymity_set_size_is_recomputed_from_registry(ds):
    for r in ds.planted_risks:
        assert k_of(ds, r.combined_attributes) == r.anonymity_set_size, r.risk_id
        assert r.reidentifiable == (r.anonymity_set_size == 1)


def test_combined_attributes_are_exactly_what_the_documents_reveal(ds):
    for r in ds.planted_risks:
        assert revealed(ds, r.person_id, r.doc_ids) == r.combined_attributes, r.risk_id
        assert sorted(r.combined_attribute_types) == sorted(r.combined_attributes)


def test_first_pass_anonymity_set_is_recomputed(ds, strategy_at):
    for r in ds.planted_risks:
        visible = revealed(ds, r.person_id, r.doc_ids, strategy_at)
        assert k_of(ds, visible) == r.anonymity_set_size_after_first_pass, r.risk_id
        assert r.survives_first_pass == (r.anonymity_set_size_after_first_pass == 1)


def test_mix_of_risky_and_control_cases(ds):
    risky = [r for r in ds.planted_risks if r.reidentifiable]
    control = [r for r in ds.planted_risks if r.anonymity_set_size >= 3]
    assert len(risky) >= 3 and len(control) >= 3
    assert sum(r.survives_first_pass for r in risky) >= 3, "Agent 5 needs risks the first pass leaves"
    assert len(risky) + len(control) == len(ds.planted_risks), "no ambiguous k = 2 cases"
    assert {r.person_id for r in ds.planted_risks} == {p.person_id for p in ds.registry if p.is_target}


def test_controls_stay_safe_across_all_their_documents(ds):
    docs_of = defaultdict(set)
    for m in ds.mentions:
        if m.person_id:
            docs_of[m.person_id].add(m.doc_id)
    for r in ds.planted_risks:
        if not r.reidentifiable:
            assert set(r.doc_ids) == docs_of[r.person_id], r.risk_id
            assert k_of(ds, revealed(ds, r.person_id, docs_of[r.person_id])) >= 3


def test_risky_documents_are_individually_below_the_ctx01_threshold(ds):
    """'Each document looks harmless on its own': fewer than 3 quasi-identifier types."""
    qi = {"OCCUPATION", "ORGANIZATION", "LOCATION", "AGE", "DATE", "EVENT", "DEMOGRAPHIC",
          "POSTAL_CODE", "DATE_OF_BIRTH"}
    for r in ds.planted_risks:
        if r.reidentifiable and r.survives_first_pass:
            assert len(r.doc_ids) >= 2, r.risk_id
            for doc_id in r.doc_ids:
                types = {m.entity_type for m in ds.mentions if m.doc_id == doc_id} & qi
                assert len(types) < 3, (r.risk_id, doc_id, types)


# ====================================================================== expected strategies

def test_expected_strategies_match_the_policy_engine(ds, engine):
    """Independent derivation in the generator vs the knowledge base's PolicyEngine."""
    by_doc = defaultdict(list)
    for i, m in enumerate(ds.mentions):
        by_doc[m.doc_id].append(DetectedEntity(
            entity_id=f"m{i}", doc_id=m.doc_id, entity_type=EntityType(m.entity_type),
            span=Span(start=m.start, end=m.end), value=SecretStr("x"), confidence=1.0,
            identifier_class=engine.identifier_class(EntityType(m.entity_type)),
            sentence_index=m.sentence_index,
        ))
    expected = {(e.doc_id, e.start, e.end): e for e in ds.expected_strategies}
    mismatches = []
    for entities in by_doc.values():
        escalations = engine.context_escalations(entities)
        for ent in entities:
            _, risk, fired = engine.assess(ent, entities, escalations)
            strategy = engine.strategy_for(ent.entity_type, risk)
            exp = expected[(ent.doc_id, ent.span.start, ent.span.end)]
            if (strategy, risk, sorted(fired)) != (exp.expected_strategy, exp.risk, sorted(exp.fired_rules)):
                mismatches.append((ent.doc_id, ent.entity_type.value, strategy.value, exp.expected_strategy.value))
    assert mismatches == []


def test_expected_strategies_are_policy_compliant(ds, engine):
    for e in ds.expected_strategies:
        assert engine.is_compliant(EntityType(e.entity_type), e.expected_strategy), e
        assert e.why


# ====================================================================== fictional-data rules

EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
PHONE_LIKE = re.compile(r"\+\d[\d\s().-]{6,}\d")
FICTIONAL_PHONE = re.compile(r"^\+1-202-555-01\d\d$")
SSN_LIKE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")


def test_emails_use_reserved_domains(ds):
    for d in ds.documents:
        for domain in EMAIL.findall(d.text):
            assert domain in {"example.com", "example.org", "example.net"}, domain


def test_phones_are_in_the_fictional_range(ds, texts):
    for d in ds.documents:
        for phone in PHONE_LIKE.findall(d.text):
            assert FICTIONAL_PHONE.match(phone), phone
    for m in ds.mentions:
        if m.entity_type == "PHONE_NUMBER":
            assert FICTIONAL_PHONE.match(texts[m.doc_id][m.start:m.end])


def test_ssn_like_numbers_use_invalid_areas(ds, texts):
    for d in ds.documents:
        for area, _, _ in SSN_LIKE.findall(d.text):
            assert int(area) >= 900, area
    gov = [texts[m.doc_id][m.start:m.end] for m in ds.mentions if m.entity_type == "GOVERNMENT_ID"]
    assert gov and all(SSN_LIKE.fullmatch(g) and int(g[:3]) >= 900 for g in gov)


def test_record_identifiers_use_the_agreed_formats(ds, texts):
    for m in ds.mentions:
        if m.entity_type == "RECORD_IDENTIFIER":
            assert re.fullmatch(r"EMP-\d{5}|MRN-\d{7}", texts[m.doc_id][m.start:m.end])


def test_only_the_planted_surname_is_shared(ds):
    surnames = defaultdict(list)
    for p in ds.registry:
        surnames[p.name.split()[-1]].append(p.person_id)
    shared = {s: ids for s, ids in surnames.items() if len(ids) > 1 and any(i.startswith("T") for i in ids)}
    assert set(shared) == {"Rao"}


# ====================================================================== edge cases

def _m(ds, doc_id, entity_type=None, person_id=...):
    return [m for m in ds.mentions if m.doc_id == doc_id
            and (entity_type is None or m.entity_type == entity_type)
            and (person_id is ... or m.person_id == person_id)]


def _surface(texts, m):
    return texts[m.doc_id][m.start:m.end]


def check_name_variants_same_person(ds, texts, docs):
    names = [m for d in docs for m in _m(ds, d, "PERSON")]
    target = {m.person_id for m in names if _surface(texts, m).startswith(("A.", "Dr."))}
    assert len(target) == 1
    pid = target.pop()
    variants = {_surface(texts, m) for m in names if m.person_id == pid}
    assert len(variants) >= 3
    assert all(any(m.person_id == pid for m in _m(ds, d, "PERSON")) for d in docs)


def check_shared_surname_different_people(ds, texts, docs):
    people = _m(ds, docs[0], "PERSON")
    by_surname = defaultdict(set)
    for m in people:
        by_surname[_surface(texts, m).split()[-1]].add(m.person_id)
    assert any(len(ids) >= 2 for ids in by_surname.values())


def check_same_email_two_documents(ds, texts, docs):
    found = [{(_surface(texts, m), m.person_id) for m in _m(ds, d, "EMAIL_ADDRESS")} for d in docs]
    assert set.intersection(*found)


def check_no_name_still_identifying(ds, texts, docs):
    assert not _m(ds, docs[0], "PERSON")
    about = {m.person_id for m in _m(ds, docs[0]) if m.person_id}
    assert len(about) == 1
    risk = next(r for r in ds.planted_risks if r.doc_ids == docs)
    assert risk.person_id in about and risk.reidentifiable


def check_dob_postcode_gender(ds, texts, docs):
    types = {(m.entity_type, m.value_kind) for m in _m(ds, docs[0])}
    assert {("DATE_OF_BIRTH", "date_of_birth"), ("POSTAL_CODE", "postcode"), ("DEMOGRAPHIC", "gender")} <= types


def check_medical_condition_with_name(ds, texts, docs):
    med = _m(ds, docs[0], "MEDICAL_CONDITION")
    names = _m(ds, docs[0], "PERSON")
    assert med and names and {m.person_id for m in med} <= {m.person_id for m in names}


def check_demographic_about_named_person(ds, texts, docs):
    demo = [m for m in _m(ds, docs[0], "DEMOGRAPHIC") if m.value_kind in {"nationality", "religion"}]
    names = _m(ds, docs[0], "PERSON")
    assert demo and any(d.sentence_index == n.sentence_index and d.person_id == n.person_id
                        for d in demo for n in names)


def check_isolated_dateline(ds, texts, docs):
    for d in docs:
        dates = [m for m in _m(ds, d, "DATE", None)]
        assert any(
            not any(o is not m and o.sentence_index == m.sentence_index for o in _m(ds, d)) for m in dates
        ), d


def check_conflicting_city(ds, texts, docs):
    cities = [m for d in docs for m in _m(ds, d, "LOCATION") if m.person_id]
    pids = {m.person_id for m in cities}
    assert len(pids) == 1
    assert len({_surface(texts, m) for m in cities}) == 2
    assert sum(m.contradicts_registry for m in cities) == 1


def check_organisation_only_document(ds, texts, docs):
    assert _m(ds, docs[0]) and all(m.person_id is None for m in _m(ds, docs[0]))


CHECKS = {name[len("check_"):]: fn for name, fn in globals().items() if name.startswith("check_")}


def test_every_edge_case_has_a_checker(ds):
    assert {e.case for e in ds.edge_cases} == set(CHECKS)


@pytest.mark.parametrize("case", sorted(CHECKS))
def test_edge_case_documents_contain_what_they_describe(ds, texts, case):
    edge = next(e for e in ds.edge_cases if e.case == case)
    CHECKS[case](ds, texts, edge.doc_ids)

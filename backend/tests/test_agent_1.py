"""Agent 1 - Privacy Intelligence.

Covers detection accuracy, annotation validation, structured extraction, span accuracy,
contextual entities, cross-document clustering and the entity graph. The last class runs
against the ai4privacy dev split when it has been prepared.
"""

from __future__ import annotations

import json

import pytest

from privacy_review.agents.privacy_intelligence import (
    IntelligenceResult, LLMDetection, PrivacyIntelligenceAgent, expand_to_words, map_annotation_label, splits_a_word,
)
from privacy_review.config import Settings
from privacy_review.schemas import Annotation, AnnotationStatus, Document, EntityType as E, IdentifierClass, Span

from tests.conftest import processed

PROFILE = ("Ananya Rao (ananya.rao@example.com, +1-202-555-0143) joined Orion Biolabs in Pune as Principal Data "
           "Scientist. She was born on 12/03/1989 and lives at 42 Park Street, Apt 7. Her SSN is 906-43-6765 and "
           "employee ID EMP-58213. She spoke at the Global AI Summit 2024.")


def found(result: IntelligenceResult, text: str) -> dict[str, E]:
    return {text[e.span.start:e.span.end]: e.entity_type for e in result.entities}


# ===================================================================== detection

class TestDetection:
    @pytest.fixture(scope="class")
    def profile(self, agent1):
        return found(agent1.run([Document(doc_id="p", text=PROFILE)]), PROFILE)

    @pytest.mark.parametrize("value,etype", [
        ("Ananya Rao", E.PERSON), ("ananya.rao@example.com", E.EMAIL_ADDRESS), ("+1-202-555-0143", E.PHONE_NUMBER),
        ("Orion Biolabs", E.ORGANIZATION), ("Pune", E.LOCATION), ("Principal Data Scientist", E.OCCUPATION),
        ("12/03/1989", E.DATE_OF_BIRTH), ("42 Park Street, Apt 7", E.STREET_ADDRESS),
        ("906-43-6765", E.GOVERNMENT_ID), ("EMP-58213", E.RECORD_IDENTIFIER), ("Global AI Summit 2024", E.EVENT),
    ])
    def test_profile_entities(self, profile, value, etype):
        assert profile.get(value) == etype, f"{value!r} -> {profile.get(value)}"

    @pytest.mark.parametrize("text,value,etype", [
        ("Device IMEI: 06-184755-866851-3 was flagged.", "06-184755-866851-3", E.DEVICE_IDENTIFIER),
        ("Last seen at [-71.6702,-107.6572] yesterday.", "[-71.6702,-107.6572]", E.GPS_COORDINATE),
        ("Your new password: ap4R_oBHAg0w. Keep it safe.", "ap4R_oBHAg0w", E.CREDENTIAL),
        ("Send to 0x52908400098527886E0F7030069857D2E4169EE7 today.", "0x52908400098527886E0F7030069857D2E4169EE7", E.FINANCIAL_ACCOUNT),
        ("Card security code CVV 847 must not be stored.", "847", E.FINANCIAL_ACCOUNT),
        ("Patient MRN: 00456123 was discharged.", "00456123", E.RECORD_IDENTIFIER),
        ("The client with SSN 75697241181 called.", "75697241181", E.GOVERNMENT_ID),
        ("Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 logged in.", None, E.ONLINE_IDENTIFIER),
        ("Dear Danyka, your invoice is attached.", "Danyka", E.PERSON),
        ("Contact us at (064)-3788903 any time.", "(064)-3788903", E.PHONE_NUMBER),
        ("He is 34 years old and lives nearby.", "34 years old", E.AGE),
        ("Patient, aged 61, was admitted.", "61", E.AGE),
    ])
    def test_formats(self, agent1, text, value, etype):
        ents = found(agent1.run([Document(doc_id="f", text=text)]), text)
        if value is None:
            assert etype in ents.values(), ents
        else:
            assert ents.get(value) == etype, ents

    def test_non_identifying_terms_are_not_flagged(self, agent1):
        text = "Pay with Mastercard in BGN, head Northwest, and call back at 9:13 PM via VPN."
        ents = found(agent1.run([Document(doc_id="n", text=text)]), text)
        assert not {k for k, v in ents.items() if v in (E.ORGANIZATION, E.LOCATION, E.DATE, E.PERSON)}, ents

    def test_relative_dates_are_not_flagged(self, agent1):
        text = "We met last year and will meet again next week."
        assert not agent1.run([Document(doc_id="r", text=text)]).entities

    def test_empty_and_whitespace_documents(self, agent1):
        r = agent1.run([Document(doc_id="e1", text=""), Document(doc_id="e2", text="   \n ")])
        assert r.entities == []


# ===================================================================== structured extraction

class TestStructuredExtraction:
    @pytest.fixture(scope="class")
    def result(self, agent1):
        return agent1.run([Document(doc_id="p", text=PROFILE)])

    def test_values_are_hidden_from_repr_and_json(self, result):
        for e in result.entities:
            assert e.raw() not in repr(e)
            assert e.raw() not in e.model_dump_json()

    def test_public_projection_has_no_value(self, result):
        for e in result.entities:
            assert "value" not in e.public().model_dump()

    def test_spans_are_exact_trimmed_substrings(self, result):
        for e in result.entities:
            sub = PROFILE[e.span.start:e.span.end]
            assert sub == e.raw()
            assert sub == sub.strip() and not sub.endswith((",", ";", ":"))

    def test_identifier_class_comes_from_policy(self, result, engine):
        for e in result.entities:
            assert e.identifier_class == engine.identifier_class(e.entity_type)
        classes = {e.entity_type: e.identifier_class for e in result.entities}
        assert classes[E.EMAIL_ADDRESS] == IdentifierClass.DIRECT
        assert classes[E.OCCUPATION] == IdentifierClass.INDIRECT

    def test_sentence_indices(self, result):
        sent = {PROFILE[e.span.start:e.span.end]: e.sentence_index for e in result.entities}
        assert sent["Ananya Rao"] == sent["Orion Biolabs"] == 0
        assert sent["12/03/1989"] == 1
        assert sent["Global AI Summit 2024"] == 3

    def test_confidence_bounds_and_sources(self, result):
        for e in result.entities:
            assert 0.0 <= e.confidence <= 1.0
            assert e.sources

    def test_entity_ids_unique(self, result):
        ids = [e.entity_id for e in result.entities]
        assert len(ids) == len(set(ids))


# ===================================================================== annotation validation

class TestAnnotationValidation:
    TEXT = "Ananya Rao is a Principal Data Scientist at Orion Biolabs in Pune. Contact: ananya.rao@example.com."

    def run(self, agent1, anns):
        r = agent1.run([Document(doc_id="a", text=self.TEXT, annotations=anns)])
        return r, {x.annotation_index: x for x in r.annotation_reports if x.annotation_index is not None}

    def test_correct_annotation_confirmed(self, agent1):
        _, rep = self.run(agent1, [Annotation(start=0, end=10, label="PERSON")])
        assert rep[0].status == AnnotationStatus.CONFIRMED

    def test_dataset_and_presidio_labels_are_understood(self, agent1):
        _, rep = self.run(agent1, [Annotation(start=0, end=10, label="FIRSTNAME"),
                                   Annotation(start=16, end=40, label="JOBTITLE")])
        assert rep[0].status == rep[1].status == AnnotationStatus.CONFIRMED

    def test_boundary_inside_a_word_is_flagged_and_repaired(self, agent1):
        r, rep = self.run(agent1, [Annotation(start=2, end=10, label="PERSON")])       # "anya Rao"
        assert rep[0].status == AnnotationStatus.SPAN_MISMATCH
        ent = next(e for e in r.entities if e.entity_id == rep[0].entity_id)
        assert ent.span.contains(Span(start=0, end=10))

    def test_wrong_type_flagged_and_more_sensitive_kept(self, agent1):
        r, rep = self.run(agent1, [Annotation(start=44, end=57, label="PERSON")])      # "Orion Biolabs"
        assert rep[0].status == AnnotationStatus.TYPE_MISMATCH
        ent = next(e for e in r.entities if e.entity_id == rep[0].entity_id)
        assert ent.entity_type == E.PERSON                    # PERSON is more sensitive than ORGANIZATION

    def test_unsupported_annotation_kept_not_dropped(self, agent1):
        r, rep = self.run(agent1, [Annotation(start=11, end=13, label="PERSON")])      # "is"
        assert rep[0].status == AnnotationStatus.UNCONFIRMED
        assert any(e.entity_id == rep[0].entity_id for e in r.entities)

    @pytest.mark.parametrize("start,end", [(500, 510), (5, 5), (-1, 3), (10, 11)])
    def test_invalid_spans_rejected(self, agent1, start, end):
        r, rep = self.run(agent1, [Annotation(start=start, end=end, label="EMAIL")])
        assert rep[0].status == AnnotationStatus.INVALID
        assert rep[0].entity_id is None
        assert any("invalid" in w for w in r.warnings)

    def test_missing_annotations_are_added(self, agent1):
        r, _ = self.run(agent1, [Annotation(start=0, end=10, label="PERSON")])
        added = {self.TEXT[e.span.start:e.span.end] for e in r.entities if e.annotation_status == AnnotationStatus.NOT_ANNOTATED}
        assert {"ananya.rao@example.com", "Orion Biolabs", "Pune"} <= added

    def test_unknown_label_fails_closed(self, agent1):
        assert map_annotation_label("SHOE_SIZE") == E.UNKNOWN
        r, rep = self.run(agent1, [Annotation(start=11, end=13, label="SHOE_SIZE")])
        ent = next(e for e in r.entities if e.entity_id == rep[0].entity_id)
        assert ent.entity_type == E.UNKNOWN

    def test_final_entities_never_overlap(self, agent1):
        r, _ = self.run(agent1, [Annotation(start=0, end=20, label="PERSON"), Annotation(start=5, end=40, label="JOBTITLE")])
        spans = sorted((e.span.start, e.span.end) for e in r.entities)
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))

    def test_word_boundary_helpers(self):
        t = "Ananya Rao"
        assert splits_a_word(t, Span(start=2, end=10)) and not splits_a_word(t, Span(start=0, end=10))
        assert expand_to_words(t, Span(start=2, end=5)) == Span(start=0, end=6)


# ===================================================================== cross-document

class TestCrossDocument:
    DOCS = [
        Document(doc_id="hr", text="Ananya Rao (ananya.rao@example.com) is a Principal Data Scientist at Orion Biolabs."),
        Document(doc_id="news", text="Dr. Ananya Rao won the Orion Innovation Award. Reach her at ananya.rao@example.com."),
        Document(doc_id="other", text="Rahul Mehta from Pune attended the review."),
    ]

    @pytest.fixture(scope="class")
    def result(self, agent1):
        return agent1.run(self.DOCS)

    def test_same_person_clustered_across_documents(self, result):
        clusters = {c.cluster_id: c for c in result.clusters}
        persons = [c for c in clusters.values() if c.entity_type == E.PERSON and len(c.doc_ids) > 1]
        assert len(persons) == 1 and persons[0].doc_ids == ["hr", "news"]

    def test_same_email_clustered(self, result):
        emails = [c for c in result.clusters if c.entity_type == E.EMAIL_ADDRESS]
        assert len(emails) == 1 and emails[0].doc_ids == ["hr", "news"]

    def test_different_people_not_merged(self, result):
        persons = [c for c in result.clusters if c.entity_type == E.PERSON]
        assert len(persons) == 2

    def test_cluster_ids_do_not_encode_values(self, result):
        for c in result.clusters:
            assert c.cluster_id.startswith("C") and c.cluster_id[1:].isdigit()

    def test_every_entity_has_a_cluster(self, result):
        assert all(e.cluster_id for e in result.entities)

    def test_graph_links_person_to_employer(self, result):
        person = next(c.cluster_id for c in result.clusters if c.entity_type == E.PERSON and len(c.doc_ids) > 1)
        org_ids = {c.cluster_id for c in result.clusters if c.entity_type == E.ORGANIZATION}
        linked = {l.target_cluster if l.source_cluster == person else l.source_cluster
                  for l in result.links if person in (l.source_cluster, l.target_cluster)}
        assert linked & org_ids
        assert all(l.doc_ids for l in result.links)


# ===================================================================== optional LLM pass

class TestLLMDetection:
    TEXT = "The only assistant warden of the girls' hostel reported the incident."

    def test_off_by_default_even_with_a_key(self, engine, extractor, fake_reasoner):
        fake = fake_reasoner({"agent1_detection": LLMDetection(items=[])})
        agent = PrivacyIntelligenceAgent(engine, extractor=extractor, reasoner=fake)
        r = agent.run([Document(doc_id="x", text=self.TEXT)])
        assert r.llm_used is False and fake.prompts == []      # raw text never sent

    def test_enabled_merges_llm_findings(self, engine, extractor, fake_reasoner):
        fake = fake_reasoner({"agent1_detection": LLMDetection(items=[
            LLMDetection.Item(text="assistant warden", entity_type=E.OCCUPATION, reason="rare role"),
            LLMDetection.Item(text="not in the document", entity_type=E.PERSON, reason="hallucinated")])})
        agent = PrivacyIntelligenceAgent(engine, extractor=extractor, reasoner=fake,
                                         settings=Settings(llm_raw_text_detection=True))
        r = agent.run([Document(doc_id="x", text=self.TEXT)])
        assert r.llm_used
        got = found(r, self.TEXT)
        assert got.get("assistant warden") == E.OCCUPATION
        assert "not in the document" not in got                 # hallucinations cannot create spans

    def test_llm_failure_falls_back_silently(self, engine, extractor, fake_reasoner):
        fake = fake_reasoner({})                                 # returns None, as on timeout/refusal
        agent = PrivacyIntelligenceAgent(engine, extractor=extractor, reasoner=fake,
                                         settings=Settings(llm_raw_text_detection=True))
        r = agent.run([Document(doc_id="x", text=PROFILE)])
        assert r.llm_used is False and r.entities


# ===================================================================== dataset-based

class TestOnDataset:
    """Regression floors set below the measured dev numbers (coverage 0.930, strict F1 0.716),
    so a detection change that loses ground fails loudly."""

    @pytest.fixture(scope="class")
    def dev_metrics(self, agent1):
        from privacy_review.datasets.ground_truth import as_document
        from privacy_review.evaluation.detection_metrics import evaluate_detection
        ex = [e for e in processed("ai4privacy") if e.split == "dev"]
        preds = {e.example_id: agent1.run([as_document(e, "raw")]).entities for e in ex}
        return evaluate_detection(ex, preds)

    def test_raw_mode_hides_ground_truth(self):
        from privacy_review.datasets.ground_truth import as_document
        ex = processed("ai4privacy")[0]
        assert as_document(ex, "raw").annotations is None

    def test_privacy_coverage_floor(self, dev_metrics):
        assert dev_metrics["privacy_coverage"]["recall"] >= 0.90

    def test_strict_f1_floor(self, dev_metrics):
        assert dev_metrics["micro"]["strict"]["f1"] >= 0.68

    def test_direct_identifiers_nearly_always_covered(self, dev_metrics):
        by = dev_metrics["privacy_coverage"]["by_type"]
        for t in ("EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "URL", "GPS_COORDINATE"):
            assert by[t]["recall"] >= 0.9, (t, by[t])

    def test_report_contains_no_text(self, dev_metrics):
        blob = json.dumps(dev_metrics)
        ex = [e for e in processed("ai4privacy") if e.split == "dev"]
        values = {e.text[g.start:g.end] for e in ex for g in e.gold if g.end - g.start >= 6}
        assert not [v for v in values if v in blob]

"""The complete five-agent pipeline through LangGraph."""

from __future__ import annotations

import pytest

from privacy_review.orchestration.runner import run_pipeline, to_batch_result
from privacy_review.schemas import Annotation, BatchResult, Document, ReleaseStatus


def run(pipeline, docs, **kw):
    s = run_pipeline(docs, batch_id="it", pipeline=pipeline, **kw)
    return s, to_batch_result(s)


TEXT = "Rahul Mehta (rahul.mehta@example.org) from Nagpur called +1-202-555-0177 about invoice 4471."


def test_single_raw_document(pipeline):
    s, r = run(pipeline, [Document(doc_id="d", text=TEXT)])
    d = r.documents[0]
    assert d.released and "rahul.mehta@example.org" not in d.redacted_text and "Rahul Mehta" not in d.redacted_text
    assert d.verification.passed


def test_single_annotated_document(pipeline):
    anns = [Annotation(start=0, end=11, label="PERSON"), Annotation(start=13, end=36, label="EMAIL")]
    s, r = run(pipeline, [Document(doc_id="d", text=TEXT, annotations=anns)])
    assert s.intelligence.annotation_reports and r.documents[0].released
    assert "+1-202-555-0177" not in r.documents[0].redacted_text            # unannotated phone found anyway


def test_multiple_raw_documents_share_pseudonyms(pipeline):
    docs = [Document(doc_id="a", text="Rahul Mehta approved the budget."),
            Document(doc_id="b", text="Rahul Mehta signed off on Friday.")]
    s, r = run(pipeline, docs)
    texts = [d.redacted_text or "" for d in r.documents]
    assert all("Rahul" not in t for t in texts)


def test_multiple_annotated_documents(pipeline):
    docs = [Document(doc_id="a", text="Contact: priya@example.net", annotations=[Annotation(start=9, end=26, label="EMAIL")]),
            Document(doc_id="b", text="Priya Nair joined.", annotations=[Annotation(start=0, end=10, label="FIRSTNAME")])]
    s, r = run(pipeline, docs)
    assert all(d.released for d in r.documents)
    assert "priya@example.net" not in r.documents[0].redacted_text


def test_repeated_entities_are_all_redacted(pipeline):
    t = "Asha Kulkarni called. Asha Kulkarni then emailed asha.k@example.com and later asha.k@example.com again."
    s, r = run(pipeline, [Document(doc_id="d", text=t)])
    out = r.documents[0].redacted_text
    assert "Asha" not in out and "asha.k@example.com" not in out


def test_indirect_identifiers_are_handled(pipeline):
    t = "The only assistant warden of the girls' hostel, who joined in March 2024, reported the incident."
    s, r = run(pipeline, [Document(doc_id="d", text=t)])
    d = r.documents[0]
    assert (not d.released) or "March 2024" not in (d.redacted_text or "")


def test_conflicting_contextual_information(pipeline):
    docs = [Document(doc_id="a", text="Neha Joshi works in Pune."), Document(doc_id="b", text="Neha Joshi works in Kochi.")]
    s, r = run(pipeline, docs)
    assert all(d.release.status in (ReleaseStatus.RELEASED, ReleaseStatus.BLOCKED) for d in r.documents)
    assert all("Neha" not in (d.redacted_text or "") for d in r.documents)


def test_result_is_a_valid_batch_result(pipeline):
    s, r = run(pipeline, [Document(doc_id="d", text=TEXT)])
    again = BatchResult.model_validate_json(r.model_dump_json())
    assert again.aggregate.document_count == 1
    assert sum(again.aggregate.entities_by_type.values()) == len(again.documents[0].entities)


def test_remediation_loop_repairs_and_releases(pipeline):
    docs = [Document(doc_id="C", text="The only woman speaker from Orion Biolabs at the Global AI Summit 2024 was aged 34.")]
    s, r = run(pipeline, docs)
    assert s.round >= 1                                     # something was fixed on the way
    assert [h.stage for h in s.history][:2] == ["verification", "adversarial"]
    d = r.documents[0]
    assert d.released or "re-identification" in d.release.reason


def test_run_batch_entry_point_matches_api_contract(pipeline):
    from privacy_review.orchestration.runner import run_batch
    r = run_batch([Document(doc_id="d", text="Hello world.")], batch_id="x", pipeline=pipeline)
    assert isinstance(r, BatchResult) and r.batch_id == "x" and r.documents[0].released

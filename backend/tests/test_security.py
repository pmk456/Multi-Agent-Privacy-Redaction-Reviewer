"""Security: nothing raw leaves the backend, failures block release, loops terminate."""

from __future__ import annotations

import copy
import json
import logging

import pytest

from privacy_review.orchestration.runner import run_pipeline, to_batch_result
from privacy_review.schemas import BatchResult, Document, ReleaseStatus, Severity
from privacy_review.schemas.verification import Finding, FindingType, VerificationReport

SECRETS = ["Ananya Rao", "ananya.rao@example.com", "+1-202-555-0143", "906-43-6765", "EMP-58213", "12/03/1989"]
DOC = Document(doc_id="s", text="Ananya Rao (ananya.rao@example.com, +1-202-555-0143), SSN 906-43-6765, "
                                "employee ID EMP-58213, born on 12/03/1989.")


@pytest.fixture(scope="module")
def ran(pipeline):
    return run_pipeline([DOC], batch_id="sec", pipeline=pipeline)


def test_released_output_has_no_raw_identifiers(ran):
    blob = to_batch_result(ran).model_dump_json()
    assert not [s for s in SECRETS if s in blob]


def test_blocked_output_has_no_text_at_all(pipeline):
    from tests.test_adversarial import _WrongRiskAgent  # noqa: F401  (reuse not needed; build a stuck pipeline)

    class Never(type(pipeline.a4)):
        def run(self, documents, redacted, entities, decisions):
            reps = super().run(documents, redacted, entities, decisions)
            for r in reps:
                r.findings.append(Finding(finding_type=FindingType.RESIDUAL_PII, severity=Severity.BLOCKING,
                                          doc_id=r.doc_id, description="forced"))
                r.passed = False
            return reps

    stuck = copy.copy(pipeline)
    stuck.a4 = Never(pipeline.policy, pipeline.settings, extractor=pipeline.a4.extractor)
    stuck.graph = stuck._build()
    s = run_pipeline([DOC], pipeline=stuck)
    r = to_batch_result(s)
    d = r.documents[0]
    assert d.release.status == ReleaseStatus.BLOCKED and d.redacted_text is None
    assert s.round <= s.max_rounds                          # retry limit held - no infinite loop
    assert not [x for x in SECRETS if x in r.model_dump_json()]


def test_retry_limit_is_configurable(pipeline):
    s = run_pipeline([DOC], pipeline=pipeline, max_rounds=0)
    assert s.round == 0


def test_raw_identifiers_not_in_logs(pipeline, caplog):
    with caplog.at_level(logging.DEBUG):
        run_pipeline([DOC], batch_id="logs", pipeline=pipeline)
    assert not [s for s in SECRETS if s in caplog.text]


def test_state_repr_and_entity_dumps_hide_values(ran):
    assert not [s for s in SECRETS if s in repr(ran)]
    for e in ran.entities:
        assert e.raw() not in e.model_dump_json()
        assert e.raw() not in str(e)


def test_aggregate_and_history_are_counts_only(ran):
    blob = to_batch_result(ran).aggregate.model_dump_json() + json.dumps([h.model_dump() for h in ran.history])
    assert not [s for s in SECRETS if s in blob]


def test_failed_verification_prevents_release(ran):
    r = to_batch_result(ran)
    for d in r.documents:
        if not d.verification or not d.verification.passed:
            assert not d.released and d.redacted_text is None


def test_outputs_validate_against_schemas(ran):
    r = to_batch_result(ran)
    assert BatchResult.model_validate(json.loads(r.model_dump_json())) == r
    for v in ran.verification:
        VerificationReport.model_validate(v.model_dump())


def test_public_entities_have_no_value_field(ran):
    for d in to_batch_result(ran).documents:
        for e in d.entities:
            assert "value" not in e.model_dump()


def test_pseudonym_mapping_never_in_output(ran):
    blob = to_batch_result(ran).model_dump_json()
    assert "digest" not in blob and "hmac" not in blob.lower()

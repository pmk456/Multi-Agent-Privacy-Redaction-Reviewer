"""API tests. The central property: no raw identifier leaves the backend - not in a
response, a log line, the audit table or the results table. All data is fictional."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from privacy_review.api import STUB_REASON, create_app, stub_run_batch
from privacy_review.config import Settings
from privacy_review.schemas import (
    AggregateStatistics,
    BatchResult,
    EntityType,
    IdentifierClass,
    PublicEntity,
    ReleaseDecision,
    ReleaseStatus,
    SanitizedDocument,
    Span,
)

EMAIL = "alice@example.com"
PHONE = "+1-202-555-0143"
SECRETS = (EMAIL, PHONE)
TEXT = f"Please contact Alice Example at {EMAIL} or {PHONE} about the claim."
IDENTIFYING_FILENAME = "alice_example_discharge"


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(protected_store_dir=tmp_path / "protected_store", _env_file=None)


def masking_pipeline(documents, batch_id):
    """A fake 'live' pipeline that masks the two fictional identifiers."""
    out = []
    for d in documents:
        entities, redacted = [], d.text
        for n, (value, et) in enumerate(((EMAIL, EntityType.EMAIL_ADDRESS),
                                         (PHONE, EntityType.PHONE_NUMBER))):
            if value in d.text:
                start = d.text.index(value)
                entities.append(PublicEntity(
                    entity_id=f"{d.doc_id}-e{n}", doc_id=d.doc_id, entity_type=et,
                    span=Span(start=start, end=start + len(value)), confidence=0.99,
                    identifier_class=IdentifierClass.DIRECT,
                ))
                redacted = redacted.replace(value, f"[{et.value}]")
        out.append(SanitizedDocument(
            doc_id=d.doc_id, released=True, redacted_text=redacted, entities=entities,
            release=ReleaseDecision(doc_id=d.doc_id, status=ReleaseStatus.RELEASED,
                                    reason="All checks passed.", remediation_rounds=0),
        ))
    return BatchResult(
        batch_id=batch_id, documents=out,
        aggregate=AggregateStatistics(
            document_count=len(out), documents_released=len(out), documents_blocked=0,
            entities_by_type={"EMAIL_ADDRESS": len(out), "PHONE_NUMBER": len(out)},
        ),
    )


def echo_pipeline(documents, batch_id):
    """A broken pipeline: blocks every document but still attaches the original text."""
    result = stub_run_batch(documents, batch_id)
    for sd, d in zip(result.documents, documents):
        sd.redacted_text = d.text
    return result


def exploding_pipeline(documents, batch_id):
    raise RuntimeError(f"boom while processing {documents[0].text}")


@pytest.fixture
def client_for(settings):
    def make(run_batch=None) -> TestClient:
        return TestClient(create_app(run_batch, settings=settings))
    return make


@pytest.fixture
def stub_client(client_for, monkeypatch) -> TestClient:
    monkeypatch.setitem(sys.modules, "privacy_review.orchestration.runner", None)
    return client_for()


def _db_dump(settings: Settings) -> str:
    with sqlite3.connect(settings.protected_store_dir / "api.sqlite") as conn:
        rows = conn.execute("SELECT * FROM audit").fetchall()
        rows += conn.execute("SELECT * FROM results").fetchall()
    return repr(rows)


def _originals(settings: Settings) -> list[Path]:
    return [p for p in settings.protected_store_dir.glob("*/*") if p.is_file()]


def _text_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def _assert_clean(*blobs: str) -> None:
    for blob in blobs:
        for secret in SECRETS + (IDENTIFYING_FILENAME,):
            assert secret not in blob, f"leaked {secret!r}"


# ------------------------------------------------------------------ health

class TestHealth:
    def test_reports_stub_when_no_pipeline(self, stub_client):
        r = stub_client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "pipeline": "stub", "llm": False}

    def test_reports_live_with_injected_pipeline(self, client_for):
        assert client_for(masking_pipeline).get("/health").json()["pipeline"] == "live"

    def test_reports_live_when_runner_importable(self, client_for, monkeypatch):
        import types
        fake = types.ModuleType("privacy_review.orchestration.runner")
        fake.run_batch = masking_pipeline
        monkeypatch.setitem(sys.modules, "privacy_review.orchestration.runner", fake)
        assert client_for().get("/health").json()["pipeline"] == "live"


# ------------------------------------------------------------------ no leaks

class TestNoRawIdentifiers:
    @pytest.mark.parametrize("pipeline", [None, masking_pipeline, echo_pipeline])
    def test_review_leaks_nothing(self, client_for, settings, caplog, monkeypatch, pipeline):
        monkeypatch.setitem(sys.modules, "privacy_review.orchestration.runner", None)
        caplog.set_level(logging.DEBUG)
        client = client_for(pipeline)

        r = client.post("/review", json={"documents": [{"doc_id": "claim-1", "text": TEXT}]})
        assert r.status_code == 200, r.text
        batch_id = r.json()["batch_id"]
        again = client.get(f"/batches/{batch_id}")

        _assert_clean(r.text, again.text, _db_dump(settings), caplog.text)
        # sanity: the identifiers really did reach the backend, and only the protected store
        [original] = _originals(settings)
        assert EMAIL in original.read_text(encoding="utf-8")

    def test_stub_withholds_everything(self, stub_client):
        r = stub_client.post("/review", json={"documents": [{"text": TEXT}, {"text": "Second."}]})
        body = r.json()
        assert [d["released"] for d in body["documents"]] == [False, False]
        assert [d["redacted_text"] for d in body["documents"]] == [None, None]
        assert {d["release"]["status"] for d in body["documents"]} == {"blocked"}
        assert {d["release"]["reason"] for d in body["documents"]} == {STUB_REASON}
        assert body["aggregate"]["documents_blocked"] == 2

    def test_masking_pipeline_output_is_returned(self, client_for):
        body = client_for(masking_pipeline).post(
            "/review", json={"documents": [{"text": TEXT}]}).json()
        doc = body["documents"][0]
        assert doc["released"] is True
        assert "[EMAIL_ADDRESS]" in doc["redacted_text"] and "[PHONE_NUMBER]" in doc["redacted_text"]
        assert all("value" not in e for e in doc["entities"])

    def test_release_gate_drops_text_of_blocked_documents(self, client_for):
        body = client_for(echo_pipeline).post("/review", json={"documents": [{"text": TEXT}]}).json()
        assert body["documents"][0]["redacted_text"] is None

    def test_upload_leaks_nothing_including_filename(self, client_for, settings, caplog):
        caplog.set_level(logging.DEBUG)
        client = client_for(masking_pipeline)
        files = [
            ("files", (f"{IDENTIFYING_FILENAME}.txt", TEXT.encode(), "text/plain")),
            ("files", (f"{IDENTIFYING_FILENAME}.pdf", _text_pdf(TEXT), "application/pdf")),
        ]
        r = client.post("/upload", files=files)
        assert r.status_code == 200, r.text
        assert len(r.json()["documents"]) == 2
        _assert_clean(r.text, _db_dump(settings), caplog.text)
        assert all(IDENTIFYING_FILENAME not in p.name for p in _originals(settings))

    def test_validation_errors_do_not_echo_input(self, stub_client, caplog):
        caplog.set_level(logging.DEBUG)
        r = stub_client.post("/review", json={"documents": [{"text": 12345, "doc_id": EMAIL,
                                                             EMAIL: PHONE}]})
        assert r.status_code == 422
        assert r.json()["code"] == "invalid_request"
        _assert_clean(r.text, caplog.text)
        assert "12345" not in r.text

    def test_pipeline_crash_returns_generic_500(self, client_for, settings, caplog):
        caplog.set_level(logging.DEBUG)
        r = client_for(exploding_pipeline).post("/review", json={"documents": [{"text": TEXT}]})
        assert r.status_code == 500
        assert r.json()["code"] == "pipeline_error"
        _assert_clean(r.text, caplog.text, _db_dump(settings))
        assert "RuntimeError" in caplog.text            # the type is logged, the message isn't


# ------------------------------------------------------------------ storage

class TestStorage:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not enforced on Windows")
    def test_original_saved_with_mode_0600(self, stub_client, settings):
        r = stub_client.post("/upload", files=[("files", ("a.txt", TEXT.encode(), "text/plain"))])
        assert r.status_code == 200
        [original] = _originals(settings)
        assert original.stat().st_mode & 0o777 == 0o600
        assert original.parent.stat().st_mode & 0o777 == 0o700
        assert (settings.protected_store_dir / "api.sqlite").stat().st_mode & 0o777 == 0o600

    def test_original_stored_under_batch_and_doc_id(self, stub_client, settings):
        r = stub_client.post("/upload", files=[("files", ("x.pdf", _text_pdf(TEXT), "application/pdf"))])
        body = r.json()
        [original] = _originals(settings)
        assert original.parent.name == body["batch_id"]
        assert original.name == f"{body['documents'][0]['doc_id']}.pdf"
        assert original.read_bytes().startswith(b"%PDF")

    def test_audit_rows_hold_ids_and_counts_only(self, client_for, settings):
        r = client_for(masking_pipeline).post(
            "/review", json={"documents": [{"doc_id": "d1", "text": TEXT}]})
        batch_id = r.json()["batch_id"]
        store = client_for(masking_pipeline).app.state.store
        [row] = store.audit_rows(batch_id)
        assert row["doc_id"] == "d1" and row["status"] == "released"
        assert row["entity_count"] == 2 and row["finding_count"] == 0
        with sqlite3.connect(store.db_path) as conn:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(audit)")]
        assert cols == ["batch_id", "doc_id", "status", "entity_count", "finding_count", "created_at"]

    def test_fake_pipeline_round_trips_through_get(self, client_for):
        client = client_for(masking_pipeline)
        posted = client.post("/review", json={"documents": [{"text": TEXT}, {"text": "No PII."}]})
        fetched = client.get(f"/batches/{posted.json()['batch_id']}")
        assert fetched.status_code == 200
        assert fetched.json() == posted.json()
        BatchResult.model_validate(fetched.json())

    def test_unknown_batch_is_404_without_echo(self, stub_client):
        r = stub_client.get(f"/batches/{IDENTIFYING_FILENAME}")
        assert r.status_code == 404
        assert r.json()["code"] == "batch_not_found"
        assert IDENTIFYING_FILENAME not in r.text


# ------------------------------------------------------------------ ingestion errors

class TestIngestionErrors:
    def test_upload_errors_list_index_and_code_only(self, stub_client, settings):
        files = [
            ("files", ("good.txt", b"fine", "text/plain")),
            ("files", (f"{IDENTIFYING_FILENAME}.txt", b"", "text/plain")),
            ("files", (f"{IDENTIFYING_FILENAME}.docx", TEXT.encode(), "application/octet-stream")),
            ("files", (f"{IDENTIFYING_FILENAME}.json", f'{{"text": "{EMAIL}", "annotations": 3}}'.encode(),
                       "application/json")),
            ("files", ("scan.pdf", b"not a pdf", "application/pdf")),
        ]
        r = stub_client.post("/upload", files=files)
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "ingestion_failed"
        assert [(e["file_index"], e["code"]) for e in body["errors"]] == [
            (1, "empty_document"), (2, "unsupported_format"), (3, "malformed_json"), (4, "corrupt_file"),
        ]
        _assert_clean(r.text)
        assert "fine" not in r.text
        assert _originals(settings) == []          # nothing stored when the batch is rejected

    def test_upload_oversize_file(self, client_for, tmp_path):
        s = Settings(protected_store_dir=tmp_path / "ps", max_upload_bytes=100, _env_file=None)
        client = TestClient(create_app(stub_run_batch, settings=s))
        r = client.post("/upload", files=[("files", ("a.txt", b"x" * 101, "text/plain"))])
        assert r.status_code == 422
        assert r.json()["errors"] == [{"file_index": 0, "code": "file_too_large",
                                       "message": "The file exceeds the maximum upload size of 100 bytes."}]

    def test_too_many_files(self, tmp_path):
        s = Settings(protected_store_dir=tmp_path / "ps", max_files_per_batch=2, _env_file=None)
        client = TestClient(create_app(stub_run_batch, settings=s))
        files = [("files", (f"{i}.txt", b"x", "text/plain")) for i in range(3)]
        assert client.post("/upload", files=files).json()["code"] == "too_many_files"
        r = client.post("/review", json={"documents": [{"text": "x"}] * 3})
        assert r.json()["code"] == "too_many_documents"

    def test_review_errors_use_document_index(self, stub_client):
        r = stub_client.post("/review", json={"documents": [
            {"text": "ok", "doc_id": "a"}, {"text": "   "}, {"text": "x", "doc_id": "../../x"},
            {"text": "dup", "doc_id": "a"},
        ]})
        assert r.status_code == 422
        assert [(e["document_index"], e["code"]) for e in r.json()["errors"]] == [
            (1, "empty_document"), (2, "invalid_doc_id"), (3, "duplicate_doc_id"),
        ]
        assert all("file_index" not in e for e in r.json()["errors"])

    def test_review_keeps_out_of_bounds_annotations(self, client_for, settings):
        seen = {}

        def capture(documents, batch_id):
            seen["annotations"] = documents[0].annotations
            return stub_run_batch(documents, batch_id)

        r = client_for(capture).post("/review", json={"documents": [
            {"text": "short", "annotations": [{"start": 2, "end": 500, "label": "PERSON"}]}]})
        assert r.status_code == 200
        assert [(a.start, a.end) for a in seen["annotations"]] == [(2, 500)]

    def test_json_upload_with_several_documents(self, stub_client):
        payload = b'[{"doc_id": "a", "text": "one"}, {"doc_id": "b", "text": "two"}]'
        r = stub_client.post("/upload", files=[("files", ("batch.json", payload, "application/json"))])
        assert [d["doc_id"] for d in r.json()["documents"]] == ["a", "b"]

    def test_duplicate_doc_id_across_files(self, stub_client):
        a = ("files", ("a.json", b'{"doc_id": "same", "text": "one"}', "application/json"))
        b = ("files", ("b.json", b'{"doc_id": "same", "text": "two"}', "application/json"))
        r = stub_client.post("/upload", files=[a, b])
        assert [(e["file_index"], e["code"]) for e in r.json()["errors"]] == [(1, "duplicate_doc_id")]

    def test_body_without_length_or_too_large(self, tmp_path):
        s = Settings(protected_store_dir=tmp_path / "ps", max_upload_bytes=10,
                     max_files_per_batch=1, _env_file=None)
        client = TestClient(create_app(stub_run_batch, settings=s))
        big = b'{"documents": [{"text": "' + b"x" * 300_000 + b'"}]}'
        r = client.post("/review", content=big, headers={"content-type": "application/json"})
        assert r.status_code == 413 and r.json()["code"] == "request_too_large"

        def chunks():
            yield b'{"documents": [{"text": "x"}]}'
        r = client.post("/review", content=chunks(), headers={"content-type": "application/json"})
        assert r.status_code == 411


# ------------------------------------------------------------------ frontend

class TestFrontend:
    def test_root_redirects_to_ui(self, stub_client):
        r = stub_client.get("/", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"] == "/ui/"

    def test_ui_and_mock_are_served(self, stub_client):
        assert "<html" in stub_client.get("/ui/").text.lower()
        assert stub_client.get("/ui/app.js").status_code == 200
        assert stub_client.get("/ui/assets/alliance-university-logo.png").status_code == 200
        BatchResult.model_validate(stub_client.get("/ui/mock/batch_result.json").json())

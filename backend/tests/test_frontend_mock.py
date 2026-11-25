"""The demo-mode mock must stay valid against BatchResult and contain fictional data only."""

from __future__ import annotations

import json
import re

from privacy_review.schemas import BatchResult
from scripts.make_frontend_mock import OUT, render

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def _mock() -> dict:
    return json.loads(OUT.read_text(encoding="utf-8"))


def test_mock_validates_against_batch_result():
    BatchResult.model_validate(_mock())


def test_mock_round_trips_exactly():
    """Catches fields added to or removed from the schema, not just type errors."""
    data = _mock()
    assert BatchResult.model_validate(data).model_dump(mode="json") == data


def test_mock_is_up_to_date_with_generator():
    assert OUT.read_text(encoding="utf-8") == render(), (
        "frontend/mock/batch_result.json is stale - run: python scripts/make_frontend_mock.py"
    )


def test_mock_contains_only_fictional_identifiers():
    blob = OUT.read_text(encoding="utf-8")
    assert all(e.endswith("@example.com") for e in EMAIL.findall(blob))
    for phone in PHONE.findall(blob):
        digits = re.sub(r"\D", "", phone)
        assert "55501" in digits, phone


def test_blocked_documents_carry_no_text():
    for doc in _mock()["documents"]:
        if not doc["released"]:
            assert doc["redacted_text"] is None

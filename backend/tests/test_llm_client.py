"""The Claude client must never raise into the pipeline and must account for usage.
No live API key is available, so these use a fake Anthropic client."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from privacy_review.config import Settings
from privacy_review.llm import ClaudeReasoner, tokenize


class Out(BaseModel):
    answer: str


def _resp(stop="end_turn", parsed=Out(answer="ok")):
    return SimpleNamespace(stop_reason=stop, parsed_output=parsed,
                           usage=SimpleNamespace(input_tokens=120, output_tokens=30))


class FakeMessages:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


def reasoner(behaviour, **settings):
    msgs = FakeMessages(behaviour)
    return ClaudeReasoner(Settings(**settings), client=SimpleNamespace(messages=msgs)), msgs


def _http_error(cls, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


def call(r):
    return r.structured(purpose="t", system="s", prompt="p", output_format=Out)


def test_no_key_returns_none_without_network():
    r = ClaudeReasoner(Settings(anthropic_api_key=None))
    assert r.available is False
    assert call(r) is None
    assert r.ledger.calls[-1].error == "llm_unavailable"


def test_success_returns_validated_model_and_counts_tokens():
    r, msgs = reasoner(_resp())
    assert call(r) == Out(answer="ok")
    assert r.ledger.input_tokens == 120 and r.ledger.output_tokens == 30
    assert msgs.kwargs["model"] == "claude-haiku-5-5"            # minimal-usage default
    assert msgs.kwargs["thinking"] == {"type": "disabled"}
    assert msgs.kwargs["output_config"] == {"effort": "low"}
    assert msgs.kwargs["max_tokens"] == 1024
    assert msgs.kwargs["output_format"] is Out


def test_call_budget_is_enforced_per_batch():
    r, msgs = reasoner(_resp(), llm_max_calls_per_batch=2)
    assert [call(r) is not None for _ in range(3)] == [True, True, False]
    assert r.ledger.calls[-1].error == "budget_exhausted"
    r.reset_budget()
    assert call(r) is not None


def test_tests_never_enable_the_llm():
    from privacy_review.config import Settings as S
    assert S().llm_available is False


@pytest.mark.parametrize("behaviour,code", [
    (_resp(stop="refusal", parsed=None), "refusal"),
    (_resp(stop="max_tokens", parsed=None), "truncated"),
    (_resp(parsed=None), "unparseable"),
    (_http_error(anthropic.RateLimitError, 429), "rate_limited"),
    (_http_error(anthropic.AuthenticationError, 401), "authentication_failed"),
    (_http_error(anthropic.BadRequestError, 400), "bad_request"),
    (_http_error(anthropic.InternalServerError, 500), "api_status_500"),
    (anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com")), "timeout"),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), "connection_error"),
])
def test_failures_never_raise(behaviour, code):
    r, _ = reasoner(behaviour)
    assert call(r) is None
    assert r.ledger.calls[-1].error == code
    assert r.ledger.summary()["failed"] == 1


def test_failure_log_does_not_contain_prompt(caplog):
    r, _ = reasoner(_http_error(anthropic.RateLimitError, 429))
    with caplog.at_level(logging.WARNING):
        r.structured(purpose="t", system="s", prompt="SECRET-PROMPT-TEXT", output_format=Out)
    assert "SECRET-PROMPT-TEXT" not in caplog.text


def test_tokenize_replaces_every_value(entity_factory):
    text = "Ananya Rao works at Orion Biolabs."
    a = entity_factory("PERSON", 0, value="Ananya Rao", start=0)
    b = entity_factory("ORGANIZATION", 0, value="Orion Biolabs", start=20)
    out, keys = tokenize(text, [a, b])
    assert out == "[PERSON_1] works at [ORGANIZATION_1]."
    assert "Ananya" not in out and "Orion" not in out
    assert set(keys) == {"[PERSON_1]", "[ORGANIZATION_1]"}

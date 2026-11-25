"""Claude client for structured reasoning.

Design rules:
  * Never raises into the pipeline. Every failure - no key, timeout, rate limit, refusal,
    malformed output - returns None plus a CallRecord, and the calling agent falls back to
    its deterministic path.
  * Structured output only. Responses are parsed into a Pydantic model; anything that does
    not validate is discarded, never passed downstream.
  * Token usage is accumulated so reports can state what LLM reasoning cost.
  * What gets sent is the caller's responsibility, and every caller in this package sends
    tokenized or already-redacted text (see llm/context.py). Raw text is sent only by
    Agent 1's optional detection pass, which is off unless LLM_RAW_TEXT_DETECTION=true.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from privacy_review.config import Settings, get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class CallRecord:
    purpose: str
    ok: bool
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


@dataclass
class UsageLedger:
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    def summary(self) -> dict:
        return {"calls": len(self.calls), "succeeded": sum(c.ok for c in self.calls),
                "failed": sum(not c.ok for c in self.calls),
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "errors": sorted({c.error for c in self.calls if c.error})}


class Reasoner(Protocol):
    """What agents depend on. Tests substitute a fake that satisfies this."""

    @property
    def available(self) -> bool: ...

    ledger: UsageLedger

    def structured(self, *, purpose: str, system: str, prompt: str, output_format: type[T],
                   max_tokens: int | None = None) -> Optional[T]: ...


class ClaudeReasoner:
    def __init__(self, settings: Settings | None = None, client=None):
        self.settings = settings or get_settings()
        self.ledger = UsageLedger()
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None or self.settings.llm_available

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key.get_secret_value(),
                timeout=self.settings.llm_timeout_seconds,
                max_retries=self.settings.llm_max_retries,      # SDK backs off on 429 / 5xx
            )
        return self._client

    def structured(self, *, purpose: str, system: str, prompt: str, output_format: type[T],
                   max_tokens: int | None = None) -> Optional[T]:
        if not self.available:
            self.ledger.calls.append(CallRecord(purpose, False, "llm_unavailable"))
            return None
        import anthropic

        t0 = time.monotonic()
        rec = CallRecord(purpose, False)
        try:
            resp = self._get_client().messages.parse(
                model=self.settings.claude_model,
                max_tokens=max_tokens or self.settings.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=output_format,
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.claude_effort},
            )
            usage = getattr(resp, "usage", None)
            rec.input_tokens = getattr(usage, "input_tokens", 0) or 0
            rec.output_tokens = getattr(usage, "output_tokens", 0) or 0
            if resp.stop_reason == "refusal":
                rec.error = "refusal"
            elif resp.stop_reason == "max_tokens":
                rec.error = "truncated"
            elif resp.parsed_output is None:
                rec.error = "unparseable"
            else:
                rec.ok = True
                return resp.parsed_output
        except ValidationError:
            rec.error = "schema_validation_failed"
        except anthropic.RateLimitError:
            rec.error = "rate_limited"
        except anthropic.APITimeoutError:
            rec.error = "timeout"
        except anthropic.AuthenticationError:
            rec.error = "authentication_failed"
        except anthropic.BadRequestError:
            rec.error = "bad_request"
        except anthropic.APIStatusError as e:
            rec.error = f"api_status_{e.status_code}"
        except anthropic.APIConnectionError:
            rec.error = "connection_error"
        finally:
            rec.seconds = round(time.monotonic() - t0, 3)
            self.ledger.calls.append(rec)
            if not rec.ok:
                # The error code only - never the prompt, which may hold tokenized document text.
                log.warning("llm call '%s' failed: %s; continuing deterministically", purpose, rec.error)
        return None

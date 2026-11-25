"""Claude API client.

Used by Agent 02 (risk and policy) and Agent 05 (adversarial probing). Not used for the
redaction transformations themselves - those are deterministic Python in engines/.

Privacy rule for this module specifically: send the minimum context needed for the
decision in front of you. A span plus a window of surrounding text, not the whole
document, and never the full set of identifiers in a batch.

Owner: Patan Musthakheem
"""

from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # Resolves ANTHROPIC_API_KEY from the environment when api_key is empty.
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    return _client


def extract(
    *,
    system: str,
    prompt: str,
    output_format: type[T],
    max_tokens: int = 4096,
) -> T:
    """Ask Claude for one structured answer, validated against `output_format`.

    Structured output is how agent decisions stay machine-readable: the model returns a
    schema-valid object, Pydantic validates it, and a malformed field fails here instead
    of flowing downstream.
    """
    response = get_client().messages.parse(
        model=settings.claude_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=output_format,
        thinking={"type": "adaptive"},
        output_config={"effort": settings.claude_effort},
    )

    # Safety classifiers can decline a request: HTTP 200 with stop_reason "refusal".
    # Check before reading the result.
    if response.stop_reason == "refusal":
        raise RuntimeError(
            f"Claude declined this request: {getattr(response.stop_details, 'category', None)}"
        )

    return response.parsed_output


def build_minimal_context(text: str, start: int, end: int, window: int = 160) -> str:
    """A window around a span, so we never send a whole document to the model."""
    return text[max(0, start - window) : min(len(text), end + window)]

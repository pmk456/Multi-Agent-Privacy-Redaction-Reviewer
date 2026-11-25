"""The four transformations. Deterministic, pure, testable.

This is the part that must not be an LLM call. Same input, same output, every run -
otherwise Agent 04 cannot tell a redaction bug from model variance.

Owner: Nandha Jyothi E
"""

from __future__ import annotations

from app.schemas.entities import Entity
from app.schemas.policy import PolicyDecision
from app.schemas.redaction import RedactedDocument


def mask(value: str) -> str:
    """Rajesh -> [REDACTED]"""
    raise NotImplementedError


def generalize(value: str, category: str) -> str:
    """1998-04-12 -> 25-30 ; Koramangala, Bengaluru -> Bengaluru"""
    raise NotImplementedError


def pseudonymize(value: str, category: str, scope_key: str) -> str:
    """Rajesh -> PERSON_01, stable within `scope_key`.

    `scope_key` is the document id or the batch id depending on PolicyDecision.scope.
    Batch scope keeps a set of documents readable together; it also preserves exactly the
    linkage Agent 05 is meant to find. That trade-off is a policy setting, not a default
    to pick casually.
    """
    raise NotImplementedError


def suppress(value: str) -> str:
    """Remove the span entirely."""
    raise NotImplementedError


def apply(
    document_id: str, text: str, entities: list[Entity], decisions: list[PolicyDecision]
) -> RedactedDocument:
    """Apply every decision to `text`.

    Work right to left so that spans earlier in the document stay valid as you edit.
    """
    raise NotImplementedError("Redaction engine - planned for Review 2")

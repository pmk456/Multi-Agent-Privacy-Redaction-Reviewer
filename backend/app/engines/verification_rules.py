"""Deterministic checks that do not need a model.

Consistency and policy compliance are arithmetic over the redaction record - cheaper and
more reliable than asking an LLM. Agent 04 combines these with its own detection pass.

Owner: Nandha Jyothi E
"""

from __future__ import annotations

from app.schemas.redaction import RedactedDocument
from app.schemas.verification import Finding


def check_consistency(doc: RedactedDocument) -> list[Finding]:
    """Same entity, same replacement, everywhere it appears."""
    raise NotImplementedError("Consistency checks - planned for Review 3")


def check_policy_compliance(doc: RedactedDocument, decisions) -> list[Finding]:
    """The strategy applied matches the strategy that was decided."""
    raise NotImplementedError("Policy checks - planned for Review 3")


def check_spans(doc: RedactedDocument) -> list[Finding]:
    """No overlapping or off-by-one redaction spans."""
    raise NotImplementedError("Span checks - planned for Review 3")

"""Mask (typed placeholder) and suppress (untyped removal)."""

from __future__ import annotations

from privacy_review.schemas.entities import EntityType

MASK_FORMAT = "[{entity_type}]"
SUPPRESS_TOKEN = "[REDACTED]"


def mask(entity_type: EntityType, fmt: str = MASK_FORMAT) -> str:
    return fmt.format(entity_type=entity_type.value)


def suppress(token: str = SUPPRESS_TOKEN) -> str:
    """Suppression hides even the category - a reader learns only that something was here."""
    return token

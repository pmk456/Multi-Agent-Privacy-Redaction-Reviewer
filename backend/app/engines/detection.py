"""Detection: Presidio + spaCy + our own patterns.

Used twice, independently: once by Agent 01 on the original text, once by Agent 04 on the
redacted text. Keep it free of any state so the two calls cannot influence each other.

Indian formats the stock recognizers do not cover well are the first thing to add here -
Aadhaar, PAN, Indian mobile numbers, PIN codes. See the open questions in the report.

Owner: Nandha Jyothi E
"""

from __future__ import annotations

from app.schemas.entities import Entity, EntityLink


def detect(document_id: str, text: str) -> list[Entity]:
    """Return every entity found in `text`. No annotations involved."""
    raise NotImplementedError("Detection engine - planned for Review 2")


def validate_annotations(
    document_id: str, text: str, annotations: list[dict], detected: list[Entity]
) -> list[Entity]:
    """Reconcile supplied annotations against our own detection.

    Confirm, correct the span, or reject - and record which on each Entity.
    An annotation we cannot confirm is still worth keeping with a low confidence;
    dropping it silently is how a real identifier survives into the output.
    """
    raise NotImplementedError("Annotation validation - planned for Review 2")


def link_entities(entities: list[Entity]) -> list[EntityLink]:
    """Build the cross-document entity graph with NetworkX."""
    raise NotImplementedError("Entity linking - planned for Review 3")

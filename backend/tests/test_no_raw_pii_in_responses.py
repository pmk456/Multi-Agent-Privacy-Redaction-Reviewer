"""The guard rail.

Every response model the API can return must be incapable of carrying a raw identifier
value. This test fails if somebody adds a `value` field to something that goes out over
HTTP - which is exactly the mistake that is easy to make and hard to spot in review.
"""

import pytest

from app.schemas.api_models import (
    AggregateReport,
    DocumentResult,
    ReviewResponse,
)
from app.schemas.entities import PublicEntity

RESPONSE_MODELS = [ReviewResponse, DocumentResult, AggregateReport, PublicEntity]

# Field names that would mean an original identifier is being serialised.
FORBIDDEN = {"value", "original_text", "raw_value", "original_value", "source_text"}


@pytest.mark.parametrize("model", RESPONSE_MODELS)
def test_response_models_carry_no_raw_identifier_field(model):
    offending = FORBIDDEN & set(model.model_fields)
    assert not offending, (
        f"{model.__name__} exposes {sorted(offending)} through the API boundary. "
        "Return entity_id and category instead - see CONTRIBUTING.md."
    )


def test_document_result_entities_are_public():
    annotation = DocumentResult.model_fields["entities"].annotation
    assert "PublicEntity" in str(annotation), (
        "DocumentResult.entities must be PublicEntity, not Entity."
    )

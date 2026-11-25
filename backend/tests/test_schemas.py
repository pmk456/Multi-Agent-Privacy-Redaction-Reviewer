"""The schema contracts are shared, so they get tests from day one."""

from app.schemas.entities import Entity, EntityCategory, PublicEntity, Span


def _entity() -> Entity:
    return Entity(
        entity_id="e1",
        document_id="d1",
        category=EntityCategory.PERSON,
        span=Span(start=10, end=16),
        value="Rajesh",
        context="reported by Rajesh on Tuesday",
        confidence=0.92,
    )


def test_public_entity_drops_the_value():
    public = _entity().public()
    assert isinstance(public, PublicEntity)
    assert "value" not in public.model_dump()
    assert "Rajesh" not in str(public.model_dump())


def test_span_overlap():
    assert Span(start=0, end=5).overlaps(Span(start=4, end=9))
    assert not Span(start=0, end=5).overlaps(Span(start=5, end=9))

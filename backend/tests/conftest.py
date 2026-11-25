"""Shared fixtures. Heavy models (spaCy, Presidio) load once per session."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from privacy_review.config import get_settings
from privacy_review.knowledge_base import KnowledgeBase, PolicyEngine
from privacy_review.schemas import DetectedEntity, EntityType, IdentifierClass, Span

FIXTURES = Path(__file__).parent / "fixtures"
_ids = itertools.count()


@pytest.fixture(scope="session")
def kb_json() -> dict:
    return json.loads(get_settings().knowledge_base_json.read_text())


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    return KnowledgeBase.from_json(get_settings().knowledge_base_json)


@pytest.fixture(scope="session")
def engine(kb) -> PolicyEngine:
    return PolicyEngine(kb)


@pytest.fixture(scope="session")
def kb_expected() -> dict:
    return json.loads((FIXTURES / "kb_expected_decisions.json").read_text())


def make_entity(entity_type, sentence=0, *, value="x", doc_id="d1", start=None,
                identifier_class=None, confidence=0.9, engine=None) -> DetectedEntity:
    n = next(_ids)
    start = n * 10 if start is None else start
    et = EntityType(entity_type)
    if identifier_class is None:
        identifier_class = engine.identifier_class(et) if engine else IdentifierClass.INDIRECT
    return DetectedEntity(
        entity_id=f"e{n}", doc_id=doc_id, entity_type=et,
        span=Span(start=start, end=start + max(1, len(value))), value=SecretStr(value),
        confidence=confidence, identifier_class=identifier_class, sentence_index=sentence,
    )


@pytest.fixture
def entity_factory(engine):
    return lambda et, sentence=0, **kw: make_entity(et, sentence, engine=engine, **kw)


# ---------------------------------------------------------------- heavy shared fixtures

@pytest.fixture(scope="session")
def extractor(engine):
    import warnings
    warnings.filterwarnings("ignore")
    from privacy_review.detection import EntityExtractor
    return EntityExtractor(engine)


@pytest.fixture(scope="session")
def agent1(engine, extractor):
    from privacy_review.agents.privacy_intelligence import PrivacyIntelligenceAgent
    return PrivacyIntelligenceAgent(engine, extractor=extractor)


class FakeReasoner:
    """Stands in for ClaudeReasoner. Returns whatever `responses` maps a purpose to."""

    def __init__(self, responses=None, available=True):
        from privacy_review.llm import UsageLedger
        self.responses = responses or {}
        self._available = available
        self.ledger = UsageLedger()
        self.prompts: list[str] = []

    @property
    def available(self):
        return self._available

    def structured(self, *, purpose, system, prompt, output_format, max_tokens=None):
        from privacy_review.llm import CallRecord
        self.prompts.append(prompt)
        r = self.responses.get(purpose)
        self.ledger.calls.append(CallRecord(purpose, r is not None, None if r is not None else "fake_none"))
        return r


@pytest.fixture
def fake_reasoner():
    return FakeReasoner


def processed(name: str):
    from privacy_review.datasets import prepare_dataset
    path = get_settings().data_dir / "processed" / f"{name}.jsonl"
    if not path.exists():
        pytest.skip(f"{path.name} not prepared - run scripts/prepare_data.py")
    return prepare_dataset.load(path)

"""Shared fixtures. Heavy models (spaCy, Presidio) load once per session."""

from __future__ import annotations

import os

# Tests must never spend API calls, whatever .env holds. Environment beats .env in
# pydantic-settings, and this runs before any Settings object is created.
os.environ["LLM_ENABLED"] = "false"

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


# ---------------------------------------------------------------- pipeline-level fixtures

@pytest.fixture(scope="session")
def pipeline(engine):
    """Deterministic pipeline: the LLM is explicitly unavailable, as on this machine."""
    from privacy_review.config import Settings
    from privacy_review.orchestration.graph import Pipeline
    return Pipeline(engine, Settings(), reasoner=FakeReasoner(available=False))


@pytest.fixture(scope="session")
def agents(pipeline):
    """(a1, a2, a3, a4, a5) sharing the pipeline's loaded models."""
    return pipeline.a1, pipeline.a2, pipeline.a3, pipeline.a4, pipeline.a5


def run_through(agents, docs, batch_id="t", decisions_hook=None):
    """Run agents 1-3 and return everything a test needs to poke at agents 4 and 5."""
    a1, a2, a3, _, _ = agents
    intel = a1.run(docs)
    risk = a2.run(intel.entities, {d.doc_id: d.text for d in docs})
    decisions = decisions_hook(risk.decisions, intel.entities) if decisions_hook else risk.decisions
    red = a3.run(docs, intel.entities, decisions, batch_id)
    return intel, risk, decisions, red


PROFILE_DOCS_TEXT = {
    "hr": "Ananya Rao (ananya.rao@example.com, +1-202-555-0143) is a Principal Data Scientist at Orion Biolabs "
          "in Pune. She is 34 years old, born on 12/03/1989. SSN 906-43-6765.",
    "news": "Report date: 3 February 2025. Dr. Ananya Rao won the Orion Innovation Award in Bengaluru.",
}

"""run_batch(): the single entry point the API calls. Returns only sanitized output."""

from __future__ import annotations

import uuid
from collections import Counter
from functools import lru_cache

from privacy_review.config import get_settings
from privacy_review.knowledge_base import default_engine
from privacy_review.orchestration.graph import Pipeline
from privacy_review.orchestration.state import PipelineState
from privacy_review.schemas.documents import Document
from privacy_review.schemas.outputs import AggregateStatistics, BatchResult, SanitizedDocument
from privacy_review.schemas.verification import ReleaseStatus


@lru_cache(maxsize=1)
def default_pipeline() -> Pipeline:
    return Pipeline(default_engine(), get_settings())


def run_pipeline(documents: list[Document], batch_id: str | None = None, pipeline: Pipeline | None = None,
                 max_rounds: int | None = None) -> PipelineState:
    p = pipeline or default_pipeline()
    if hasattr(p.reasoner, "reset_budget"):
        p.reasoner.reset_budget()
    state = PipelineState(batch_id=batch_id or uuid.uuid4().hex[:12], documents=documents,
                          max_rounds=p.settings.max_remediation_rounds if max_rounds is None else max_rounds)
    return p.invoke(state)


def to_batch_result(s: PipelineState) -> BatchResult:
    rel = {r.doc_id: r for r in s.release}
    ver = {r.doc_id: r for r in s.verification}
    risks = s.risk.assessments if s.risk else []
    decs = s.risk.decisions if s.risk else []
    red = {r.doc_id: r for r in s.redacted}
    docs = []
    for d in s.documents:
        released = rel[d.doc_id].status == ReleaseStatus.RELEASED
        ent_ids = {e.entity_id for e in s.entities if e.doc_id == d.doc_id}
        docs.append(SanitizedDocument(
            doc_id=d.doc_id, released=released,
            redacted_text=red[d.doc_id].text if released else None,        # the release gate
            entities=[e.public() for e in s.entities if e.doc_id == d.doc_id],
            risks=[r for r in risks if r.entity_id in ent_ids],
            decisions=[x for x in decs if x.entity_id in ent_ids],
            verification=ver.get(d.doc_id), release=rel[d.doc_id]))
    findings = [f for r in s.verification for f in r.findings] + (s.adversarial.findings if s.adversarial else [])
    agg = AggregateStatistics(
        document_count=len(docs), documents_released=sum(x.released for x in docs),
        documents_blocked=sum(not x.released for x in docs),
        entities_by_type=dict(Counter(e.entity_type.value for e in s.entities)),
        risks_by_level=dict(Counter(r.risk.value for r in risks)),
        strategies=dict(Counter(x.strategy.value for x in decs)),
        findings_by_type=dict(Counter(f.finding_type.value for f in findings)),
        remediation_rounds=s.round, llm_used=s.llm_used)
    return BatchResult(batch_id=s.batch_id, documents=docs, adversarial=s.adversarial, aggregate=agg)


def run_batch(documents: list[Document], batch_id: str | None = None, pipeline: Pipeline | None = None) -> BatchResult:
    return to_batch_result(run_pipeline(documents, batch_id, pipeline))

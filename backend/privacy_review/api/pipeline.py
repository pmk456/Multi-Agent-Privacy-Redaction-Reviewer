"""Pipeline wiring: the live `run_batch` when it exists, a safe stub when it doesn't.

The stub withholds every document. It must NEVER return the input text: a mock that
echoes its input leaks exactly what the real pipeline exists to protect.
"""

from __future__ import annotations

import inspect
import logging
from typing import Callable, Literal

from privacy_review.schemas import (
    AggregateStatistics,
    BatchResult,
    Document,
    ReleaseDecision,
    ReleaseStatus,
    SanitizedDocument,
)

log = logging.getLogger("privacy_review.api")

RunBatch = Callable[[list[Document], str], BatchResult]
PipelineMode = Literal["stub", "live"]

STUB_REASON = "Redaction pipeline not available yet; document withheld."


def stub_run_batch(documents: list[Document], batch_id: str) -> BatchResult:
    """Withhold everything. Reads only doc_ids - never the text."""
    sanitized = [
        SanitizedDocument(
            doc_id=d.doc_id,
            released=False,
            redacted_text=None,
            release=ReleaseDecision(
                doc_id=d.doc_id,
                status=ReleaseStatus.BLOCKED,
                reason=STUB_REASON,
                remediation_rounds=0,
            ),
        )
        for d in documents
    ]
    return BatchResult(
        batch_id=batch_id,
        documents=sanitized,
        adversarial=None,
        aggregate=AggregateStatistics(
            document_count=len(sanitized),
            documents_released=0,
            documents_blocked=len(sanitized),
        ),
    )


def load_pipeline() -> tuple[RunBatch, PipelineMode]:
    """Import the live pipeline if it has landed, otherwise fall back to the stub."""
    try:
        from privacy_review.orchestration.runner import run_batch
    except ImportError as exc:
        log.info("Live pipeline unavailable (%s); using the withholding stub.", type(exc).__name__)
        return stub_run_batch, "stub"
    return adapt(run_batch), "live"


def adapt(fn: Callable) -> RunBatch:
    """Accept both `run_batch(documents, batch_id)` and the older `run_batch(documents)`."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn
    takes_batch_id = "batch_id" in params or len(params) >= 2 or any(
        p.kind is inspect.Parameter.VAR_POSITIONAL for p in params.values()
    )
    if takes_batch_id:
        return fn

    def call(documents: list[Document], batch_id: str) -> BatchResult:
        return fn(documents)

    return call


def enforce_release_gate(result: BatchResult | dict, batch_id: str) -> BatchResult:
    """Last check at the boundary, whatever the pipeline returned.

    * re-validates the result against `BatchResult` (drops anything not in the schema)
    * a document that is not released, or whose release decision says blocked, never
      carries text
    """
    result = BatchResult.model_validate(
        result.model_dump() if isinstance(result, BatchResult) else result
    )
    if result.batch_id != batch_id:
        log.warning("batch %s: pipeline returned a different batch_id; overriding.", batch_id)
        result.batch_id = batch_id
    for doc in result.documents:
        if not doc.released or doc.release.status is not ReleaseStatus.RELEASED:
            if doc.redacted_text is not None:
                log.warning(
                    "batch %s: doc %s is not released but carried text; text dropped.",
                    batch_id, doc.doc_id,
                )
            if doc.release.status is ReleaseStatus.RELEASED:
                doc.release.status = ReleaseStatus.BLOCKED
                doc.release.reason = INCONSISTENT_REASON
            doc.released = False
            doc.redacted_text = None
    return result


INCONSISTENT_REASON = "Withheld at the API boundary: the release decision was inconsistent."

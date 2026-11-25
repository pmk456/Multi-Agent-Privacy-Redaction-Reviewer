"""Aggregate statistics for the review report.

Deliberately not an agent. Counting entity categories and summarising verification
outcomes is arithmetic - there is no reason to involve a language model in it.

Counts only. An aggregate view over several documents is safe precisely because it
reports how many, never which.

Owner: Nandha Jyothi E with Pulagampalli Sai Mahima (charts)
"""

from __future__ import annotations

from app.schemas.api_models import AggregateReport
from app.orchestrator.state import ReviewState


def build_report(state: ReviewState) -> AggregateReport:
    """Roll the batch up into counts."""
    raise NotImplementedError("Aggregate reporting - planned for Review 3")


def to_plotly_figures(report: AggregateReport) -> dict:
    """Chart specs for the frontend - entity mix, risk mix, findings by type."""
    raise NotImplementedError("Charts - planned for Review 3")

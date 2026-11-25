"""LangGraph workflow.

    ingest
      -> privacy_intelligence
      -> risk_policy
      -> adaptive_redaction
      -> independent_verification
           |- blocking findings and remediations left -> back to adaptive_redaction
           |- blocking findings and budget spent      -> blocked
           '- clean                                   -> adversarial_privacy
      -> adversarial_privacy
           |- not safe -> back to adaptive_redaction (or blocked)
           '- safe     -> release_gate -> aggregate

The loop back is the reason this is a graph and not a list of function calls. The
remediation budget exists so a document that cannot be made safe is reported as blocked
instead of looping forever - see the open question in the Review 1 report.

Owner: Patan Musthakheem
"""

from __future__ import annotations

from app.orchestrator.state import ReviewState


def build_graph():
    """Build and compile the StateGraph.

    TODO(Review 2): nodes for the five agents, conditional edges for the two feedback
    loops, then `.compile()`.
    """
    raise NotImplementedError("LangGraph workflow - planned for Review 2")


def run_review(state: ReviewState) -> ReviewState:
    """Run one batch through the workflow."""
    raise NotImplementedError("LangGraph workflow - planned for Review 2")

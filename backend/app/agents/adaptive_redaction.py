"""Agent 03 - Adaptive Redaction.

Owns: carrying out the decision it was handed.

  in  : state.decisions
  out : state.redacted_documents

Four techniques - mask, generalize, pseudonymize, suppress - chosen by the policy, not by
this agent. The transformation itself is deterministic Python in engines.redaction, not an
LLM call: the same input must give the same output every run, or verification means
nothing.

Watch the offsets. Every edit shifts the spans after it.

Owner: Nandha Jyothi E
"""

from __future__ import annotations

from app.agents.base import Agent
from app.orchestrator.state import ReviewState


class AdaptiveRedactionAgent(Agent):
    name = "adaptive_redaction"

    def run(self, state: ReviewState) -> ReviewState:
        # TODO(Review 2): apply engines.redaction.apply() per document, right-to-left so
        # earlier spans stay valid, and record AppliedRedaction for each.
        raise NotImplementedError("Adaptive Redaction Agent - planned for Review 3")

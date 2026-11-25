"""Agent 04 - Independent Verification.

Owns: checking that the redaction was performed correctly.

  in  : state.redacted_documents  (NOT state.entities - that is the point)
  out : state.verification_reports

It runs its own detection pass over the redacted output. If it were handed the first
agent's entity list it would inherit the same blind spots and the check would be
circular.

Looks for: identifiers that were missed, spans applied to the wrong characters,
the same entity redacted inconsistently, and transformations that do not match the
policy that was supposed to apply.

A blocking finding sends the document back to Agent 03 rather than forward.

Owner: Nandha Jyothi E
"""

from __future__ import annotations

from app.agents.base import Agent
from app.orchestrator.state import ReviewState


class IndependentVerificationAgent(Agent):
    name = "independent_verification"

    def run(self, state: ReviewState) -> ReviewState:
        # TODO(Review 3): fresh engines.detection pass on the redacted text +
        # engines.verification_rules consistency and policy checks.
        raise NotImplementedError("Independent Verification Agent - planned for Review 3")

"""Agent 05 - Adversarial Privacy.

Owns: attacking the result.

  in  : state.redacted_documents, state.entity_links
  out : state.adversarial_reports

Verification asks whether the redaction was done correctly. This asks whether the output
is actually safe, which is a different and harder question - there is no list to check
against.

Looks for: residual identifiers, indirect identification (role + place + date can name a
person with no name in the sentence), and linkage across the batch where two documents are
each safe alone and not safe together.

This is the agent we understand least. Expect it to need the most iteration.

Owner: Patan Musthakheem with Nandha Jyothi E
"""

from __future__ import annotations

from app.agents.base import Agent
from app.orchestrator.state import ReviewState


class AdversarialPrivacyAgent(Agent):
    name = "adversarial_privacy"

    def run(self, state: ReviewState) -> ReviewState:
        # TODO(Review 3): LLM re-identification probe over the redacted text, plus a
        # NetworkX pass over entity_links for cross-document linkage.
        raise NotImplementedError("Adversarial Privacy Agent - planned for Review 3")

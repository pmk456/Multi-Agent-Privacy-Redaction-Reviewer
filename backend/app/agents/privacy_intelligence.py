"""Agent 01 - Privacy Intelligence.

Owns: knowing what is in the document.

  in  : raw text (+ any supplied annotations)
  out : state.entities, state.entity_links

Responsibilities
  - run detection over the text (Presidio + spaCy + our patterns)
  - validate supplied annotations instead of trusting them: confirm, correct the span,
    or reject, and record which on Entity.annotation_confirmed
  - build relationships between entities, including across documents in the batch

Owner: Nandha Jyothi E (detection), Patan Musthakheem (graph wiring)
"""

from __future__ import annotations

from app.agents.base import Agent
from app.orchestrator.state import ReviewState


class PrivacyIntelligenceAgent(Agent):
    name = "privacy_intelligence"

    def run(self, state: ReviewState) -> ReviewState:
        # TODO(Review 2): engines.detection.detect() over each document,
        # reconcile with state.annotations, then engines.detection.link_entities().
        raise NotImplementedError("Privacy Intelligence Agent - planned for Review 2")

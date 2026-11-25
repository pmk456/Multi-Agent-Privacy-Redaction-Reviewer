"""Agent 02 - Privacy Risk and Policy.

Owns: deciding how much each entity matters and what should happen to it.

  in  : state.entities, state.entity_links
  out : state.risks, state.decisions

The risk of an entity is not the risk of its category in the abstract - a surname in a
list of authors is not a surname in a medical complaint. Context is the input, which is
why this is where the LLM earns its place.

Produces decisions only. It does not transform anything.

Owner: Patan Musthakheem
"""

from __future__ import annotations

from app.agents.base import Agent
from app.orchestrator.state import ReviewState


class PrivacyRiskPolicyAgent(Agent):
    name = "risk_policy"

    def run(self, state: ReviewState) -> ReviewState:
        # TODO(Review 2): score each entity with llm.claude_client (structured output ->
        # RiskAssessment), then map risk -> strategy through knowledge_base/redaction_policies.yaml.
        raise NotImplementedError("Privacy Risk and Policy Agent - planned for Review 2")

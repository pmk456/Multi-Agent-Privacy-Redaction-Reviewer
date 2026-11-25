"""Common shape for the five agents.

Each agent takes the workflow state, does one job, and returns the state with its own
output added. No agent reaches into another agent's output to re-do its work - that is
what keeps verification independent rather than circular.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.orchestrator.state import ReviewState


class Agent(ABC):
    name: str = "agent"

    @abstractmethod
    def run(self, state: ReviewState) -> ReviewState:
        """Do this agent's job and return the updated state."""
        raise NotImplementedError

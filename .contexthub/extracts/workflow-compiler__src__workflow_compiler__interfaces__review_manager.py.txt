"""Abstract review manager interface for the approval gate."""

from __future__ import annotations

from abc import ABC, abstractmethod

from workflow_compiler.models import ReviewReport, WorkflowState


class ReviewManager(ABC):
    """Governs the human-in-the-loop review and approval of a workflow graph.

    Implementations decide how a generated graph is reviewed (automated agent,
    queued for a human, hybrid) and record approve/reject decisions.
    """

    @abstractmethod
    async def review(self, state: WorkflowState) -> ReviewReport:
        """Produce a review report for the state's current workflow graph."""
        raise NotImplementedError

    @abstractmethod
    async def approve(self, state: WorkflowState, *, reviewer: str | None = None) -> WorkflowState:
        """Mark the state's graph as approved and return the updated state."""
        raise NotImplementedError

    @abstractmethod
    async def reject(
        self,
        state: WorkflowState,
        *,
        reviewer: str | None = None,
        reason: str | None = None,
    ) -> WorkflowState:
        """Mark the state's graph as rejected and return the updated state."""
        raise NotImplementedError

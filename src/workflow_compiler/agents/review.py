"""WorkflowReviewAgent: structurally review the generated workflow graph.

Deterministic (no LLM). Wraps :class:`GraphReviewer` to produce a
:class:`ReviewReport` and attaches it to the :class:`WorkflowState`.
"""

from __future__ import annotations

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.graph.review import GraphReviewer
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.models import (
    CompilationStage,
    ConfidenceScores,
    WorkflowState,
)


class WorkflowReviewAgent(BaseAgent):
    """Review the state's workflow graph and attach a ReviewReport."""

    name = "workflow-review"

    def __init__(self, *, reviewer: GraphReviewer | None = None) -> None:
        """Graph review is deterministic, so no LLM provider is required."""
        super().__init__(None)
        self._reviewer = reviewer or GraphReviewer()

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Review ``state.workflow_graph`` and update the state in place."""
        if state.workflow_graph is None:
            raise CompilationError("WorkflowReviewAgent requires a built workflow_graph.")

        report = self._reviewer.review(state.workflow_graph)

        state.review_report = report
        scores = state.confidence_scores or ConfidenceScores()
        notes = {**scores.notes, "review": report.summary or ""}
        state.confidence_scores = scores.model_copy(update={"notes": notes})
        state.stage = CompilationStage.REVIEWED
        state.touch()
        return state

"""Default review manager wiring the deterministic GraphReviewer to the gate."""

from __future__ import annotations

from datetime import UTC, datetime

from workflow_compiler.exceptions import ApprovalError
from workflow_compiler.graph.review import GraphReviewer
from workflow_compiler.interfaces.review_manager import ReviewManager
from workflow_compiler.models import (
    ApprovalStatus,
    ReviewReport,
    WorkflowState,
)


class DefaultReviewManager(ReviewManager):
    """Review a state's graph with :class:`GraphReviewer` and record decisions.

    Reviewing is deterministic and side-effect free. Approve/reject mutate only
    the approval-related fields of the state and return it; persistence is the
    caller's responsibility (the compiler saves through its state store).
    """

    def __init__(self, *, reviewer: GraphReviewer | None = None) -> None:
        """Use the supplied :class:`GraphReviewer`, or a default instance."""
        self._reviewer = reviewer or GraphReviewer()

    async def review(self, state: WorkflowState) -> ReviewReport:
        """Produce a review report for the state's current workflow graph."""
        if state.workflow_graph is None:
            raise ApprovalError("Cannot review a state without a workflow_graph.")
        return self._reviewer.review(state.workflow_graph)

    async def approve(
        self, state: WorkflowState, *, reviewer: str | None = None
    ) -> WorkflowState:
        """Mark the graph approved, recording the reviewer on the report."""
        if state.workflow_graph is None:
            raise ApprovalError("Cannot approve a state without a workflow_graph.")
        state.approval_status = ApprovalStatus.APPROVED
        state.review_report = self._stamp(state.review_report, reviewer=reviewer)
        state.touch()
        return state

    async def reject(
        self,
        state: WorkflowState,
        *,
        reviewer: str | None = None,
        reason: str | None = None,
    ) -> WorkflowState:
        """Mark the graph rejected, recording the reviewer and a reason."""
        if state.workflow_graph is None:
            raise ApprovalError("Cannot reject a state without a workflow_graph.")
        state.approval_status = ApprovalStatus.REJECTED
        report = self._stamp(state.review_report, reviewer=reviewer)
        if reason:
            existing = report.summary
            note = f"Rejected: {reason}"
            report = report.model_copy(
                update={"summary": f"{existing}\n{note}" if existing else note}
            )
        state.review_report = report
        state.touch()
        return state

    @staticmethod
    def _stamp(report: ReviewReport | None, *, reviewer: str | None) -> ReviewReport:
        """Return a report with reviewer/timestamp recorded, creating one if needed."""
        report = report or ReviewReport()
        update: dict[str, object] = {"reviewed_at": datetime.now(UTC)}
        if reviewer is not None:
            update["reviewer"] = reviewer
        return report.model_copy(update=update)

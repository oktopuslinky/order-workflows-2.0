"""Review report models for the human-in-the-loop approval gate."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.enums import ReviewSeverity


class ReviewIssue(WorkflowBaseModel):
    """A single finding raised during review of a generated workflow graph."""

    id: str = Field(..., description="Stable identifier for the issue.")
    severity: ReviewSeverity = Field(
        default=ReviewSeverity.INFO, description="Severity of the finding."
    )
    message: str = Field(..., description="Description of the issue.")
    location: str | None = Field(
        default=None, description="Node id, edge id, or fact id the issue refers to."
    )
    suggestion: str | None = Field(default=None, description="Optional remediation suggestion.")


class ReviewReport(WorkflowBaseModel):
    """The outcome of reviewing a generated workflow graph."""

    summary: str | None = Field(default=None, description="High-level review summary.")
    issues: list[ReviewIssue] = Field(default_factory=list, description="Findings raised.")
    score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Overall quality score in [0, 1]."
    )
    health_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Structural graph-health score in [0, 1]."
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in the review itself."
    )
    reviewer: str | None = Field(default=None, description="Reviewer identity (human or agent).")
    reviewed_at: datetime | None = Field(default=None, description="Review timestamp.")

    @property
    def blocking_issues(self) -> list[ReviewIssue]:
        """Return issues that should block approval."""
        blocking = {ReviewSeverity.ERROR, ReviewSeverity.CRITICAL}
        return [issue for issue in self.issues if issue.severity in blocking]

    @property
    def errors(self) -> list[ReviewIssue]:
        """Return error/critical findings."""
        severe = {ReviewSeverity.ERROR, ReviewSeverity.CRITICAL}
        return [issue for issue in self.issues if issue.severity in severe]

    @property
    def warnings(self) -> list[ReviewIssue]:
        """Return warning findings."""
        return [issue for issue in self.issues if issue.severity is ReviewSeverity.WARNING]

    @property
    def suggested_fixes(self) -> list[str]:
        """Return the non-empty suggested fixes across all findings."""
        return [issue.suggestion for issue in self.issues if issue.suggestion]

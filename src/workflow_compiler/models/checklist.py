"""The pre-generation readiness checklist.

Before the pipeline spends an LLM design pass (and emits Temporal code) it
validates the discovered facts/structure against a fixed set of requirements
derived from ``examples/ideal_temporal_workflow.md`` — the document shape that is
known to produce clean, runnable code. Each requirement becomes a
:class:`ChecklistItem`; the collection is a :class:`WorkflowChecklist`.

The checklist is purely a *gate signal*: it never mutates the workflow. Required
items that are unmet block graph/code generation until the user supplies the
missing information (or explicitly accepts the gap), making "perfect conditions"
the precondition for generation rather than a hope.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class ChecklistSeverity(StrEnum):
    """Whether an unmet item blocks generation or merely warns."""

    REQUIRED = "required"
    OPTIONAL = "optional"


class ChecklistStatus(StrEnum):
    """Resolution state of a single checklist item."""

    SATISFIED = "satisfied"  # the document already supplies this
    MISSING = "missing"  # absent and required to be supplied
    NEEDS_CONFIRMATION = "needs_confirmation"  # present but suspect; confirm/correct
    ACCEPTED = "accepted"  # unmet but explicitly accepted as-is by the user


#: Statuses that do not block generation.
_CLEARED: frozenset[ChecklistStatus] = frozenset(
    {ChecklistStatus.SATISFIED, ChecklistStatus.ACCEPTED}
)


class ChecklistItem(WorkflowBaseModel):
    """One readiness requirement, with its current status and supporting evidence."""

    id: str = Field(..., description="Stable rule id (e.g. 'R2-inputs').")
    requirement: str = Field(..., description="Human-readable statement of what is needed.")
    category: str = Field(..., description="Grouping label (e.g. 'inputs', 'decisions').")
    severity: ChecklistSeverity = Field(
        default=ChecklistSeverity.REQUIRED,
        description="Whether an unmet item blocks generation.",
    )
    status: ChecklistStatus = Field(
        default=ChecklistStatus.MISSING, description="Current resolution state."
    )
    evidence: str | None = Field(
        default=None, description="What was (or was not) found in the document."
    )
    question: str | None = Field(
        default=None, description="What to ask the user when the item is unmet."
    )
    answer: str | None = Field(
        default=None, description="The user's supplied answer, read back from the report."
    )

    def is_cleared(self) -> bool:
        """True when this item does not block generation."""
        return self.status in _CLEARED

    def is_blocking(self) -> bool:
        """True when this required item is still unmet."""
        return self.severity == ChecklistSeverity.REQUIRED and not self.is_cleared()


class WorkflowChecklist(WorkflowBaseModel):
    """The full readiness checklist for one workflow."""

    items: list[ChecklistItem] = Field(default_factory=list)

    def unmet_required(self) -> list[ChecklistItem]:
        """Required items that are still unmet (these block generation)."""
        return [item for item in self.items if item.is_blocking()]

    def needs_input(self) -> list[ChecklistItem]:
        """Every item that is not yet cleared (the user-facing form rows)."""
        return [item for item in self.items if not item.is_cleared()]

    def is_satisfied(self) -> bool:
        """True when no required item is blocking — generation may proceed."""
        return not self.unmet_required()

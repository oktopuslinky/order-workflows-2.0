"""Capture / Validate / Process / Activate (CVPA) classification models."""

from __future__ import annotations

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.enums import CVPAPhase


class CVPANodeAssignment(WorkflowBaseModel):
    """Assignment of a single graph node to a CVPA phase."""

    node_id: str = Field(..., description="Identifier of the classified node.")
    phase: CVPAPhase = Field(..., description="Assigned Capture/Validate/Process/Activate phase.")
    rationale: str | None = Field(default=None, description="Why the node was assigned this phase.")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Classification confidence in [0, 1]."
    )


class CVPAPhaseSummary(WorkflowBaseModel):
    """Aggregate summary of a single CVPA phase across the workflow."""

    phase: CVPAPhase = Field(..., description="The phase being summarized.")
    node_ids: list[str] = Field(
        default_factory=list, description="Nodes assigned to this phase."
    )
    summary: str | None = Field(default=None, description="Narrative summary of the phase.")


class CVPAClassification(WorkflowBaseModel):
    """The full Capture/Validate/Process/Activate classification of a workflow."""

    assignments: list[CVPANodeAssignment] = Field(
        default_factory=list, description="Per-node phase assignments."
    )
    phase_summaries: list[CVPAPhaseSummary] = Field(
        default_factory=list, description="Per-phase aggregate summaries."
    )

    def nodes_in_phase(self, phase: CVPAPhase) -> list[str]:
        """Return node ids assigned to the given phase."""
        return [a.node_id for a in self.assignments if a.phase == phase]

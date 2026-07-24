"""The central WorkflowState aggregate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.checklist import WorkflowChecklist
from workflow_compiler.models.confidence import ConfidenceScores
from workflow_compiler.models.cvpa import CVPAClassification
from workflow_compiler.models.enums import ApprovalStatus, CompilationStage
from workflow_compiler.models.facts import WorkflowFacts
from workflow_compiler.models.graph import WorkflowGraph
from workflow_compiler.models.mermaid import MermaidDiagram
from workflow_compiler.models.metadata import WorkflowMetadata
from workflow_compiler.models.review import ReviewReport
from workflow_compiler.models.spec import WorkflowTrigger
from workflow_compiler.models.temporal import TemporalCodeBundle, TemporalWorkflowDesign


class WorkflowState(WorkflowBaseModel):
    """The complete, evolving state of a single workflow compilation.

    A ``WorkflowState`` starts life holding only ``document_text`` and is
    progressively enriched as it flows through the compilation pipeline. Each
    artifact field is ``None`` until its producing stage has run.
    """

    workflow_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier for this compilation run.",
    )
    document_text: str = Field(..., description="The raw business workflow document.")
    project_id: str | None = Field(
        default=None,
        description="Owning CompilationProject id when compiled via the spec front-end.",
    )

    workflow_metadata: WorkflowMetadata | None = Field(
        default=None, description="Extracted workflow metadata."
    )
    workflow_facts: WorkflowFacts | None = Field(
        default=None, description="Extracted workflow facts."
    )
    checklist: WorkflowChecklist | None = Field(
        default=None, description="Pre-generation readiness checklist (the form gate)."
    )
    outgoing_triggers: list[WorkflowTrigger] = Field(
        default_factory=list,
        description=(
            "Cross-workflow triggers this workflow fires (populated from the "
            "project at approval; empty for classic single-workflow compiles)."
        ),
    )
    workflow_graph: WorkflowGraph | None = Field(
        default=None, description="Canonical workflow graph."
    )
    review_report: ReviewReport | None = Field(
        default=None, description="Review of the generated graph."
    )
    approval_status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING, description="Human-in-the-loop approval state."
    )
    cvpa_classification: CVPAClassification | None = Field(
        default=None, description="Capture/Validate/Process/Activate classification."
    )
    temporal_design: TemporalWorkflowDesign | None = Field(
        default=None, description="Temporal workflow blueprint."
    )
    temporal_code: TemporalCodeBundle | None = Field(
        default=None, description="Executable Temporal SDK code rendered from the design."
    )
    mermaid_diagram: MermaidDiagram | None = Field(
        default=None, description="Mermaid diagram of the workflow."
    )
    confidence_scores: ConfidenceScores | None = Field(
        default=None, description="Per-stage and overall confidence scores."
    )

    stage: CompilationStage = Field(
        default=CompilationStage.INGESTED, description="Current pipeline stage."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="State creation timestamp."
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last mutation timestamp."
    )

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp to now."""
        self.updated_at = datetime.now(UTC)

"""The CompilationProject aggregate — one source document, many workflows.

Where :class:`~workflow_compiler.models.state.WorkflowState` is the per-workflow
unit threaded through the back-end pipeline, a :class:`CompilationProject` is the
parent aggregate the spec-centric front-end produces: the original document, the
discovered workflow segments, one reviewed :class:`WorkflowSpec` per workflow,
and the spec approval gate. The back-end per-workflow pipeline does not know the
project exists — approval spawns one ``WorkflowState`` per spec.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.enums import ApprovalStatus
from workflow_compiler.models.findings import Severity, SpecFinding
from workflow_compiler.models.spec import CrossReference, WorkflowSpec, WorkflowTrigger


class ProjectStage(StrEnum):
    """Ordered stages of a spec-centric compilation project."""

    INGESTED = "ingested"
    WORKFLOWS_DISCOVERED = "workflows_discovered"
    SPEC_DRAFTED = "spec_drafted"
    SPEC_VALIDATED = "spec_validated"
    SPEC_APPROVED = "spec_approved"
    COMPILING = "compiling"
    COMPLETED = "completed"
    NEEDS_ATTENTION = "needs_attention"
    FAILED = "failed"


class WorkflowSegment(WorkflowBaseModel):
    """One discovered workflow and the slice of the document that describes it."""

    id: str = Field(..., description="Stable id within the project (e.g. 'w1').")
    slug: str = Field(..., description="Filename-safe identifier derived from the name.")
    name: str = Field(..., description="Discovered workflow name.")
    purpose: str | None = Field(default=None, description="Discovered business intent.")
    section_titles: list[str] = Field(
        default_factory=list, description="Document headings assigned to this workflow."
    )
    text: str = Field(..., description="The assembled document text for this workflow.")
    sliced: bool = Field(
        default=True,
        description=(
            "Whether the text is a real per-workflow slice. False means slicing "
            "failed and the full document was used — the segment is contaminated "
            "with the other workflows' content and must not be silently compiled."
        ),
    )


class CompilationProject(WorkflowBaseModel):
    """The evolving state of one document's spec-centric compilation."""

    project_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier for this project.",
    )
    document_text: str = Field(..., description="The raw source business document.")
    segments: list[WorkflowSegment] = Field(
        default_factory=list, description="Discovered workflows and their document slices."
    )
    specs: list[WorkflowSpec] = Field(
        default_factory=list, description="One reviewed specification per workflow."
    )
    cross_references: list[CrossReference] = Field(
        default_factory=list, description="Typed output→input links between workflows."
    )
    triggers: list[WorkflowTrigger] = Field(
        default_factory=list,
        description="Executable cross-workflow triggers (start/await between workflows).",
    )
    spec_approval_status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING, description="Human approval state of the specs."
    )
    workflow_ids: dict[str, str] = Field(
        default_factory=dict,
        description="slug → compiled WorkflowState id, populated at approval.",
    )
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal issues (e.g. unlocatable segments)."
    )
    validation_findings: dict[str, list[SpecFinding]] = Field(
        default_factory=dict,
        description="slug → structured findings from the most recent validation run.",
    )
    stage: ProjectStage = Field(
        default=ProjectStage.INGESTED, description="Current project stage."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Creation timestamp."
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last mutation timestamp."
    )

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp to now."""
        self.updated_at = datetime.now(UTC)

    def spec_for(self, slug: str) -> WorkflowSpec | None:
        """Return the spec with ``slug``, if present."""
        return next((s for s in self.specs if s.slug == slug), None)

    def segment_for(self, slug: str) -> WorkflowSegment | None:
        """Return the segment with ``slug``, if present."""
        return next((s for s in self.segments if s.slug == slug), None)

    def references_for(self, slug: str) -> list[CrossReference]:
        """Cross-references in which ``slug`` participates (as source or target)."""
        return [
            r
            for r in self.cross_references
            if r.source_workflow == slug or r.target_workflow == slug
        ]

    def triggers_from(self, slug: str) -> list[WorkflowTrigger]:
        """Triggers that ``slug`` fires (its outgoing cross-workflow starts)."""
        return [t for t in self.triggers if t.source_workflow == slug]

    def has_blocking_findings(self) -> bool:
        """True when any workflow has an unresolved BLOCKING validation finding."""
        return any(
            finding.severity is Severity.BLOCKING
            for findings in self.validation_findings.values()
            for finding in findings
        )

    def findings_as_strings(self) -> dict[str, list[str]]:
        """Legacy projection: slug → one-line finding strings (for the API/overview)."""
        return {
            slug: [finding.as_string() for finding in findings]
            for slug, findings in self.validation_findings.items()
        }

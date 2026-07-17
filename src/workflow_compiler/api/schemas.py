"""Request/response DTOs for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from workflow_compiler.metrics import TimeSavedReport
from workflow_compiler.models import (
    CompilationProject,
    EditRecord,
    GeneratedFile,
    ResolvedEdit,
    WorkflowState,
)


class MetricsSummary(BaseModel):
    """Aggregate time-saved across the caller's projects (estimates, see metrics.py)."""

    projects: int = Field(default=0, description="Projects with measured timings.")
    total_baseline_hours: float = Field(default=0.0)
    total_actual_seconds: float = Field(default=0.0)
    total_saved_hours: float = Field(default=0.0)


class RegisterRequest(BaseModel):
    """Request body for creating a local account."""

    email: str = Field(..., min_length=3, description="Login email (stored lowercased).")
    password: str = Field(..., min_length=8, description="Password, at least 8 characters.")
    display_name: str = Field(
        default="", description="Name shown in the UI; defaults to the email's local part."
    )


class LoginRequest(BaseModel):
    """Request body for signing in."""

    email: str = Field(..., description="Login email.")
    password: str = Field(..., description="Password.")


class UserPublic(BaseModel):
    """The signed-in user, as exposed to the frontend (never the password hash)."""

    user_id: str = Field(...)
    email: str = Field(...)
    display_name: str = Field(...)


class ApproveRequest(BaseModel):
    """Request body for approving a workflow graph."""

    workflow_id: str = Field(..., description="Id of the workflow to approve.")
    reviewer: str | None = Field(default=None, description="Reviewer identity.")


class RejectRequest(BaseModel):
    """Request body for rejecting a workflow graph."""

    workflow_id: str = Field(..., description="Id of the workflow to reject.")
    reviewer: str | None = Field(default=None, description="Reviewer identity.")
    reason: str | None = Field(default=None, description="Reason for rejection.")


class WorkflowStateResponse(BaseModel):
    """Response wrapper carrying a full workflow state."""

    state: WorkflowState


class WorkflowIdList(BaseModel):
    """Response listing stored workflow ids."""

    workflow_ids: list[str] = Field(default_factory=list)


class ProjectCompileRequest(BaseModel):
    """Request body for compiling a document into a spec project."""

    document_text: str = Field(..., description="The raw business workflow document.")
    persist: bool = Field(default=True, description="Persist the resulting project.")
    model: str | None = Field(
        default=None,
        description="Optional local gateway model id for this compile (else the server default).",
    )


class LocalModelList(BaseModel):
    """Response listing the models the local eGPU gateway exposes."""

    models: list[str] = Field(default_factory=list)


class SpecUpdateRequest(BaseModel):
    """Edited spec file contents keyed by workflow slug."""

    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → edited spec Markdown."
    )


class ProjectEditRequest(BaseModel):
    """Request body for applying a workflow edit-request document."""

    edit_document: str = Field(
        ..., description="The edit-request Markdown (see docs/EDIT_FORMAT_GUIDE.md)."
    )
    workflows: list[str] | None = Field(
        default=None, description="Restrict edits to these slugs (default: any)."
    )
    author: str | None = Field(
        default=None, description="Author recorded in the project's edit log."
    )
    resolved: ResolvedEdit | None = Field(
        default=None,
        description=(
            "Preview handoff from POST /projects/{id}/edit/preview — apply exactly "
            "those interpreted operations with no LLM re-interpretation. A stale "
            "blob (the project changed since the preview) answers 409."
        ),
    )


class EditPreviewResponse(BaseModel):
    """A previewed edit: what would change, without persisting anything."""

    record: EditRecord = Field(
        ..., description="The would-be audit entry (summary, patches, wiring ops)."
    )
    resolved: ResolvedEdit = Field(
        ..., description="Replayable interpretation — send back on confirm."
    )
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → post-edit rendered spec Markdown."
    )
    workflows_added: list[str] = Field(default_factory=list)
    workflows_removed: list[str] = Field(default_factory=list)


class ProjectApproveRequest(BaseModel):
    """Request body for approving a project's specs."""

    workflows: list[str] | None = Field(
        default=None, description="Slugs to approve (default: all)."
    )
    reviewer: str | None = Field(default=None, description="Reviewer identity.")
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="Final edited spec Markdown by slug."
    )
    accept_incomplete: bool = Field(
        default=False, description="Proceed despite unanswered required questions."
    )
    allow_unconfirmed_references: bool = Field(
        default=False, description="Proceed without confirming cross-workflow links."
    )


class ProjectResponse(BaseModel):
    """Response wrapper carrying a project plus its rendered spec files."""

    project: CompilationProject
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → rendered spec Markdown."
    )
    time_saved: TimeSavedReport | None = Field(
        default=None,
        description=(
            "Measured pipeline time vs. estimated human-team hours (None when "
            "nothing was measured). Baselines are configurable estimates."
        ),
    )
    diagrams: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "slug → structural Mermaid diagram source, built deterministically from "
            "the current specs (a preview of the graph approval will build)."
        ),
    )


class CvpaPreviewRequest(BaseModel):
    """Request body for an on-demand CVPA phase-coloring preview."""

    workflow: str = Field(..., description="Slug of the workflow to classify.")


class CvpaPreviewResponse(BaseModel):
    """A single workflow's CVPA phase-colored Mermaid diagram (display-only)."""

    slug: str = Field(..., description="Slug of the classified workflow.")
    diagram: str = Field(..., description="CVPA phase-colored Mermaid diagram source.")


class ProjectIdList(BaseModel):
    """Response listing stored project ids."""

    project_ids: list[str] = Field(default_factory=list)


class ProjectFilesResponse(BaseModel):
    """Flat, directory-prefixed file tree for a compiled project (ready to zip)."""

    project_id: str = Field(..., description="Id of the project the files belong to.")
    files: list[GeneratedFile] = Field(
        default_factory=list,
        description=(
            "Every generated file: each workflow's bundle under '<slug>/...' plus the "
            "shared project glue files (contracts.py, README.md) at the root."
        ),
    )

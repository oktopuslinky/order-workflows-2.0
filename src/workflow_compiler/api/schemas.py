"""Request/response DTOs for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from workflow_compiler.models import CompilationProject, WorkflowState


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


class SpecUpdateRequest(BaseModel):
    """Edited spec file contents keyed by workflow slug."""

    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → edited spec Markdown."
    )


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


class ProjectIdList(BaseModel):
    """Response listing stored project ids."""

    project_ids: list[str] = Field(default_factory=list)

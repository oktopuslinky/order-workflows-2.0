"""Request/response DTOs for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from workflow_compiler.models import WorkflowState


class CompileRequest(BaseModel):
    """Request body for compiling a document."""

    document_text: str = Field(..., description="The raw business workflow document.")
    persist: bool = Field(default=True, description="Persist the resulting state.")
    auto_approve: bool = Field(
        default=False,
        description="Skip the human gate and run the full pipeline end-to-end.",
    )


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

"""Workflow metadata model."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class WorkflowMetadata(WorkflowBaseModel):
    """High-level descriptive metadata for a compiled workflow."""

    name: str = Field(..., description="Human-readable workflow name.")
    description: str | None = Field(
        default=None, description="Short summary of the workflow's purpose."
    )
    purpose: str | None = Field(
        default=None, description="What the workflow is meant to achieve (business intent)."
    )
    actors: list[str] = Field(
        default_factory=list, description="Human/role participants in the workflow."
    )
    systems: list[str] = Field(
        default_factory=list, description="External systems/services the workflow touches."
    )
    trigger_events: list[str] = Field(
        default_factory=list, description="Events that initiate the workflow."
    )
    start_states: list[str] = Field(
        default_factory=list, description="Entry/start states of the workflow."
    )
    end_states: list[str] = Field(
        default_factory=list, description="Terminal/end states of the workflow."
    )
    version: str = Field(
        default="0.1.0", description="Semantic version of the workflow definition."
    )
    domain: str | None = Field(
        default=None, description="Business domain, e.g. 'order-management'."
    )
    owner: str | None = Field(
        default=None, description="Team or person accountable for the workflow."
    )
    source_format: str | None = Field(
        default=None,
        description="Detected source document format (markdown, docx, plain, ...).",
    )
    tags: list[str] = Field(default_factory=list, description="Free-form classification tags.")
    extra: dict[str, str] = Field(
        default_factory=dict, description="Additional provider/parser-specific metadata."
    )
    created_at: datetime | None = Field(
        default=None, description="Timestamp the source document was authored, if known."
    )

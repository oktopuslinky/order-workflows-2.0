"""The DocumentCompilation aggregate — the outer, multi-workflow container.

A single business document may describe several workflows. ``DocumentCompilation``
is the outer aggregate that holds the segmentation of a document into N workflows,
the authored master document a human edits, and pointers to each per-workflow
:class:`~workflow_compiler.models.state.WorkflowState`. The single-workflow
``WorkflowState`` is intentionally left untouched; this model wraps it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.enums import DocumentStage


class WorkflowSegment(WorkflowBaseModel):
    """One workflow carved out of a multi-workflow document by segmentation.

    ``source_text`` is the slice of the original document attributed to this
    workflow — it becomes the ``document_text`` of the child ``WorkflowState``.
    ``invokes`` names other workflows (by canonical name) this one triggers as a
    Temporal child workflow. ``questions`` are the open clarifications the LLM
    surfaced for a human to resolve in the master document.
    """

    id: str = Field(..., description="Stable segment id (e.g. 'w1').")
    name: str = Field(..., description="Canonical workflow name (PascalCase-friendly).")
    summary: str = Field(default="", description="One-line description of the workflow.")
    source_text: str = Field(
        default="", description="The document slice attributed to this workflow."
    )
    invokes: list[str] = Field(
        default_factory=list,
        description="Names of workflows this one invokes as child workflows.",
    )
    questions: list[str] = Field(
        default_factory=list,
        description="Open clarification questions the LLM raised for this workflow.",
    )
    workflow_id: str | None = Field(
        default=None,
        description="Id of the child WorkflowState once this segment is compiled.",
    )


class DocumentCompilation(WorkflowBaseModel):
    """The evolving state of compiling one document into many workflows.

    Starts holding only ``source_text``; segmentation fills ``segments``, the
    authoring stage fills ``master_document``, and the recompile stage fills
    ``workflow_ids`` (one per per-workflow ``WorkflowState``, persisted separately).
    """

    document_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier for this document compilation.",
    )
    source_text: str = Field(..., description="The raw (possibly multi-workflow) document.")
    master_document: str | None = Field(
        default=None,
        description="The authored, human-editable master document (ideal-format sections).",
    )
    segments: list[WorkflowSegment] = Field(
        default_factory=list, description="The workflows carved out of the document."
    )
    workflow_ids: list[str] = Field(
        default_factory=list,
        description="Ids of the child WorkflowStates produced on recompile.",
    )
    clarifications: list[str] = Field(
        default_factory=list,
        description="Document-level open questions raised during segmentation.",
    )
    stage: DocumentStage = Field(
        default=DocumentStage.SEGMENTED, description="Current outer-pipeline stage."
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

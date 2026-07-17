"""Edit-request models — the vocabulary of the workflow edit pipeline.

An *edit request* is a human-authored Markdown document describing changes to
previously-compiled workflows. Its structured skeleton is parsed
deterministically (``spec/edit_ingest.py``); the natural-language entries inside
are interpreted by :class:`~workflow_compiler.agents.edit_interpreter.EditInterpreterAgent`
into an :class:`EditPlan` — the existing review :class:`~workflow_compiler.models.patch.Patch`
vocabulary plus typed wiring operations that patches cannot express.

Like ``models/patch.py``, the plan models are **LLM output schemas** and are
permissive (``extra="ignore"``); the deterministic appliers do the strict work.
:class:`EditRecord` is the strict domain model appended to a project's edit log
after a successful application.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.patch import Patch
from workflow_compiler.models.spec import CrossReference, WorkflowTrigger


class WiringAction(StrEnum):
    """Operations on cross-workflow wiring (triggers and cross-references)."""

    ADD = "add"
    REMOVE = "remove"
    MODIFY = "modify"


class TriggerOp(BaseModel):
    """One edit to the project's cross-workflow triggers.

    Triggers are structured objects (mode, condition, typed ``input_map``), so
    they get a typed payload instead of being squeezed into ``Patch.payload``.
    ``source_workflow``/``target_workflow`` identify the trigger being edited;
    ``trigger`` carries the full desired object for ``add``/``modify`` and is
    ignored for ``remove``.
    """

    model_config = ConfigDict(extra="ignore")

    action: WiringAction = Field(default=WiringAction.ADD)
    source_workflow: str = Field(default="", description="Slug firing the trigger.")
    target_workflow: str = Field(default="", description="Slug being started.")
    trigger: WorkflowTrigger | None = Field(
        default=None, description="Full trigger payload for add/modify; None for remove."
    )


class XrefOp(BaseModel):
    """One edit to the project's output→input cross-references.

    The reference's 4-tuple (source workflow, output field, target workflow,
    input field) identifies which link is being added, removed, or replaced.
    """

    model_config = ConfigDict(extra="ignore")

    action: WiringAction = Field(default=WiringAction.ADD)
    reference: CrossReference | None = Field(
        default=None, description="The full cross-reference payload (identifies + replaces)."
    )


class EditPlan(BaseModel):
    """The interpreter's structured translation of one edit-request section.

    ``patches`` reuse the review vocabulary and are applied by the
    human-authority spec applier; ``trigger_ops``/``xref_ops`` are applied
    deterministically to the project wiring. Entries the model could not map
    go verbatim into ``unresolved`` — a non-empty list aborts the whole edit
    (human edits must never silently vanish).
    """

    model_config = ConfigDict(extra="ignore")

    patches: list[Patch] = Field(default_factory=list)
    trigger_ops: list[TriggerOp] = Field(default_factory=list)
    xref_ops: list[XrefOp] = Field(default_factory=list)
    unresolved: list[str] = Field(
        default_factory=list, description="Edit entries the model could not translate."
    )
    note: str = Field(default="", description="Optional free-text rationale.")


class EditRecord(WorkflowBaseModel):
    """One applied edit request, appended to ``CompilationProject.edit_log``.

    The append-only log is the project's audit trail: the verbatim document,
    the resolved operations, and a per-workflow human-readable summary.
    """

    edit_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier for this edit.",
    )
    document: str = Field(..., description="The verbatim edit-request Markdown.")
    author: str | None = Field(default=None, description="Who submitted the edit.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When the edit was applied."
    )
    resolved_patches: dict[str, list[Patch]] = Field(
        default_factory=dict, description="slug → patches applied to that workflow's spec."
    )
    trigger_ops: list[TriggerOp] = Field(
        default_factory=list, description="Cross-workflow trigger operations applied."
    )
    xref_ops: list[XrefOp] = Field(
        default_factory=list, description="Cross-reference operations applied."
    )
    workflows_added: list[str] = Field(
        default_factory=list, description="Slugs of workflows created by this edit."
    )
    workflows_removed: list[str] = Field(
        default_factory=list, description="Slugs of workflows deleted by this edit."
    )
    summary: dict[str, list[str]] = Field(
        default_factory=dict, description="slug → human-readable change lines."
    )

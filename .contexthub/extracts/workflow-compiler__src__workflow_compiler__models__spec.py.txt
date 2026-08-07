"""Workflow specification models — the human-reviewed primary artifact.

A :class:`WorkflowSpec` is the structured **source of truth** for one workflow
after the front-end (segmentation + fact extraction) has run. The Markdown file
the user reviews is a deterministic *projection* of this model (rendered by
``spec/renderer.py``); human edits to that file are folded back in as validated
patches (``spec/ingest.py``) — the model is never regenerated from free prose.

Provenance is what lets the spec validator flag LLM inferences without fighting
legitimate human additions: an element marked ``HUMAN_PROVIDED`` may be flagged
for confirmation but is never dropped by a grounding pass.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.facts import WorkflowFacts
from workflow_compiler.models.metadata import WorkflowMetadata
from workflow_compiler.models.temporal import BindingSource


class Provenance(StrEnum):
    """Where a spec element came from — drives how the validator treats it.

    * ``DOCUMENT_GROUNDED`` — explicitly supported by the source document.
    * ``LLM_INFERRED`` — produced by a model without direct textual support;
      the grounding pass may flag or remove it.
    * ``HUMAN_PROVIDED`` — added or confirmed by the user editing the spec;
      the grounding pass may flag it for confirmation but never removes it.
    """

    DOCUMENT_GROUNDED = "document_grounded"
    LLM_INFERRED = "llm_inferred"
    HUMAN_PROVIDED = "human_provided"


class SpecItem(WorkflowBaseModel):
    """One free-text review item (assumption, ambiguity, open question, ...)."""

    text: str = Field(..., description="The item's statement or question.")
    provenance: Provenance = Field(
        default=Provenance.LLM_INFERRED, description="Where this item came from."
    )
    resolved: bool = Field(
        default=False, description="True once the user has answered/settled the item."
    )
    answer: str | None = Field(
        default=None, description="The user's answer, when the item is a question."
    )
    ref: str | None = Field(
        default=None,
        description="Optional stable reference (e.g. the checklist item id 'R2-inputs').",
    )


class CrossReference(WorkflowBaseModel):
    """A typed output→input link between two workflows in the same project.

    Workflows are compiled independently, but when one workflow's output feeds
    another's input the link is recorded here so the user can validate it during
    spec review. Links are advisory until ``user_confirmed`` is set.
    """

    source_workflow: str = Field(..., description="Slug of the workflow producing the output.")
    output_field: str = Field(..., description="Name of the produced output field.")
    output_type: str = Field(
        default="str", description="Python type of the produced output (LLM-inferred, editable)."
    )
    target_workflow: str = Field(..., description="Slug of the workflow consuming the value.")
    input_field: str = Field(..., description="Name of the consuming input field.")
    input_type: str = Field(
        default="str", description="Python type of the consumed input (LLM-inferred, editable)."
    )
    description: str | None = Field(
        default=None, description="Plain-language explanation of the dependency."
    )
    user_confirmed: bool = Field(
        default=False, description="True once the user has validated this link."
    )


class TriggerMode(StrEnum):
    """How a source workflow relates to a workflow it triggers.

    * ``BLOCKING`` — the caller awaits the triggered workflow's result (bound to
      ``result_binding``) before continuing.
    * ``FIRE_AND_FORGET`` — the caller starts the target and moves on.
    """

    BLOCKING = "blocking"
    FIRE_AND_FORGET = "fire_and_forget"


class TriggerInputBinding(WorkflowBaseModel):
    """One field of the triggered workflow's input and where its value comes from.

    A :class:`WorkflowTrigger` carries a *list* of these — together they assemble
    the full typed ``WorkflowInput`` the standalone target receives at start.
    """

    target_input: str = Field(..., description="Field on the target workflow's WorkflowInput.")
    source: BindingSource = Field(
        default=BindingSource.CONSTANT,
        description="Where the value comes from (caller input / earlier step / constant).",
    )
    source_ref: str | None = Field(
        default=None,
        description=(
            "For WORKFLOW_INPUT: the caller's WorkflowInput field name. "
            "For STEP_OUTPUT: the producing step id. For CONSTANT: ignored."
        ),
    )
    type: str = Field(default="str", description="Python type of the handed-off value.")


class WorkflowTrigger(WorkflowBaseModel):
    """An executable cross-workflow trigger: one workflow starts another.

    Where a :class:`CrossReference` is advisory data-dependency metadata, a
    trigger compiles to runtime wiring: the standalone ``source_workflow`` starts
    the standalone ``target_workflow``, passing a full typed input assembled from
    ``input_map``. ``condition`` (when set) makes the trigger conditional and is
    LLM-drafted then human-confirmed; ``mode`` decides whether the caller awaits
    the target's result (which BLOCKING binds to ``result_binding``). Both
    workflows remain independently runnable — the trigger only adds glue.
    """

    source_workflow: str = Field(..., description="Slug of the workflow that fires the trigger.")
    target_workflow: str = Field(
        ..., description="Slug of the standalone workflow being started."
    )
    mode: TriggerMode = Field(
        default=TriggerMode.FIRE_AND_FORGET,
        description="Whether the caller awaits the target's result or moves on.",
    )
    condition: str | None = Field(
        default=None,
        description=(
            "Predicate gating the trigger; None = unconditional. LLM-drafted, "
            "human-confirmed (mirrors branch-predicate provenance)."
        ),
    )
    input_map: list[TriggerInputBinding] = Field(
        default_factory=list, description="Full typed input record for the target workflow."
    )
    result_binding: str | None = Field(
        default=None,
        description="BLOCKING only: variable name the target's result is bound to.",
    )
    user_confirmed: bool = Field(
        default=False, description="True once the user has validated this trigger."
    )


class WorkflowSpec(WorkflowBaseModel):
    """The complete reviewed specification for one workflow.

    Combines the structured extraction (metadata + facts/structure) with the
    review-surface lists a human resolves before approval. ``provenance``
    records, per element reference (e.g. ``activity:a3``, ``input:order_id``,
    ``actors:Warehouse``), where an element came from when it differs from the
    default ``DOCUMENT_GROUNDED``.
    """

    slug: str = Field(..., description="Filename-safe identifier, unique within a project.")
    metadata: WorkflowMetadata = Field(..., description="Discovered workflow metadata.")
    facts: WorkflowFacts = Field(
        default_factory=WorkflowFacts, description="Extracted facts + relational structure."
    )
    assumptions: list[SpecItem] = Field(
        default_factory=list, description="Assumptions made while interpreting the document."
    )
    ambiguities: list[SpecItem] = Field(
        default_factory=list, description="Points the document leaves ambiguous."
    )
    open_questions: list[SpecItem] = Field(
        default_factory=list,
        description="Missing information the user must supply (absorbs the checklist form).",
    )
    suggested_edits: list[SpecItem] = Field(
        default_factory=list, description="Improvements the pipeline suggests to the user."
    )
    provenance: dict[str, Provenance] = Field(
        default_factory=dict,
        description="Per-element provenance overrides, keyed by element reference.",
    )

    def unresolved_questions(self) -> list[SpecItem]:
        """Open questions the user has not yet answered."""
        return [q for q in self.open_questions if not q.resolved]

    def provenance_of(self, ref: str) -> Provenance:
        """Return the provenance recorded for ``ref`` (default: document-grounded)."""
        return self.provenance.get(ref, Provenance.DOCUMENT_GROUNDED)

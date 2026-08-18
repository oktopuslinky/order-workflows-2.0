"""The change spec — existing vs. proposed per component (plan D9, Phase 3).

A :class:`ChangeSpec` is the second half of a knowledge-graph-grounded workflow
project: where the :class:`~workflow_compiler.models.spec.WorkflowSpec` describes
the *process* the TDD implies, the change spec describes the *code-level
deltas* the TDD asks for — one :class:`ComponentChange` per module / activity /
workflow / type / signal / query / test / diagram / doc, each with the text of
what exists today and what is proposed.

Like the workflow spec it is the structured source of truth: ``changes.md``
(``spec/change_renderer.py``) is a deterministic projection, ``spec/change_ingest.py``
folds human edits back, ``spec/change_validator.py`` produces findings under the
``__changes__`` pseudo-slug so the Resolve dialogue can ask about them.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.dialogue import SuggestedOption
from workflow_compiler.models.spec import Provenance, SpecItem

#: The pseudo-slug ``changes.md`` findings and markdown travel under. It is
#: deliberately unlike any workflow slug (slugs never start with ``_``).
CHANGES_SLUG = "__changes__"


class ComponentKind(StrEnum):
    """What kind of thing a component change touches."""

    MODULE = "module"
    ACTIVITY = "activity"
    WORKFLOW = "workflow"
    TYPE = "type"
    SIGNAL = "signal"
    QUERY = "query"
    TEST = "test"
    DIAGRAM = "diagram"
    DOC = "doc"


class ChangeType(StrEnum):
    """How the component changes."""

    MODIFY = "modify"
    ADD = "add"
    REMOVE = "remove"
    VERIFY = "verify"


class ComponentChange(WorkflowBaseModel):
    """One component's existing state and proposed change."""

    name: str = Field(..., description="Component name, e.g. 'provision_order' or 'OrderState'.")
    kind: ComponentKind = Field(default=ComponentKind.MODULE, description="Component kind.")
    path: str = Field(
        default="",
        description=(
            "Where the component lives: a knowledge-graph node id "
            "(`mod:existing_Codebase/shared/types.py`) or a corpus-relative file path. "
            "Empty for a component that does not exist yet."
        ),
    )
    existing: str = Field(default="", description="What exists today (from the TDD / KB).")
    proposed: str = Field(default="", description="What the TDD proposes.")
    change_type: ChangeType = Field(default=ChangeType.MODIFY, description="Nature of the change.")
    requirement_ids: list[str] = Field(
        default_factory=list, description="Change-request requirement ids this change serves."
    )
    provenance: Provenance = Field(
        default=Provenance.LLM_INFERRED, description="Where this component change came from."
    )

    def key(self) -> str:
        """Case-insensitive identity used to match components across edits."""
        return f"{self.kind.value}:{self.name.strip().lower()}"


class ChangeSpec(WorkflowBaseModel):
    """The change specification for one KG-grounded workflow project."""

    components: list[ComponentChange] = Field(default_factory=list)
    assumptions: list[SpecItem] = Field(default_factory=list)
    open_questions: list[SpecItem] = Field(default_factory=list)
    sources: list[str] = Field(
        default_factory=list,
        description="Knowledge-base files (with line spans) the extraction was grounded on.",
    )
    version: int = Field(default=1, description="Bumped on every fold-in / dialogue change.")

    def component(
        self, name: str, kind: ComponentKind | str | None = None
    ) -> ComponentChange | None:
        """Find a component by name (and kind when given), case-insensitively."""
        needle = name.strip().lower()
        for component in self.components:
            if component.name.strip().lower() != needle:
                continue
            if kind is not None and component.kind.value != str(kind):
                continue
            return component
        return None

    def unresolved_questions(self) -> list[SpecItem]:
        """Open questions the user has not answered yet."""
        return [q for q in self.open_questions if not q.resolved]


# --------------------------------------------------------------------------- #
# LLM plans (permissive: extra keys ignored, everything defaulted)
# --------------------------------------------------------------------------- #


class ComponentDraft(BaseModel):
    """One component as the extraction model returns it (cleaned by the agent)."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    kind: str = "module"
    path: str = ""
    existing: str = ""
    proposed: str = ""
    change_type: str = "modify"
    requirement_ids: list[str] = Field(default_factory=list)


class ChangeSpecDraft(BaseModel):
    """The extraction model's whole answer for ``extract_change_spec``."""

    model_config = ConfigDict(extra="ignore")

    components: list[ComponentDraft] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class ComponentUpdate(BaseModel):
    """One deterministic update to a component, as the answer interpreter emits it."""

    model_config = ConfigDict(extra="ignore")

    action: str = Field(default="modify", description="modify | add | remove")
    name: str = ""
    kind: str | None = None
    path: str | None = None
    existing: str | None = None
    proposed: str | None = None
    change_type: str | None = None
    requirement_ids: list[str] | None = None
    evidence: str = ""


class ChangeAnswerPlan(BaseModel):
    """The interpreter's reading of one prose answer to a change-spec question.

    Same disposition rules as :class:`~workflow_compiler.models.dialogue.AnswerPlan`:
    updates win; otherwise one follow-up; otherwise the answer is parked.
    """

    model_config = ConfigDict(extra="ignore")

    updates: list[ComponentUpdate] = Field(default_factory=list)
    resolve_questions: list[str] = Field(
        default_factory=list, description="Open-question texts this answer settles."
    )
    needs_followup: bool = False
    followup_question: str | None = None
    followup_options: list[SuggestedOption] = Field(default_factory=list)
    park_note: str | None = None
    note: str = ""


__all__ = [
    "CHANGES_SLUG",
    "ChangeAnswerPlan",
    "ChangeSpec",
    "ChangeSpecDraft",
    "ChangeType",
    "ComponentChange",
    "ComponentDraft",
    "ComponentKind",
    "ComponentUpdate",
]

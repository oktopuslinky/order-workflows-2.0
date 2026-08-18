"""Change requests, the guided wizard that analyses them, and the artifacts it drafts.

A *change request* pairs a business-change document (a BCR ``.docx``, or plain
markdown/text) with a knowledge base. A deterministic wizard walks it through
four steps — **Impact → EPIC → Stories → TDD** — asking a few clarifying
questions before each draft, then producing one markdown artifact per step
that the user can revise in chat, edit by hand, and approve.

Two families of model live here, split exactly like ``models/dialogue.py``:

* **Persisted state** — :class:`ChangeRequest`, :class:`WizardSession`,
  :class:`Artifact` and friends are strict domain data stored under
  ``<state-root>/change_requests/<cr_id>.json``. Every artifact keeps its full
  version history (``llm_draft`` / ``llm_revision`` / ``human_edit``).
* **Document content + LLM output schemas** — :class:`ImpactDoc`,
  :class:`EpicDoc`, :class:`StoryDoc`, :class:`TddDoc` are the structured
  form of each artifact. They are permissive (``extra="ignore"``, defaulted)
  because the drafting agent returns them and a slightly-off model answer
  must still parse; the deterministic engine (``change/engine.py``) fills in
  ids, metadata and sources, ``change/render.py`` projects them to markdown
  and ``change/parse.py`` reads that markdown back (round trip is tested).

The engine — never the model — assigns business ids (``EPIC-002``,
``US-008``…, ``TDD-ORD-002``) from the knowledge base's catalog.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.dialogue import SuggestedOption


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class ArtifactKind(StrEnum):
    """The four artifacts a change request produces, in wizard order."""

    IMPACT = "impact"
    EPIC = "epic"
    STORIES = "stories"
    TDD = "tdd"


#: Wizard order — the cursor walks this list.
WIZARD_ORDER: tuple[ArtifactKind, ...] = (
    ArtifactKind.IMPACT,
    ArtifactKind.EPIC,
    ArtifactKind.STORIES,
    ArtifactKind.TDD,
)

#: Human labels for the stepper / CLI.
STEP_LABELS: dict[ArtifactKind, str] = {
    ArtifactKind.IMPACT: "Impact analysis",
    ArtifactKind.EPIC: "EPIC",
    ArtifactKind.STORIES: "User stories",
    ArtifactKind.TDD: "Technical design",
}


class ArtifactStatus(StrEnum):
    EMPTY = "empty"
    DRAFTED = "drafted"
    APPROVED = "approved"


class VersionSource(StrEnum):
    """Who produced an artifact version."""

    LLM_DRAFT = "llm_draft"
    LLM_REVISION = "llm_revision"
    HUMAN_EDIT = "human_edit"


class StepStatus(StrEnum):
    """Lifecycle of one wizard step.

    ``PENDING`` — not reached; ``ASKING`` — questions drafted, being answered;
    ``DRAFTING`` — a draft job is running; ``DRAFTED`` — an artifact exists and
    can be revised/edited; ``APPROVED`` — the user signed it off (cursor moves on).
    """

    PENDING = "pending"
    ASKING = "asking"
    DRAFTING = "drafting"
    DRAFTED = "drafted"
    APPROVED = "approved"


class WizardQuestionStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    SKIPPED = "skipped"


class ChangeRequestStage(StrEnum):
    """Coarse lifecycle of a change request."""

    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


class ChangeType(StrEnum):
    MODIFY = "modify"
    ADD = "add"
    REMOVE = "remove"
    VERIFY = "verify"


# --------------------------------------------------------------------------- #
# Persisted state
# --------------------------------------------------------------------------- #


class BcrMeta(WorkflowBaseModel):
    """The metadata block at the top of a BCR, parsed deterministically."""

    doc_id: str | None = Field(default=None, description="e.g. BCR-001.")
    status: str | None = None
    requested_by: str | None = None
    date_raised: str | None = None
    target_workflow: str | None = None


class ChangeRequirement(WorkflowBaseModel):
    """One numbered requirement from the change request (``BCR-01-03`` …)."""

    id: str
    text: str


class SourceRef(BaseModel):
    """A knowledge-base file (with line spans) an artifact was grounded on."""

    model_config = ConfigDict(extra="ignore")

    path: str
    spans: list[tuple[int, int]] = Field(default_factory=list)


class ArtifactVersion(WorkflowBaseModel):
    version: int
    markdown: str
    source: VersionSource
    note: str = Field(default="", description="Draft summary, revision summary or edit note.")
    at: datetime = Field(default_factory=_now)


class Artifact(WorkflowBaseModel):
    """One markdown artifact with its full version history."""

    kind: ArtifactKind
    markdown: str = ""
    version: int = 0
    status: ArtifactStatus = ArtifactStatus.EMPTY
    history: list[ArtifactVersion] = Field(default_factory=list)
    sources: list[SourceRef] = Field(
        default_factory=list, description="KB files the latest LLM draft/revision was grounded on."
    )
    coverage: float | None = Field(
        default=None, description="Retrieval coverage of the latest LLM draft (0..1)."
    )
    approved_at: datetime | None = None

    def add_version(self, markdown: str, source: VersionSource, note: str = "") -> ArtifactVersion:
        """Append a new version and make it current (returns it)."""
        entry = ArtifactVersion(
            version=self.version + 1, markdown=markdown, source=source, note=note
        )
        self.history.append(entry)
        self.markdown = markdown
        self.version = entry.version
        if self.status == ArtifactStatus.EMPTY:
            self.status = ArtifactStatus.DRAFTED
        return entry

    def get_version(self, version: int) -> ArtifactVersion | None:
        for entry in self.history:
            if entry.version == version:
                return entry
        return None


class ChangeArtifacts(WorkflowBaseModel):
    impact: Artifact = Field(default_factory=lambda: Artifact(kind=ArtifactKind.IMPACT))
    epic: Artifact = Field(default_factory=lambda: Artifact(kind=ArtifactKind.EPIC))
    stories: Artifact = Field(default_factory=lambda: Artifact(kind=ArtifactKind.STORIES))
    tdd: Artifact = Field(default_factory=lambda: Artifact(kind=ArtifactKind.TDD))

    def get(self, kind: ArtifactKind | str) -> Artifact:
        return {
            ArtifactKind.IMPACT: self.impact,
            ArtifactKind.EPIC: self.epic,
            ArtifactKind.STORIES: self.stories,
            ArtifactKind.TDD: self.tdd,
        }[ArtifactKind(kind)]

    def all(self) -> list[Artifact]:
        return [self.impact, self.epic, self.stories, self.tdd]


class ChatTurn(WorkflowBaseModel):
    """One line of the per-step conversation shown in the chat column."""

    role: str = Field(..., description="assistant | user | system")
    text: str
    kind: str = Field(
        default="message",
        description=(
            "question | answer | followup | note | draft | revision | edit | approve | status"
        ),
    )
    at: datetime = Field(default_factory=_now)


class WizardQuestion(WorkflowBaseModel):
    """A clarifying question asked before drafting a step (mirrors DialogueQuestion)."""

    question_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    why: str = Field(default="", description="Why the drafter needs this (shown as a hint).")
    options: list[SuggestedOption] = Field(default_factory=list)
    status: WizardQuestionStatus = WizardQuestionStatus.PENDING
    answer: str | None = None
    chosen_option: str | None = None
    followups: list[str] = Field(default_factory=list)
    followup_options: list[SuggestedOption] = Field(default_factory=list)
    note: str | None = Field(
        default=None, description="The brief line the answer became (folded into drafting)."
    )

    @property
    def awaiting_followup(self) -> bool:
        return self.status == WizardQuestionStatus.PENDING and bool(self.followups)

    @property
    def prompt(self) -> str:
        return self.followups[-1] if self.awaiting_followup else self.text

    @property
    def prompt_options(self) -> list[SuggestedOption]:
        return self.followup_options if self.awaiting_followup else self.options


class WizardStep(WorkflowBaseModel):
    kind: ArtifactKind
    status: StepStatus = StepStatus.PENDING
    questions: list[WizardQuestion] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list, description="Answers folded into brief lines for the drafter."
    )
    turns: list[ChatTurn] = Field(default_factory=list)
    error: str | None = Field(default=None, description="Last draft/revise failure, if any.")
    started_at: datetime | None = None
    drafted_at: datetime | None = None
    approved_at: datetime | None = None

    @property
    def current_question(self) -> WizardQuestion | None:
        for question in self.questions:
            if question.status == WizardQuestionStatus.PENDING:
                return question
        return None

    @property
    def questions_done(self) -> bool:
        return self.current_question is None

    def say(self, role: str, text: str, kind: str = "message") -> None:
        self.turns.append(ChatTurn(role=role, text=text, kind=kind))


class WizardSession(WorkflowBaseModel):
    steps: list[WizardStep] = Field(
        default_factory=lambda: [WizardStep(kind=kind) for kind in WIZARD_ORDER]
    )
    cursor: int = Field(default=0, ge=0)
    provider: str | None = None
    model: str | None = None
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()

    def step(self, kind: ArtifactKind | str) -> WizardStep:
        wanted = ArtifactKind(kind)
        for step in self.steps:
            if step.kind == wanted:
                return step
        raise KeyError(wanted)

    @property
    def current(self) -> WizardStep | None:
        if 0 <= self.cursor < len(self.steps):
            return self.steps[self.cursor]
        return None

    @property
    def complete(self) -> bool:
        return self.cursor >= len(self.steps)

    def index_of(self, kind: ArtifactKind | str) -> int:
        wanted = ArtifactKind(kind)
        for i, step in enumerate(self.steps):
            if step.kind == wanted:
                return i
        raise KeyError(wanted)


class ImpactTableRow(WorkflowBaseModel):
    """One row of the deterministic impact traversal kept on the change request."""

    node_id: str
    type: str
    name: str
    path: str | None = None
    hops: int
    via: str = ""


class AssignedIds(WorkflowBaseModel):
    """Business ids the engine reserved from the knowledge base's catalog."""

    epic_id: str = ""
    story_ids: list[str] = Field(default_factory=list)
    tdd_id: str = ""
    next_test_case: str = Field(default="", description="First free TC id (Phase 4 uses it).")
    prior_epic_id: str | None = Field(default=None, description="The epic being extended.")
    prior_tdd_id: str | None = Field(default=None, description="The TDD being superseded.")


class ChangeRequest(WorkflowBaseModel):
    """A business-change request under analysis against one knowledge base."""

    cr_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kb_id: str
    kb_name: str = ""
    owner_id: str | None = None
    title: str
    document_text: str
    source_filename: str | None = None
    bcr_meta: BcrMeta = Field(default_factory=BcrMeta)
    requirements: list[ChangeRequirement] = Field(default_factory=list)
    impact_seed_terms: list[str] = Field(default_factory=list)
    impact_table: list[ImpactTableRow] = Field(
        default_factory=list,
        description="Deterministic KG traversal from the seed terms (computed at wizard start).",
    )
    ids: AssignedIds = Field(default_factory=AssignedIds)
    wizard: WizardSession = Field(default_factory=WizardSession)
    artifacts: ChangeArtifacts = Field(default_factory=ChangeArtifacts)
    project_ids: list[str] = Field(default_factory=list)
    stage: ChangeRequestStage = ChangeRequestStage.CREATED
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()
        self.wizard.touch()

    @property
    def doc_id(self) -> str:
        return self.bcr_meta.doc_id or "BCR"


# --------------------------------------------------------------------------- #
# Document content (structured artifacts) — permissive, shared with the LLM
# --------------------------------------------------------------------------- #


class AffectedItem(BaseModel):
    """One row of the impact analysis' affected-components table."""

    model_config = ConfigDict(extra="ignore")

    kind: str = Field(
        default="other",
        description="module | function | class | type | document | story | test_case | "
        "test_plan | epic | diagram | requirement | other",
    )
    ref: str = Field(
        default="", description="Id or path, e.g. `existing_Codebase/shared/types.py`."
    )
    change_type: str = Field(default="modify", description="modify | add | remove | verify")
    rationale: str = ""
    kg_ref: str = Field(default="", description="Knowledge-graph node id when known.")


class RequirementImpact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    req_id: str = ""
    requirement: str = ""
    impact: str = ""


class ImpactDoc(BaseModel):
    """Structured impact analysis (LLM draft + engine-added metadata)."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    cr_id: str = ""
    target_workflow: str = ""
    kb_name: str = ""
    status: str = "Draft"
    summary: str = ""
    requirements: list[RequirementImpact] = Field(default_factory=list)
    affected: list[AffectedItem] = Field(default_factory=list)
    design_impacts: list[str] = Field(
        default_factory=list, description="'Component: impact' bullets (BCR §4 style)."
    )
    risks: list[str] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)
    kg_rows: list[ImpactTableRow] = Field(default_factory=list)
    coverage_note: str = ""
    sources: list[SourceRef] = Field(default_factory=list)


class StoryMapRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str = ""
    status: str = "Proposed"
    doc: str = ""


class NfrRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nfr: str = ""
    target: str = ""


class RiskRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    risk: str = ""
    mitigation: str = ""


class EpicDoc(BaseModel):
    """Structured EPIC (reference heading structure of EPIC-001)."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str = ""
    owner: str = ""
    linked_brd: str = ""
    linked_bcr: str = ""
    status: str = "Proposed"
    target_release: str = ""
    statement: str = ""
    value: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    dod: list[str] = Field(default_factory=list, description="Definition of Done items.")
    dod_done: list[bool] = Field(default_factory=list, description="Checked state per DoD item.")
    story_map: list[StoryMapRow] = Field(default_factory=list)
    nfrs: list[NfrRow] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[RiskRow] = Field(default_factory=list)
    coverage_note: str = ""
    sources: list[SourceRef] = Field(default_factory=list)


class StoryDoc(BaseModel):
    """One user story (reference heading structure of US-00N)."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str = ""
    epic: str = ""
    status: str = "Proposed"
    points: int = 0
    as_a: str = ""
    i_want: str = ""
    so_that: str = ""
    acceptance: list[str] = Field(default_factory=list)
    notes: str = ""
    implements: list[str] = Field(default_factory=list)


class StoriesDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")

    epic_id: str = ""
    epic_title: str = ""
    linked_bcr: str = ""
    stories: list[StoryDoc] = Field(default_factory=list)
    coverage_note: str = ""
    sources: list[SourceRef] = Field(default_factory=list)


class TddSection(BaseModel):
    """One numbered TDD section with the existing design and the proposed change."""

    model_config = ConfigDict(extra="ignore")

    key: str = ""
    number: str = ""
    title: str = ""
    existing: str = ""
    proposed: str = ""


class TddDoc(BaseModel):
    """Structured TDD (reference heading structure of TDD-ORD-001)."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str = ""
    linked_epic: str = ""
    supersedes: str = ""
    version: str = "0.1"
    status: str = "Draft"
    author: str = ""
    sections: list[TddSection] = Field(default_factory=list)
    diagrams_needed: list[str] = Field(default_factory=list)
    coverage_note: str = ""
    sources: list[SourceRef] = Field(default_factory=list)


#: TDD section plan: (key, number, title, parent-number-or-None). Sub-sections of
#: "4. Workflow Design" are numbered 4.x; the container itself has no body.
TDD_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("overview", "1", "Overview"),
    ("why_temporal", "2", "Why Temporal"),
    ("architecture", "3", "High-Level Architecture"),
    ("state_machine", "4.1", "State Machine"),
    ("activities", "4.2", "Activities"),
    ("saga", "4.3", "Saga / Compensation Logic"),
    ("idempotency", "4.4", "Idempotency Keys"),
    ("signals_queries", "4.5", "Signals & Queries"),
    ("timeouts", "4.6", "Timeouts & SLAs"),
    ("delivery_wait", "4.7", "Handling Delivery Wait Time"),
    ("data_contracts", "5", "Data Contracts"),
    ("observability", "6", "Observability"),
    ("testing", "7", "Testing Strategy"),
    ("open_items", "8", "Open Items / Future Work"),
)

TDD_CONTAINER_TITLE = "4. Workflow Design"


# --------------------------------------------------------------------------- #
# LLM output schemas — permissive on purpose
# --------------------------------------------------------------------------- #


class DraftedWizardQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str = ""
    why: str = ""
    options: list[SuggestedOption] = Field(default_factory=list)


class DraftedWizardQuestions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    questions: list[DraftedWizardQuestion] = Field(default_factory=list)
    note: str = ""


class AnswerNote(BaseModel):
    """The interpreter's reading of one answer: a brief line, or one follow-up."""

    model_config = ConfigDict(extra="ignore")

    note: str = Field(default="", description="One-line brief statement of the decision.")
    resolved: bool = True
    followup_question: str | None = None
    followup_options: list[SuggestedOption] = Field(default_factory=list)


class ImpactDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    requirements: list[RequirementImpact] = Field(default_factory=list)
    affected: list[AffectedItem] = Field(default_factory=list)
    design_impacts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)


class ImpactCoverageDraft(BaseModel):
    """Second impact pass: traversal candidates the first draft did not mention."""

    model_config = ConfigDict(extra="ignore")

    affected: list[AffectedItem] = Field(default_factory=list)


class EpicDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    epic: EpicDoc = Field(default_factory=EpicDoc)


class StoriesDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stories: list[StoryDoc] = Field(default_factory=list)


class TddSectionDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = ""
    existing: str = ""
    proposed: str = ""


class TddDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sections: list[TddSectionDraft] = Field(default_factory=list)
    diagrams_needed: list[str] = Field(default_factory=list)


class RevisedSection(BaseModel):
    """One top-level (``## ``) section a revision replaces, heading line included."""

    model_config = ConfigDict(extra="ignore")

    heading: str = ""
    markdown: str = ""


class Revision(BaseModel):
    """A chat-driven edit of the current artifact: only the sections that change.

    The engine splices the returned sections into the existing markdown by
    heading and keeps everything else — including the generated appendix and
    ``## Sources`` footer — verbatim, so a revision can never silently shorten
    the document. ``markdown`` is accepted for backwards compatibility (a whole
    replacement) but the engine only uses it when ``sections`` is empty.
    """

    model_config = ConfigDict(extra="ignore")

    sections: list[RevisedSection] = Field(default_factory=list)
    markdown: str = ""
    summary: str = ""

"""Conversational spec-resolution models — questions asked, answers applied.

The spec gate normally asks the user to edit Markdown by hand. A *dialogue
session* is the conversational alternative: the validator's
:class:`~workflow_compiler.models.findings.SpecFinding`s and the spec's own
unresolved open questions are turned into plain-language questions, the user
answers in ordinary prose, and each answer is translated into deterministic
:class:`~workflow_compiler.models.patch.Patch` operations against the spec.

Two families of model live here, and the split is load-bearing:

* **Session state** (:class:`DialogueSession`, :class:`DialogueQuestion`) is
  strict domain data persisted on the project. It records what was asked, what
  was answered, and what each answer changed — an audit trail of the
  conversation, not a transcript to replay.
* **LLM output schemas** (:class:`DraftedQuestions`, :class:`AnswerPlan`) are
  permissive (``extra="ignore"``) for the same reason the review patch models
  are: a slightly-off model response still parses, and the deterministic engine
  does the strict work.

Answers apply **incrementally** — one spec patch set and one version bump per
answered question — so abandoning a session mid-way leaves the answers already
given already applied. Anything the interpreter cannot map to a patch, after
one clarifying follow-up, is *parked* as a new open question rather than
discarded: an answer the system does not understand is still information the
user supplied.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.edit import XrefOp
from workflow_compiler.models.findings import Severity
from workflow_compiler.models.patch import Patch


class QuestionOrigin(StrEnum):
    """Where a dialogue question came from.

    * ``FINDING`` — raised by the spec validator (blocking or warning).
    * ``OPEN_QUESTION`` — an unresolved ``open_questions`` entry on the spec.
    """

    FINDING = "finding"
    OPEN_QUESTION = "open_question"


class QuestionStatus(StrEnum):
    """How a dialogue question was disposed of.

    * ``PENDING`` — not yet reached, or awaiting a clarifying follow-up.
    * ``ANSWERED`` — the answer produced patches that were applied to the spec.
    * ``PARKED`` — the answer could not be mapped to patches; it was recorded as
      a new open question on the spec instead of being dropped.
    * ``SKIPPED`` — the user explicitly passed on it; the spec is unchanged.
    """

    PENDING = "pending"
    ANSWERED = "answered"
    PARKED = "parked"
    SKIPPED = "skipped"


class SuggestedOption(WorkflowBaseModel):
    """One candidate answer the drafting agent proposes alongside a question.

    Options are a shortcut, never a shortlist: the free-text answer box is always
    present and an option is only ever *text the user could have typed*. Picking
    one sends its ``label`` through the same interpretation path as typed prose,
    so there is a single apply path and no stored patch that can go stale.

    They must be **grounded** in the specification or source document — an actor
    that exists, a state the workflow already has, a downstream workflow that was
    really discovered — rather than invented. The gate's whole value is that the
    human is the oracle; plausible-looking invented options quietly move authorship
    back to the model while the result still records as ``HUMAN_PROVIDED``.
    """

    label: str = Field(..., description="The candidate answer, phrased as the user would say it.")
    detail: str = Field(
        default="",
        description="One short clause on what choosing this implies. Empty when self-evident.",
    )


class DialogueQuestion(WorkflowBaseModel):
    """One question put to the user, plus how it was ultimately resolved.

    A question may cover **several** findings at once — the drafting agent is
    allowed to group related ones — so ``covers`` holds every source it speaks
    for. ``followups`` records clarifying questions asked when the first answer
    was too vague to map; the engine allows at most one before parking.
    """

    question_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier for this question within the session.",
    )
    slug: str = Field(..., description="Slug of the workflow this question concerns.")
    text: str = Field(..., description="The question as shown to the user.")
    origin: QuestionOrigin = Field(
        default=QuestionOrigin.FINDING, description="Whether a finding or open question raised it."
    )
    severity: Severity = Field(
        default=Severity.WARNING,
        description="Highest severity among the sources this question covers.",
    )
    section: str | None = Field(
        default=None, description="Spec section the question concerns, e.g. 'Outputs'."
    )
    covers: list[str] = Field(
        default_factory=list,
        description="Source finding messages / open-question texts this question speaks for.",
    )
    options: list[SuggestedOption] = Field(
        default_factory=list,
        description="Candidate answers offered alongside the free-text box. May be empty.",
    )
    status: QuestionStatus = Field(
        default=QuestionStatus.PENDING, description="How the question was resolved."
    )
    answer: str | None = Field(
        default=None, description="The user's prose answer, verbatim."
    )
    chosen_option: str | None = Field(
        default=None,
        description=(
            "Label of the suggested option the user accepted verbatim, when they took "
            "one rather than writing their own. None for typed or edited answers. Kept "
            "so the audit trail distinguishes what the user authored from what they "
            "merely agreed to."
        ),
    )
    followups: list[str] = Field(
        default_factory=list,
        description="Clarifying questions asked when an answer could not be mapped.",
    )
    followup_options: list[SuggestedOption] = Field(
        default_factory=list,
        description=(
            "Candidate answers for the open follow-up. Replaced each time a follow-up "
            "is asked; since at most one is ever asked, that is at most once."
        ),
    )
    changes: list[str] = Field(
        default_factory=list,
        description="Human-readable summary of what applying the answer changed.",
    )
    parked_as: str | None = Field(
        default=None,
        description="Text of the open question this answer became, when parked.",
    )

    @property
    def awaiting_followup(self) -> bool:
        """True when a clarifying follow-up has been asked but not yet answered."""
        return self.status == QuestionStatus.PENDING and bool(self.followups)

    @property
    def prompt(self) -> str:
        """The text actually awaiting an answer — the follow-up if one is open."""
        return self.followups[-1] if self.awaiting_followup else self.text

    @property
    def prompt_options(self) -> list[SuggestedOption]:
        """The options belonging to :attr:`prompt`.

        Mirrors ``prompt`` deliberately: the client is handed the exact text and
        the exact options to show, and never has to work out for itself whether
        it is displaying the question or its follow-up.
        """
        return self.followup_options if self.awaiting_followup else self.options


class DialogueSession(WorkflowBaseModel):
    """An ordered run of questions over one project's specs.

    The question list is a **snapshot** taken when the session starts: answers
    applied mid-session change the specs underneath, but the agenda does not
    move, so the session always terminates. Re-validating after the session
    produces the next round of findings.
    """

    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier for this session.",
    )
    questions: list[DialogueQuestion] = Field(
        default_factory=list, description="The agenda, in the order it is asked."
    )
    cursor: int = Field(
        default=0, ge=0, description="Index of the question currently being asked."
    )
    applied_specs: list[str] = Field(
        default_factory=list,
        description="Slugs whose specs this session has already changed.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When the session started."
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last activity timestamp."
    )

    def touch(self) -> None:
        """Update ``updated_at`` to now."""
        self.updated_at = datetime.now(UTC)

    @property
    def current(self) -> DialogueQuestion | None:
        """The question awaiting an answer, or ``None`` when the agenda is done."""
        if 0 <= self.cursor < len(self.questions):
            return self.questions[self.cursor]
        return None

    @property
    def complete(self) -> bool:
        """True once every question has been dispositioned."""
        return self.cursor >= len(self.questions)

    @property
    def answered_count(self) -> int:
        """How many questions produced applied spec changes."""
        return sum(1 for q in self.questions if q.status == QuestionStatus.ANSWERED)

    def advance(self) -> None:
        """Move to the next question."""
        self.cursor = min(self.cursor + 1, len(self.questions))
        self.touch()


class PreparedAgenda(WorkflowBaseModel):
    """A question agenda drafted ahead of time, waiting for the user to open it.

    Drafting is the slow half of the dialogue — one LLM call per spec, serially,
    before the user sees anything. Doing it in the background when ``validate``
    finishes turns "Start resolving" from a multi-minute wait into an instant one.

    ``fingerprint`` is what makes that safe. It is taken over the exact inputs the
    agenda was drafted from, so an agenda whose specs or findings have moved on is
    detectably stale and is re-drafted rather than shown. Only a *completed* draft
    is ever persisted: an interrupted one leaves nothing behind and simply runs
    again, which is the whole of the crash-recovery story.
    """

    fingerprint: str = Field(
        ..., description="Digest of the findings/specs this agenda was drafted from."
    )
    questions: list[DialogueQuestion] = Field(
        default_factory=list, description="The drafted agenda, in the order it will be asked."
    )
    drafted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When drafting completed."
    )


# --------------------------------------------------------------------------- #
# LLM output schemas — permissive on purpose (see module docstring)
# --------------------------------------------------------------------------- #


class DraftedQuestion(BaseModel):
    """One question the drafting agent proposes, with the sources it covers."""

    model_config = ConfigDict(extra="ignore")

    slug: str = Field(default="", description="Workflow slug the question concerns.")
    question: str = Field(default="", description="Plain-language question for the user.")
    covers: list[str] = Field(
        default_factory=list,
        description="Verbatim finding messages / open-question texts this covers.",
    )
    section: str | None = Field(default=None, description="Spec section concerned.")
    options: list[SuggestedOption] = Field(
        default_factory=list,
        description="Candidate answers grounded in the spec. Empty when none can be.",
    )


class DraftedQuestions(BaseModel):
    """The drafting agent's full agenda for one workflow."""

    model_config = ConfigDict(extra="ignore")

    questions: list[DraftedQuestion] = Field(default_factory=list)
    note: str = Field(default="", description="Optional rationale from the agent.")


class AnswerPlan(BaseModel):
    """The interpreter's reading of one prose answer.

    Exactly one disposition is meaningful at a time, and the engine resolves the
    precedence deterministically: patches win; otherwise a requested follow-up is
    asked (once); otherwise the answer is parked.
    """

    model_config = ConfigDict(extra="ignore")

    patches: list[Patch] = Field(
        default_factory=list, description="Deterministic spec operations the answer implies."
    )
    xref_ops: list[XrefOp] = Field(
        default_factory=list,
        description=(
            "Cross-workflow dependency operations the answer implies. A dependency "
            "belongs to the project rather than to one spec, so it cannot be a Patch; "
            "this is the same typed operation the edit path uses."
        ),
    )
    needs_followup: bool = Field(
        default=False, description="True when the answer is too vague to map as given."
    )
    followup_question: str | None = Field(
        default=None, description="The clarifying question to ask, when needs_followup."
    )
    followup_options: list[SuggestedOption] = Field(
        default_factory=list,
        description="Candidate answers to the clarifying question, when needs_followup.",
    )
    park_note: str | None = Field(
        default=None,
        description="Restatement of the answer to record as an open question when unmappable.",
    )
    note: str = Field(default="", description="Optional rationale from the interpreter.")

    def has_patches(self) -> bool:
        """True when the plan carries at least one effective (non-no-op) patch."""
        return any(not p.is_noop() for p in self.patches)

    def has_effect(self) -> bool:
        """True when the plan asks to change anything at all.

        Patches change a spec; dependency operations change the project. Either
        counts as an answer that acted, and both must be checked before falling
        through to a follow-up or a park.
        """
        return self.has_patches() or bool(self.xref_ops)

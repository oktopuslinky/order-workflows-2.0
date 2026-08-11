"""Free-form spec chat — the user-driven door to the spec gate.

The guided dialogue (:mod:`workflow_compiler.models.dialogue`) works from an
agenda: the validator's findings become questions, and the user answers them.
This is the other direction. The user types whatever they want changed — "add a
refund step after payment clears", "the retry timeout should be 30 seconds" —
and the instruction is translated into the same deterministic
:class:`~workflow_compiler.models.patch.Patch` operations, applied through the
same human-authority applier.

Three differences from the guided dialogue drive the model design:

* **No agenda, so no prerequisite.** ``validate`` need not have run; there is
  nothing to be "done" with, so a session has no cursor and never completes. It
  is a transcript, not a queue.
* **The target workflow is not given.** A question knows which spec it concerns;
  an instruction does not. ``target_slug`` is resolved per turn — from the
  caller, from the workflow under discussion, or by the interpreter — and is
  recorded on the turn so the transcript stays readable.
* **Clarification is per instruction, not per session.** The bound that stops
  the guided dialogue looping is one follow-up per *question*. Here the user is
  driving, so the same bound applies per *instruction*: one clarifying question,
  then the engine acts on what it has or parks it.

As in the guided dialogue, session state is strict domain data and the LLM
output schema (:class:`InstructionPlan`) is permissive — a slightly-off model
response still parses, and the deterministic engine does the strict work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.patch import Patch


class ChatRole(StrEnum):
    """Who produced a transcript turn."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatTurnStatus(StrEnum):
    """What an assistant turn did about the instruction it answers.

    * ``APPLIED`` — the instruction became patches; the spec changed and its
      patch version bumped.
    * ``CLARIFYING`` — the instruction was on-topic but underspecified; one
      clarifying question is now awaiting a reply. The spec is untouched.
    * ``PARKED`` — the instruction could not become a spec change, so it was
      recorded as a new open question rather than discarded.
    * ``NO_CHANGE`` — the instruction was understood but the spec already says
      it. Nothing to do, and saying so is more useful than a silent no-op.
    """

    APPLIED = "applied"
    CLARIFYING = "clarifying"
    PARKED = "parked"
    NO_CHANGE = "no_change"


class SpecChatTurn(WorkflowBaseModel):
    """One turn of the transcript — a user instruction or the reply to it."""

    turn_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier for this turn within the session.",
    )
    role: ChatRole = Field(..., description="Who produced this turn.")
    text: str = Field(..., description="What was said — verbatim for user turns.")
    slug: str | None = Field(
        default=None, description="Workflow this turn concerns, once resolved."
    )
    status: ChatTurnStatus | None = Field(
        default=None, description="Disposition; set on assistant turns only."
    )
    changes: list[str] = Field(
        default_factory=list,
        description="Human-readable summary of what applying the instruction changed.",
    )
    parked_as: str | None = Field(
        default=None, description="Text of the open question this became, when parked."
    )
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal issues from the applier."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When the turn was recorded."
    )


class SpecChatSession(WorkflowBaseModel):
    """An open-ended conversation about one project's specifications.

    Unlike :class:`~workflow_compiler.models.dialogue.DialogueSession` this has
    no cursor and no completion: the user ends it when they are done. What it
    does carry is the *pending clarification* — the instruction the engine asked
    about and is still waiting on — which is what lets the next message be read
    as a reply rather than as a fresh instruction.
    """

    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier for this session.",
    )
    turns: list[SpecChatTurn] = Field(
        default_factory=list, description="The transcript, oldest first."
    )
    pending_instruction: str | None = Field(
        default=None,
        description="The instruction a clarifying question is still waiting on.",
    )
    pending_question: str | None = Field(
        default=None, description="The clarifying question awaiting a reply."
    )
    pending_slug: str | None = Field(
        default=None, description="Workflow the pending instruction concerns, if resolved."
    )
    applied_specs: list[str] = Field(
        default_factory=list, description="Slugs whose specs this session has changed."
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
    def awaiting_clarification(self) -> bool:
        """True when the next message will be read as a reply, not an instruction."""
        return self.pending_question is not None

    @property
    def applied_count(self) -> int:
        """How many instructions produced applied spec changes."""
        return sum(1 for t in self.turns if t.status == ChatTurnStatus.APPLIED)

    def clear_pending(self) -> None:
        """Forget the open clarification, so the next message starts fresh."""
        self.pending_instruction = None
        self.pending_question = None
        self.pending_slug = None

    def record(self, turn: SpecChatTurn) -> SpecChatTurn:
        """Append ``turn`` to the transcript and stamp the session."""
        self.turns.append(turn)
        self.touch()
        return turn

    def recent(self, limit: int = 6) -> list[SpecChatTurn]:
        """The last ``limit`` turns — the context window handed to the model."""
        return self.turns[-limit:] if limit > 0 else []


# --------------------------------------------------------------------------- #
# LLM output schema — permissive on purpose (see module docstring)
# --------------------------------------------------------------------------- #


class InstructionPlan(BaseModel):
    """The interpreter's reading of one free-form instruction.

    Dispositions are resolved deterministically by the engine, in this order:
    patches win; then an explicit "already true" acknowledgement; then a
    clarifying question (once per instruction); otherwise the instruction is
    parked. The model proposes — it never decides.
    """

    model_config = ConfigDict(extra="ignore")

    target_slug: str = Field(
        default="",
        description="Slug of the workflow the instruction concerns; empty when unclear.",
    )
    patches: list[Patch] = Field(
        default_factory=list, description="Deterministic spec operations the instruction implies."
    )
    reply: str = Field(
        default="",
        description="One or two sentences to show the user, in plain language.",
    )
    already_satisfied: bool = Field(
        default=False,
        description="True when the specification already says what was asked for.",
    )
    needs_clarification: bool = Field(
        default=False, description="True when the instruction is too vague to act on."
    )
    clarifying_question: str | None = Field(
        default=None, description="The question to ask, when needs_clarification."
    )
    park_note: str | None = Field(
        default=None,
        description="Restatement to record as an open question when unmappable.",
    )
    note: str = Field(default="", description="Optional rationale from the interpreter.")

    def has_patches(self) -> bool:
        """True when the plan carries at least one effective (non-no-op) patch."""
        return any(not p.is_noop() for p in self.patches)

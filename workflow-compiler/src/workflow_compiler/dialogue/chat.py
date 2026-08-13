"""SpecChatEngine: the deterministic half of free-form spec editing.

The guided dialogue asks the questions; here the user does. The agent proposes
(a target workflow, and a reading of the instruction); this engine disposes. It
owns every decision that must be reproducible:

* **which spec** an instruction lands on — the caller's choice wins, then the
  workflow already under discussion, then a single-spec project, then the
  agent's pick, validated against the project's real slugs;
* **when** an instruction changes the spec (patches present → apply immediately,
  one version bump per instruction, exactly as the guided dialogue does);
* **what happens when it does not** — one clarifying question per instruction,
  then park it as an open question. Never discard, never fail the turn.

Unlike the edit-request path, nothing here is atomic across turns: each
instruction stands alone, so abandoning a chat keeps everything already applied.
Unlike the guided dialogue, there is no agenda and therefore no completion — and
because there is no agenda to preserve, a changed spec's stale
``validation_findings`` are dropped immediately rather than at session end.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from workflow_compiler.agents.spec_chat import SpecChatAgent
from workflow_compiler.dialogue.spec_ops import (
    apply_patches,
    park_as_open_question,
    reset_to_spec_gate,
)
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import CompilationProject, WorkflowSpec
from workflow_compiler.models.dialogue import SuggestedOption
from workflow_compiler.models.spec_chat import (
    ChatRole,
    ChatTurnStatus,
    InstructionPlan,
    SpecChatSession,
    SpecChatTurn,
)
from workflow_compiler.prompts import PromptManager
from workflow_compiler.spec.edit_applier import EditPatchApplier
from workflow_compiler.spec.renderer import render_spec

#: How many prior turns are handed to the interpreter as context. Enough to
#: resolve "and the same for the other one", short enough not to crowd out the
#: specification itself — which is the part the model must read accurately.
_CONTEXT_TURNS = 6


@dataclass
class ChatOutcome:
    """What one instruction did, for the caller to report back to the user."""

    #: The assistant turn appended to the transcript.
    turn: SpecChatTurn
    #: Plain-language reply to show the user.
    reply: str
    #: How the instruction was disposed of.
    status: ChatTurnStatus
    #: Slug of the spec the instruction was read against.
    slug: str | None = None
    #: Human-readable lines describing the spec changes applied.
    changes: list[str] = field(default_factory=list)
    #: Set when the instruction was recorded as a new open question instead.
    parked_as: str | None = None
    #: Non-fatal issues from the applier (e.g. pruned dangling references).
    warnings: list[str] = field(default_factory=list)

    @property
    def applied(self) -> bool:
        """True when the instruction changed the specification."""
        return self.status == ChatTurnStatus.APPLIED


class SpecChatEngine:
    """Run a free-form editing conversation over a project's specs."""

    def __init__(
        self,
        llm_provider: BaseLLMProvider | None = None,
        *,
        agent: SpecChatAgent | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Wire the interpreting agent and the deterministic applier."""
        self._agent = agent or SpecChatAgent(llm_provider, prompt_manager=prompt_manager)
        self._applier = EditPatchApplier()

    # ------------------------------------------------------------------ #
    # Opening
    # ------------------------------------------------------------------ #

    @staticmethod
    def start(project: CompilationProject) -> SpecChatSession:
        """Open a chat session.

        Requires only that the project *has* specs — there is no agenda, so
        unlike the guided dialogue this needs no prior ``validate``.
        """
        if not project.specs:
            raise CompilationError(
                "This project has no specifications to edit yet. Compile it first."
            )
        return SpecChatSession()

    # ------------------------------------------------------------------ #
    # Sending
    # ------------------------------------------------------------------ #

    async def send(
        self,
        project: CompilationProject,
        session: SpecChatSession,
        message: str,
        *,
        slug: str | None = None,
        chosen_option: str | None = None,
    ) -> ChatOutcome:
        """Read one ``message`` and act on it.

        Mutates ``project`` and ``session`` in place (the caller persists). An
        unrecognised ``slug`` is an error rather than a silent fallback — the
        alternative is patching a specification the user was not looking at.

        ``chosen_option`` names a suggested reply the user accepted verbatim.
        It is recorded, not trusted: the text is interpreted exactly as typed
        prose would be, and a label that was not actually offered is dropped
        rather than stored.
        """
        text = message.strip()
        if not text:
            raise CompilationError("A message cannot be empty.")

        spec = self._resolve_spec(project, session, slug)
        offered = {o.label for o in session.pending_options}
        session.record(
            SpecChatTurn(
                role=ChatRole.USER,
                text=text,
                slug=spec.slug,
                chosen_option=chosen_option if chosen_option in offered else None,
            )
        )

        pending_instruction = session.pending_instruction
        pending_question = session.pending_question
        plan = await self._agent.interpret_instruction(
            instruction=text,
            target_slug=spec.slug,
            slugs=[s.slug for s in project.specs],
            current_spec=render_spec(spec, project.cross_references, project.triggers),
            # The turn just recorded is the instruction itself; it is passed
            # separately, so it is excluded from the context window.
            transcript=session.recent(_CONTEXT_TURNS + 1)[:-1],
            pending_instruction=pending_instruction,
            pending_question=pending_question,
        )
        # A reply to a clarification is only meaningful alongside the question
        # it answers; once interpreted, the pair is spent either way.
        session.clear_pending()

        retargeted = self._retarget(project, plan, spec)
        if retargeted is not None:
            spec = retargeted

        full_instruction = (
            f"{pending_instruction} — {text}" if pending_instruction else text
        )
        return self._dispose(
            project,
            session,
            spec,
            plan,
            full_instruction,
            after_clarification=pending_question is not None,
        )

    def _resolve_spec(
        self,
        project: CompilationProject,
        session: SpecChatSession,
        slug: str | None,
    ) -> WorkflowSpec:
        """Pick the spec this message is about, most specific source first."""
        if not project.specs:
            raise CompilationError(
                "This project has no specifications to edit yet. Compile it first."
            )
        for candidate in (slug, session.pending_slug):
            if not candidate:
                continue
            spec = project.spec_for(candidate)
            if spec is not None:
                return spec
            if candidate == slug:
                known = ", ".join(s.slug for s in project.specs)
                raise CompilationError(
                    f"No workflow '{candidate}' in this project. Available: {known}."
                )
        return project.specs[0]

    @staticmethod
    def _retarget(
        project: CompilationProject, plan: InstructionPlan, current: WorkflowSpec
    ) -> WorkflowSpec | None:
        """Honour the agent's ``target_slug`` when it names a real other spec.

        Only ever *narrows* to a workflow that exists. A hallucinated slug is
        ignored and the instruction stays on the spec the user was looking at —
        patching some other specification because the model invented a name is
        strictly worse than reading the intended one.
        """
        proposed = (plan.target_slug or "").strip()
        if not proposed or proposed == current.slug:
            return None
        return project.spec_for(proposed)

    # ------------------------------------------------------------------ #
    # Disposing
    # ------------------------------------------------------------------ #

    def _dispose(
        self,
        project: CompilationProject,
        session: SpecChatSession,
        spec: WorkflowSpec,
        plan: InstructionPlan,
        instruction: str,
        *,
        after_clarification: bool = False,
    ) -> ChatOutcome:
        """Resolve one interpreted instruction: apply, acknowledge, ask, or park.

        Precedence is fixed and deliberate — real patches beat every other
        signal, so a model that sets both ``patches`` and ``needs_clarification``
        still does the useful thing.
        """
        if plan.has_patches():
            return self._apply(project, session, spec, plan)

        if plan.already_satisfied:
            return self._settle(
                session,
                spec,
                ChatTurnStatus.NO_CHANGE,
                plan.reply or "That is already what the specification says — nothing to change.",
            )

        if plan.needs_clarification:
            question = (plan.clarifying_question or "").strip()
            if question:
                options = [o for o in plan.clarifying_options if o.label.strip()]
                session.pending_instruction = instruction
                session.pending_question = question
                session.pending_slug = spec.slug
                session.pending_options = options
                return self._settle(
                    session, spec, ChatTurnStatus.CLARIFYING, question, options=options
                )

        return self._park(
            project, session, spec, plan, instruction,
            after_clarification=after_clarification,
        )

    def _apply(
        self,
        project: CompilationProject,
        session: SpecChatSession,
        spec: WorkflowSpec,
        plan: InstructionPlan,
    ) -> ChatOutcome:
        """Fold the instruction's patches into the spec and bump its version."""
        _, summary, warnings = apply_patches(project, spec, plan.patches, self._applier)
        self._mark_dirty(project, session, spec.slug)
        reply = plan.reply.strip() or "Applied that to the specification."
        return self._settle(
            session,
            spec,
            ChatTurnStatus.APPLIED,
            reply,
            changes=summary,
            warnings=warnings,
        )

    def _park(
        self,
        project: CompilationProject,
        session: SpecChatSession,
        spec: WorkflowSpec,
        plan: InstructionPlan,
        instruction: str,
        *,
        after_clarification: bool = False,
    ) -> ChatOutcome:
        """Record an unmappable instruction as a new open question on the spec."""
        note = (plan.park_note or "").strip() or instruction
        park_as_open_question(project, spec, note, ref=f"chat:{session.session_id}")
        self._mark_dirty(project, session, spec.slug)
        default = (
            "I could not turn that into a specification change, so I have recorded it "
            "as an open question."
        )
        # The engine owns the disposition, so it owns the sentence describing it.
        # A model denied a second clarification writes its question into `reply`
        # anyway, which would tell the user to "please specify…" at the very
        # moment their answer was parked. Observed live on the cloud provider,
        # not hypothetical. Note the agent has already cleared
        # `needs_clarification` by this point, so the pending flag is the only
        # remaining signal that the model was still trying to ask.
        reply = default if after_clarification else (plan.reply.strip() or default)
        return self._settle(
            session, spec, ChatTurnStatus.PARKED, reply, parked_as=note
        )

    @staticmethod
    def _settle(
        session: SpecChatSession,
        spec: WorkflowSpec,
        status: ChatTurnStatus,
        reply: str,
        *,
        changes: list[str] | None = None,
        parked_as: str | None = None,
        warnings: list[str] | None = None,
        options: list[SuggestedOption] | None = None,
    ) -> ChatOutcome:
        """Append the assistant turn and package the outcome."""
        turn = session.record(
            SpecChatTurn(
                role=ChatRole.ASSISTANT,
                text=reply,
                slug=spec.slug,
                status=status,
                changes=changes or [],
                parked_as=parked_as,
                warnings=warnings or [],
                options=options or [],
            )
        )
        return ChatOutcome(
            turn=turn,
            reply=reply,
            status=status,
            slug=spec.slug,
            changes=changes or [],
            parked_as=parked_as,
            warnings=warnings or [],
        )

    # ------------------------------------------------------------------ #
    # Project bookkeeping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _mark_dirty(
        project: CompilationProject, session: SpecChatSession, slug: str
    ) -> None:
        """Record that a spec changed and return the project to the spec gate.

        The changed spec's ``validation_findings`` are dropped **immediately**,
        which is where this differs from the guided dialogue: there, findings are
        the agenda and clearing them mid-session would erase the context of
        questions still to be asked. A chat has no agenda, so stale findings have
        no remaining use and keeping them would only invite approving against a
        validation that no longer describes the spec.
        """
        if slug not in session.applied_specs:
            session.applied_specs.append(slug)
        project.validation_findings.pop(slug, None)
        reset_to_spec_gate(project)
        session.touch()

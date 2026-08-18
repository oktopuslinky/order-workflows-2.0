"""TemporalGeneratorAgent: design a Temporal blueprint from graph + CVPA.

Produces **architecture specifications only** — names, descriptions, and
parameters for the workflow, its activities, signals, queries, child workflows,
timers, retries, and compensation activities. It deliberately emits no
executable Temporal SDK code.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.agents.serialization import cvpa_to_text, facts_to_text, graph_to_text
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    BindingSource,
    CompilationStage,
    ConfidenceScores,
    InputBinding,
    NodeType,
    RetryPolicyDesign,
    StepKind,
    TemporalActivityDesign,
    TemporalChildWorkflowDesign,
    TemporalCompensationDesign,
    TemporalParam,
    TemporalQueryDesign,
    TemporalSignalDesign,
    TemporalStep,
    TemporalTimerDesign,
    TemporalTriggerDesign,
    TemporalWorkflowDesign,
    TriggerMode,
    WorkflowGraph,
    WorkflowState,
    WorkflowStructure,
    WorkflowTrigger,
    pair_gate_timer,
)
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "design_temporal"
_SYSTEM = (
    "You are a Temporal solutions architect. Produce ARCHITECTURE SPECIFICATIONS "
    "ONLY (names, descriptions, parameters) as strict JSON. Never emit executable "
    "Temporal code, SDK calls, or language snippets."
)

#: A leading ``[evN]`` provenance tag on event node labels.
_EVENT_PREFIX = re.compile(r"^\s*\[[^\]]*\]\s*")
#: Words that describe an event's *direction*, not its identity.
_EVENT_STOP_TOKENS = frozenset(
    {"emitted", "emit", "emits", "event", "signal", "received", "receive", "produced"}
)


def _event_tokens(text: str) -> set[str]:
    """Identity tokens of an event/signal name (prefix + direction words removed).

    Splits camelCase and delimiters so ``OrderIdEmitted``, ``order_id_emitted``,
    and ``[ev1] order_id emitted`` all reduce to ``{order}``.
    """
    core = _EVENT_PREFIX.sub("", text or "")
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", core)
    return {
        t for t in re.findall(r"[a-z0-9]+", spaced.lower()) if len(t) > 2
    } - _EVENT_STOP_TOKENS


def _squash_name(name: str | None) -> str:
    """Lowercase alphanumeric squash for casing/word-boundary-insensitive matching."""
    return "".join(re.findall(r"[a-z0-9]+", (name or "").lower()))


def _walk_steps(steps: list[TemporalStep]):  # type: ignore[no-untyped-def]
    """Yield every step in ``steps``, descending into nested ``lanes``."""
    for step in steps:
        yield step
        for lane in step.lanes:
            yield from _walk_steps(lane)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _slug(text: str, *, fallback: str) -> str:
    """Make a PascalCase identifier from free text, or use ``fallback``.

    Word boundaries are preserved — including existing camelCase/PascalCase humps
    — so ``"ValidateRequestPayload"`` stays ``"ValidateRequestPayload"`` (and
    snake-cases cleanly to ``validate_request_payload``) instead of collapsing to
    a single word. This must agree with the code generator's ``_pascal`` so a
    declared activity name and a plan-step ref render to the *same* identifier.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    words = "".join(c if c.isalnum() else " " for c in spaced).split()
    return "".join(word[:1].upper() + word[1:] for word in words) or fallback


# --- Permissive LLM output schemas -----------------------------------------


class _RetryOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    maximum_attempts: int = Field(default=3)
    initial_interval_seconds: float = Field(default=1.0)
    backoff_coefficient: float = Field(default=2.0)
    maximum_interval_seconds: float | None = Field(default=None)
    non_retryable_error_types: list[str] = Field(default_factory=list)


class _ParamOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    type: str = Field(default="str")


class _ActivityOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    source_node_id: str | None = Field(default=None)
    description: str = Field(default="")
    inputs: list[str] = Field(default_factory=list)
    params: list[_ParamOut] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    result_type: str = Field(default="str")
    timeout_seconds: float | None = Field(default=None)
    retry_policy: _RetryOut | None = Field(default=None)


class _BindingOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    param: str = Field(default="")
    source: str = Field(default="constant")
    ref: str | None = Field(default=None)


class _StepOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="")
    kind: str = Field(default="activity")
    description: str = Field(default="")
    ref: str | None = Field(default=None)
    bindings: list[_BindingOut] = Field(default_factory=list)
    result_name: str | None = Field(default=None)
    signal: str | None = Field(default=None)
    condition: str | None = Field(default=None)
    timer: str | None = Field(default=None)
    predicate: str | None = Field(default=None)
    lanes: list[list[_StepOut]] = Field(default_factory=list)


class _SignalOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    description: str = Field(default="")
    payload: list[str] = Field(default_factory=list)


class _QueryOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    description: str = Field(default="")
    returns: str | None = Field(default=None)
    state_field: str | None = Field(default=None)


class _ChildOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    source_node_id: str | None = Field(default=None)
    description: str = Field(default="")
    inputs: list[str] = Field(default_factory=list)
    params: list[_ParamOut] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    task_queue: str | None = Field(default=None)


class _TimerOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    duration_seconds: float = Field(default=0.0)
    description: str = Field(default="")


class _CompensationOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    compensates: str | None = Field(default=None)
    source_node_id: str | None = Field(default=None)
    description: str = Field(default="")
    inputs: list[str] = Field(default_factory=list)
    params: list[_ParamOut] = Field(default_factory=list)
    bindings: list[_BindingOut] = Field(default_factory=list)
    retry_policy: _RetryOut | None = Field(default=None)


class TemporalDesignOutput(BaseModel):
    """Structured LLM output for a Temporal workflow blueprint."""

    model_config = ConfigDict(extra="ignore")

    workflow_name: str = Field(default="")
    task_queue: str | None = Field(default=None)
    description: str = Field(default="")
    workflow_inputs: list[_ParamOut] = Field(default_factory=list)
    result_type: str = Field(default="str")
    activities: list[_ActivityOut] = Field(default_factory=list)
    signals: list[_SignalOut] = Field(default_factory=list)
    queries: list[_QueryOut] = Field(default_factory=list)
    child_workflows: list[_ChildOut] = Field(default_factory=list)
    timers: list[_TimerOut] = Field(default_factory=list)
    compensation_activities: list[_CompensationOut] = Field(default_factory=list)
    default_retry_policy: _RetryOut | None = Field(default=None)
    plan: list[_StepOut] = Field(default_factory=list)
    confidence: float = Field(default=0.5)


# ``_StepOut.lanes`` is self-referential; resolve the forward reference.
_StepOut.model_rebuild()


class TemporalGeneratorAgent(BaseAgent):
    """Generate a :class:`TemporalWorkflowDesign` from graph + CVPA classification.

    Depends only on :class:`BaseLLMProvider`. Output is normalized into the
    canonical design models; invalid or empty entries are dropped.
    """

    name = "temporal-generator"

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Store the LLM provider and an optional prompt manager."""
        super().__init__(llm)
        self._prompts = prompt_manager or PromptManager()

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Design the Temporal blueprint and update ``state`` in place."""
        if self._llm is None:
            raise CompilationError("TemporalGeneratorAgent requires an LLM provider.")
        if state.workflow_graph is None:
            raise CompilationError("TemporalGeneratorAgent requires a built workflow_graph.")
        if state.cvpa_classification is None:
            raise CompilationError("TemporalGeneratorAgent requires a cvpa_classification.")

        facts_text = (
            facts_to_text(state.workflow_facts)
            if state.workflow_facts is not None
            else "(no detailed facts extracted)"
        )
        prompt = self._prompts.render(
            _PROMPT_NAME,
            workflow_graph=graph_to_text(state.workflow_graph),
            workflow_facts=facts_text,
            cvpa_classification=cvpa_to_text(state.cvpa_classification),
            kg_context=state.kg_context or "",
        )
        result = await self._llm.structured(prompt, TemporalDesignOutput, system=_SYSTEM)

        design = self._to_design(result, state)
        if state.outgoing_triggers:
            design = self._inject_triggers(design, state.outgoing_triggers)
        confidence = self._score(result, design)

        state.temporal_design = design
        scores = state.confidence_scores or ConfidenceScores()
        notes = {
            **scores.notes,
            "temporal": (
                f"{len(design.activities)} activities, {len(design.signals)} signals, "
                f"{len(design.child_workflows)} child workflows, "
                f"{len(design.compensation_activities)} compensations."
            ),
        }
        state.confidence_scores = scores.model_copy(
            update={"temporal": confidence, "notes": notes}
        )
        state.stage = CompilationStage.TEMPORAL_DESIGNED
        state.touch()
        return state

    # -- internals ----------------------------------------------------------

    def _to_design(
        self, result: TemporalDesignOutput, state: WorkflowState
    ) -> TemporalWorkflowDesign:
        """Normalize the LLM output into a validated TemporalWorkflowDesign."""
        meta_name = state.workflow_metadata.name if state.workflow_metadata else "Workflow"
        workflow_name = _slug(result.workflow_name, fallback=_slug(meta_name, fallback="Workflow"))
        task_queue = (result.task_queue or "").strip() or f"{workflow_name}-task-queue"
        description = result.description.strip() or (
            state.workflow_metadata.purpose if state.workflow_metadata else None
        )

        design = TemporalWorkflowDesign(
            workflow_name=workflow_name,
            task_queue=task_queue,
            description=description,
            workflow_inputs=self._params(result.workflow_inputs),
            result_type=(result.result_type or "str").strip() or "str",
            activities=self._activities(result.activities),
            signals=self._signals(result.signals),
            queries=self._queries(result.queries),
            child_workflows=self._children(result.child_workflows),
            timers=self._timers(result.timers),
            compensation_activities=self._compensations(result.compensation_activities),
            default_retry_policy=self._retry(result.default_retry_policy),
            plan=self._plan(result.plan),
        )
        if state.workflow_graph is not None:
            design = self._prune_ungrounded_signal_gates(design, state.workflow_graph)
        design = self._prune_misplaced_raises(design)
        structure = (
            state.workflow_facts.structure if state.workflow_facts is not None else None
        )
        if structure is not None:
            design = self._terminate_rejection_lanes(design, structure)
        return design

    @staticmethod
    def _prune_misplaced_raises(design: TemporalWorkflowDesign) -> TemporalWorkflowDesign:
        """Drop RAISE steps anywhere except a branch's else-lane.

        A raise on the unconditional path (or in a then-lane, which the prompt
        defines as the success path) would fail **every** run — the LLM
        sometimes appends its rejection raises after the branch instead of
        inside the else-lane. Only the else-lane position is meaningful; the
        deterministic rejection-lane pass re-injects a raise there when the
        spec calls for one.
        """
        dropped = False

        def prune(steps: list[TemporalStep], *, allow_raise: bool) -> list[TemporalStep]:
            nonlocal dropped
            kept: list[TemporalStep] = []
            for step in steps:
                if step.lanes:
                    if step.kind is StepKind.BRANCH:
                        lanes = [
                            prune(lane, allow_raise=(index == 1))
                            for index, lane in enumerate(step.lanes)
                        ]
                    else:
                        lanes = [prune(lane, allow_raise=False) for lane in step.lanes]
                    step = step.model_copy(update={"lanes": lanes})
                if step.kind is StepKind.RAISE and not allow_raise:
                    dropped = True
                    continue
                kept.append(step)
            return kept

        new_plan = prune(design.plan, allow_raise=False)
        return design.model_copy(update={"plan": new_plan}) if dropped else design

    # -- deterministic rejection-lane termination -----------------------------

    @staticmethod
    def _terminate_rejection_lanes(
        design: TemporalWorkflowDesign, structure: WorkflowStructure
    ) -> TemporalWorkflowDesign:
        """Fill a branch's empty else-lane with a RAISE when the spec rejects.

        The design LLM frequently leaves a decision's "no" lane empty, so the
        generated code falls through and reports a rejected run as completed.
        The approved spec knows better: a decision whose ``no_target`` is an
        exception terminates the workflow. This pass folds that in
        deterministically, under a conservative match so it can never fire on a
        legitimately-optional branch:

        - the BRANCH step must immediately follow an ACTIVITY step in the same
          lane, and that activity must be the decision's ``after`` anchor
          (matched by squashed name);
        - the decision's ``no_target`` must resolve to a declared exception;
        - the branch's then-lane must be non-empty and its else-lane empty.

        Anything else (negatively-phrased branches, optional blocks, unmatched
        anchors) is left untouched.
        """
        activity_name_by_id = {a.id: _squash_name(a.name) for a in structure.activities}
        exception_by_id = {x.id: x for x in structure.exceptions}
        decision_by_anchor: dict[str, str] = {}
        for d in structure.decisions:
            exc = exception_by_id.get(d.no_target or "")
            anchor = activity_name_by_id.get(d.after or "")
            if exc is not None and anchor:
                decision_by_anchor[anchor] = exc.reason

        if not decision_by_anchor:
            return design

        def rewrite(steps: list[TemporalStep]) -> list[TemporalStep]:
            out: list[TemporalStep] = []
            previous_activity_ref: str | None = None
            for step in steps:
                if step.lanes:
                    step = step.model_copy(
                        update={"lanes": [rewrite(lane) for lane in step.lanes]}
                    )
                if (
                    step.kind is StepKind.BRANCH
                    and previous_activity_ref is not None
                    and previous_activity_ref in decision_by_anchor
                    and len(step.lanes) >= 1
                    and step.lanes[0]
                    and (len(step.lanes) < 2 or not step.lanes[1])
                ):
                    reason = decision_by_anchor[previous_activity_ref]
                    raise_step = TemporalStep(
                        id=f"raise_{_squash_name(reason) or 'rejected'}",
                        kind=StepKind.RAISE,
                        ref=reason,
                        description=f"Rejection path from the spec: raises {reason}.",
                    )
                    lanes = [step.lanes[0], [raise_step]]
                    step = step.model_copy(update={"lanes": lanes})
                previous_activity_ref = (
                    _squash_name(step.ref)
                    if step.kind is StepKind.ACTIVITY and step.ref
                    else None
                )
                out.append(step)
            return out

        return design.model_copy(update={"plan": rewrite(design.plan)})

    # -- deterministic cross-workflow trigger injection ----------------------

    @staticmethod
    def _inject_triggers(
        design: TemporalWorkflowDesign, triggers: list[WorkflowTrigger]
    ) -> TemporalWorkflowDesign:
        """Fold the workflow's confirmed cross-workflow triggers into the design.

        Deterministic (never LLM-designed): the triggers come from the
        human-approved spec. Each becomes a :class:`TemporalTriggerDesign`
        declaration plus a plan step — conditional triggers wrapped in a
        ``BRANCH`` whose then-lane holds the ``TRIGGER`` step, reusing the
        existing branch machinery. When the LLM emitted no plan, the appended
        steps leave it trigger-only; the code generator recognizes that and
        synthesizes the activity spine in front of them.
        """
        declarations = list(design.triggers)
        steps: list[TemporalStep] = []
        for index, trigger in enumerate(triggers, start=1):
            target_name = _slug(trigger.target_workflow, fallback="Target")
            name = f"Start{target_name}"
            declarations.append(
                TemporalTriggerDesign(
                    name=name,
                    target_workflow_name=target_name,
                    target_slug=trigger.target_workflow,
                    target_task_queue=f"{target_name}-task-queue",
                    mode=trigger.mode.value,
                    params=[
                        TemporalParam(name=b.target_input, type=b.type or "str")
                        for b in trigger.input_map
                    ],
                    description=(
                        f"Fires when {trigger.condition}" if trigger.condition else None
                    ),
                )
            )
            step = TemporalStep(
                id=f"trigger_{index}",
                kind=StepKind.TRIGGER,
                ref=name,
                description=f"Start the standalone '{trigger.target_workflow}' workflow",
                bindings=[
                    InputBinding(param=b.target_input, source=b.source, ref=b.source_ref)
                    for b in trigger.input_map
                ],
                result_name=(
                    trigger.result_binding
                    if trigger.mode is TriggerMode.BLOCKING
                    else None
                ),
            )
            if trigger.condition:
                step = TemporalStep(
                    id=f"branch_trigger_{index}",
                    kind=StepKind.BRANCH,
                    predicate=trigger.condition,
                    lanes=[[step], []],
                )
            steps.append(step)
        return design.model_copy(
            update={"triggers": declarations, "plan": [*design.plan, *steps]}
        )

    # -- Stage A/B: deterministic gate guard --------------------------------

    def _prune_ungrounded_signal_gates(
        self, design: TemporalWorkflowDesign, graph: WorkflowGraph
    ) -> TemporalWorkflowDesign:
        """Drop ``signal_gate`` steps not backed by a genuine inbound wait.

        A ``signal_gate`` is legitimate only for an event the workflow *receives
        and waits on* — a ``SIGNAL`` node in the graph (a ``signal_wait`` event).
        When the design LLM instead makes a gate for a value the workflow
        **produces** (an output-emit) or for its **trigger**, the generated
        ``wait_condition`` blocks on a signal that never arrives — the workflow
        hangs forever. This deterministic guard removes any **unbounded** gate
        whose signal matches no wait node (and drops the orphaned signal
        declaration). Bounded gates (paired with a timer) are always kept — they
        time out rather than hang — so a genuine wait is never lost. Mirrors the
        design prompt's rule; guarantees "never hang" even if the LLM slips.
        """
        wait_tokens = self._wait_signal_tokens(graph)

        def is_ungrounded_gate(step: TemporalStep) -> bool:
            if step.kind is not StepKind.SIGNAL_GATE or not step.signal:
                return False
            if pair_gate_timer(step.timer, step.signal, design.timers) is not None:
                return False  # bounded — will time out, cannot hang
            sig_tokens = _event_tokens(step.signal)
            if not sig_tokens:
                return False
            # Grounded iff it matches a real wait node's identity tokens.
            return not any(w and w <= sig_tokens for w in wait_tokens)

        dropped: list[str] = []

        def filter_steps(steps: list[TemporalStep]) -> list[TemporalStep]:
            kept: list[TemporalStep] = []
            for step in steps:
                if is_ungrounded_gate(step):
                    dropped.append(step.signal or "")
                    continue
                if step.lanes:
                    step = step.model_copy(
                        update={"lanes": [filter_steps(lane) for lane in step.lanes]}
                    )
                kept.append(step)
            return kept

        new_plan = filter_steps(design.plan)
        if not dropped:
            return design

        still_used = {
            _squash_name(step.signal)
            for step in _walk_steps(new_plan)
            if step.kind is StepKind.SIGNAL_GATE and step.signal
        }
        dropped_norm = {_squash_name(name) for name in dropped}
        new_signals = [
            sig
            for sig in design.signals
            if _squash_name(sig.name) in still_used
            or _squash_name(sig.name) not in dropped_norm
        ]
        return design.model_copy(update={"plan": new_plan, "signals": new_signals})

    @staticmethod
    def _wait_signal_tokens(graph: WorkflowGraph) -> list[set[str]]:
        """Identity token sets of genuine inbound-wait nodes (``NodeType.SIGNAL``)."""
        out: list[set[str]] = []
        for node in graph.nodes:
            if node.node_type is NodeType.SIGNAL:
                tokens = _event_tokens(node.label)
                if tokens:
                    out.append(tokens)
        return out

    @staticmethod
    def _params(items: list[_ParamOut]) -> list[TemporalParam]:
        out: list[TemporalParam] = []
        for item in items:
            name = item.name.strip()
            if not name:
                continue
            out.append(TemporalParam(name=name, type=(item.type or "str").strip() or "str"))
        return out

    def _bindings(self, items: list[_BindingOut]) -> list[InputBinding]:
        out: list[InputBinding] = []
        valid = {s.value for s in BindingSource}
        for item in items:
            param = item.param.strip()
            if not param:
                continue
            source = item.source.strip().lower()
            if source not in valid:
                source = BindingSource.CONSTANT.value
            out.append(
                InputBinding(
                    param=param,
                    source=BindingSource(source),
                    ref=(item.ref or "").strip() or None,
                )
            )
        return out

    def _plan(self, items: list[_StepOut]) -> list[TemporalStep]:
        out: list[TemporalStep] = []
        valid = {k.value for k in StepKind}
        for index, item in enumerate(items):
            kind = item.kind.strip().lower()
            if kind not in valid:
                continue
            step_id = item.id.strip() or f"step_{index}"
            out.append(
                TemporalStep(
                    id=step_id,
                    kind=StepKind(kind),
                    description=item.description.strip() or None,
                    ref=(item.ref or "").strip() or None,
                    bindings=self._bindings(item.bindings),
                    result_name=(item.result_name or "").strip() or None,
                    signal=(item.signal or "").strip() or None,
                    condition=(item.condition or "").strip() or None,
                    timer=(item.timer or "").strip() or None,
                    predicate=(item.predicate or "").strip() or None,
                    lanes=[self._plan(lane) for lane in item.lanes],
                )
            )
        return out

    def _retry(self, out: _RetryOut | None) -> RetryPolicyDesign | None:
        """Convert a permissive retry payload to a validated policy."""
        if out is None:
            return None
        return RetryPolicyDesign(
            maximum_attempts=max(0, out.maximum_attempts),
            initial_interval_seconds=max(0.001, out.initial_interval_seconds),
            backoff_coefficient=max(1.0, out.backoff_coefficient),
            maximum_interval_seconds=out.maximum_interval_seconds,
            non_retryable_error_types=[
                s.strip() for s in out.non_retryable_error_types if s.strip()
            ],
        )

    def _activities(self, items: list[_ActivityOut]) -> list[TemporalActivityDesign]:
        designs: list[TemporalActivityDesign] = []
        for item in items:
            name = _slug(item.name, fallback="")
            if not name:
                continue
            designs.append(
                TemporalActivityDesign(
                    name=name,
                    source_node_id=item.source_node_id,
                    description=item.description.strip() or None,
                    inputs=[s.strip() for s in item.inputs if s.strip()],
                    params=self._params(item.params),
                    outputs=[s.strip() for s in item.outputs if s.strip()],
                    result_type=(item.result_type or "str").strip() or "str",
                    timeout_seconds=item.timeout_seconds,
                    retry_policy=self._retry(item.retry_policy),
                )
            )
        return designs

    @staticmethod
    def _signals(items: list[_SignalOut]) -> list[TemporalSignalDesign]:
        designs: list[TemporalSignalDesign] = []
        for item in items:
            name = item.name.strip()
            if not name:
                continue
            designs.append(
                TemporalSignalDesign(
                    name=name,
                    description=item.description.strip() or None,
                    payload=[s.strip() for s in item.payload if s.strip()],
                )
            )
        return designs

    @staticmethod
    def _queries(items: list[_QueryOut]) -> list[TemporalQueryDesign]:
        designs: list[TemporalQueryDesign] = []
        for item in items:
            name = item.name.strip()
            if not name:
                continue
            designs.append(
                TemporalQueryDesign(
                    name=name,
                    description=item.description.strip() or None,
                    returns=(item.returns or "").strip() or None,
                    state_field=(item.state_field or "").strip() or None,
                )
            )
        return designs

    def _children(self, items: list[_ChildOut]) -> list[TemporalChildWorkflowDesign]:
        designs: list[TemporalChildWorkflowDesign] = []
        for item in items:
            name = _slug(item.name, fallback="")
            if not name:
                continue
            designs.append(
                TemporalChildWorkflowDesign(
                    name=name,
                    source_node_id=item.source_node_id,
                    description=item.description.strip() or None,
                    inputs=[s.strip() for s in item.inputs if s.strip()],
                    params=self._params(item.params),
                    outputs=[s.strip() for s in item.outputs if s.strip()],
                    task_queue=(item.task_queue or "").strip() or None,
                )
            )
        return designs

    @staticmethod
    def _timers(items: list[_TimerOut]) -> list[TemporalTimerDesign]:
        designs: list[TemporalTimerDesign] = []
        for item in items:
            name = item.name.strip()
            if not name or item.duration_seconds <= 0:
                continue
            designs.append(
                TemporalTimerDesign(
                    name=name,
                    duration_seconds=item.duration_seconds,
                    description=item.description.strip() or None,
                )
            )
        return designs

    def _compensations(self, items: list[_CompensationOut]) -> list[TemporalCompensationDesign]:
        designs: list[TemporalCompensationDesign] = []
        for item in items:
            name = _slug(item.name, fallback="")
            if not name:
                continue
            designs.append(
                TemporalCompensationDesign(
                    name=name,
                    compensates=(item.compensates or "").strip() or None,
                    source_node_id=item.source_node_id,
                    description=item.description.strip() or None,
                    inputs=[s.strip() for s in item.inputs if s.strip()],
                    params=self._params(item.params),
                    bindings=self._bindings(item.bindings),
                    retry_policy=self._retry(item.retry_policy),
                )
            )
        return designs

    @staticmethod
    def _score(result: TemporalDesignOutput, design: TemporalWorkflowDesign) -> float:
        """Blend self-reported confidence with design completeness."""
        signals = [
            bool(design.activities),
            bool(design.signals or design.queries),
            bool(design.child_workflows or design.timers),
            bool(design.compensation_activities),
            design.default_retry_policy is not None,
        ]
        completeness = sum(signals) / len(signals)
        self_reported = _clamp(result.confidence)
        return round(_clamp(0.5 * self_reported + 0.5 * completeness), 4)

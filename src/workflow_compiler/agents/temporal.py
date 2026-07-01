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
    TemporalWorkflowDesign,
    WorkflowState,
)
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "design_temporal"
_SYSTEM = (
    "You are a Temporal solutions architect. Produce ARCHITECTURE SPECIFICATIONS "
    "ONLY (names, descriptions, parameters) as strict JSON. Never emit executable "
    "Temporal code, SDK calls, or language snippets."
)


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
        )
        result = await self._llm.structured(prompt, TemporalDesignOutput, system=_SYSTEM)

        design = self._to_design(result, state)
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

        return TemporalWorkflowDesign(
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

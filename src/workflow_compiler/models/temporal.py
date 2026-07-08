"""Temporal workflow design models.

These describe a Temporal (temporal.io) workflow blueprint derived from the
canonical workflow graph: activities, signals, queries, timers, and retry
policies. They are design artifacts, not executable Temporal definitions.

The blueprint has two layers:

* **Declarations** — the activities, signals, queries, child workflows, timers,
  and compensation activities that exist in the workflow (the "vocabulary").
* **Plan (IR)** — an ordered, typed control-and-data-flow graph of
  :class:`TemporalStep` nodes (the "categories of actions": activity calls,
  signal gates, timers, parallel groups, branches, child workflows) that wires
  the declarations together with explicit input bindings. The deterministic code
  generator walks this plan to emit runnable code; when the plan is empty it
  synthesizes a linear plan from the declarations + graph order for backward
  compatibility.

The LLM never writes code — it fills this specification; templates emit code.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class StepKind(StrEnum):
    """The category of an action in the workflow plan (IR)."""

    ACTIVITY = "activity"
    CHILD_WORKFLOW = "child_workflow"
    SIGNAL_GATE = "signal_gate"
    TIMER = "timer"
    PARALLEL = "parallel"
    BRANCH = "branch"


class BindingSource(StrEnum):
    """Where a single activity input value is sourced from."""

    WORKFLOW_INPUT = "workflow_input"  # a field on the top-level WorkflowInput
    STEP_OUTPUT = "step_output"  # the result of an earlier step
    CONSTANT = "constant"  # a literal default (left as ``""`` / TODO)


class RetryPolicyDesign(WorkflowBaseModel):
    """Design-time retry policy for a Temporal activity."""

    maximum_attempts: int = Field(default=3, ge=0, description="Max attempts; 0 means unlimited.")
    initial_interval_seconds: float = Field(
        default=1.0, gt=0, description="Initial retry interval in seconds."
    )
    backoff_coefficient: float = Field(
        default=2.0, ge=1.0, description="Exponential backoff multiplier."
    )
    maximum_interval_seconds: float | None = Field(
        default=None, description="Cap on retry interval in seconds."
    )
    non_retryable_error_types: list[str] = Field(
        default_factory=list, description="Error types that should not be retried."
    )


class TemporalParam(WorkflowBaseModel):
    """A typed named parameter (an activity / workflow input field)."""

    name: str = Field(..., description="Parameter name (snake_case recommended).")
    type: str = Field(default="str", description="Python type annotation, e.g. 'str', 'int'.")


class InputBinding(WorkflowBaseModel):
    """How one activity input parameter is supplied at a call site."""

    param: str = Field(..., description="The activity input parameter being bound.")
    source: BindingSource = Field(
        default=BindingSource.CONSTANT, description="Where the value comes from."
    )
    ref: str | None = Field(
        default=None,
        description=(
            "For WORKFLOW_INPUT: the WorkflowInput field name. "
            "For STEP_OUTPUT: the producing step id. "
            "For CONSTANT: ignored (value left as a TODO default)."
        ),
    )


class TemporalActivityDesign(WorkflowBaseModel):
    """A single Temporal activity derived from a workflow node."""

    name: str = Field(..., description="Activity name.")
    source_node_id: str | None = Field(
        default=None, description="Graph node this activity was derived from."
    )
    description: str | None = Field(default=None, description="What the activity does.")
    inputs: list[str] = Field(
        default_factory=list, description="Named input parameters (legacy; prefer `params`)."
    )
    params: list[TemporalParam] = Field(
        default_factory=list, description="Typed input parameters; supersedes `inputs`."
    )
    outputs: list[str] = Field(default_factory=list, description="Named outputs.")
    result_type: str = Field(default="str", description="Python return type annotation.")
    timeout_seconds: float | None = Field(
        default=None, description="Start-to-close timeout in seconds."
    )
    retry_policy: RetryPolicyDesign | None = Field(
        default=None, description="Retry policy for the activity."
    )

    def effective_params(self) -> list[TemporalParam]:
        """Typed params, falling back to legacy ``inputs`` as ``str`` params."""
        if self.params:
            return self.params
        return [TemporalParam(name=name) for name in self.inputs]


class TemporalStep(WorkflowBaseModel):
    """One node in the workflow plan (IR) — a typed "category of action"."""

    id: str = Field(..., description="Unique step id, used to reference its output.")
    kind: StepKind = Field(..., description="The category of action this step performs.")
    description: str | None = Field(default=None, description="Human-readable purpose.")

    # ACTIVITY / CHILD_WORKFLOW
    ref: str | None = Field(
        default=None, description="Name of the activity or child workflow this step invokes."
    )
    bindings: list[InputBinding] = Field(
        default_factory=list, description="How this step's inputs are supplied."
    )
    result_name: str | None = Field(
        default=None, description="Variable name to bind this step's result to."
    )

    # SIGNAL_GATE
    signal: str | None = Field(
        default=None, description="For SIGNAL_GATE: the signal name to wait for."
    )
    condition: str | None = Field(
        default=None, description="For SIGNAL_GATE: human-readable wait condition."
    )

    # TIMER
    timer: str | None = Field(
        default=None, description="For TIMER: the timer name (duration from `timers`)."
    )

    # BRANCH
    predicate: str | None = Field(
        default=None, description="For BRANCH: human-readable condition for the `then` lane."
    )

    # PARALLEL: each lane runs concurrently. BRANCH: lanes[0]=then, lanes[1]=else.
    lanes: list[list[TemporalStep]] = Field(
        default_factory=list, description="Nested step lanes for PARALLEL / BRANCH."
    )


class TemporalSignalDesign(WorkflowBaseModel):
    """A Temporal signal handler design."""

    name: str = Field(..., description="Signal name.")
    description: str | None = Field(default=None, description="When/why the signal is sent.")
    payload: list[str] = Field(default_factory=list, description="Named payload fields.")


class TemporalQueryDesign(WorkflowBaseModel):
    """A Temporal query handler design."""

    name: str = Field(..., description="Query name.")
    description: str | None = Field(default=None, description="What state the query returns.")
    returns: str | None = Field(default=None, description="Return type or shape description.")
    state_field: str | None = Field(
        default=None, description="Workflow state attribute this query returns (snake_case)."
    )


class TemporalTimerDesign(WorkflowBaseModel):
    """A Temporal timer / durable sleep design."""

    name: str = Field(..., description="Timer name.")
    duration_seconds: float = Field(..., gt=0, description="Timer duration in seconds.")
    description: str | None = Field(default=None, description="What the timer gates.")


class TemporalChildWorkflowDesign(WorkflowBaseModel):
    """A child workflow invoked by the parent workflow."""

    name: str = Field(..., description="Child workflow type name.")
    source_node_id: str | None = Field(
        default=None, description="Graph node (e.g. subprocess) this child was derived from."
    )
    description: str | None = Field(default=None, description="What the child workflow does.")
    inputs: list[str] = Field(default_factory=list, description="Named input parameters.")
    params: list[TemporalParam] = Field(
        default_factory=list, description="Typed input parameters; supersedes `inputs`."
    )
    outputs: list[str] = Field(default_factory=list, description="Named outputs.")
    task_queue: str | None = Field(
        default=None, description="Recommended task queue for the child workflow."
    )

    def effective_params(self) -> list[TemporalParam]:
        """Typed params, falling back to legacy ``inputs`` as ``str`` params."""
        if self.params:
            return self.params
        return [TemporalParam(name=name) for name in self.inputs]


class TemporalCompensationDesign(WorkflowBaseModel):
    """A compensation (saga rollback) activity that undoes a prior activity."""

    name: str = Field(..., description="Compensation activity name.")
    compensates: str | None = Field(
        default=None, description="Name of the activity this compensation reverses."
    )
    source_node_id: str | None = Field(
        default=None, description="Graph node this compensation was derived from."
    )
    description: str | None = Field(
        default=None, description="What the compensation undoes and when it runs."
    )
    inputs: list[str] = Field(
        default_factory=list, description="Named input parameters (legacy; prefer `params`)."
    )
    params: list[TemporalParam] = Field(
        default_factory=list, description="Typed input parameters; supersedes `inputs`."
    )
    bindings: list[InputBinding] = Field(
        default_factory=list,
        description=(
            "How this compensation's inputs are supplied when it is registered "
            "(typically bound to the workflow input or the compensated activity's output)."
        ),
    )
    retry_policy: RetryPolicyDesign | None = Field(
        default=None, description="Retry policy for the compensation activity."
    )

    def effective_params(self) -> list[TemporalParam]:
        """Typed params, falling back to legacy ``inputs`` as ``str`` params."""
        if self.params:
            return self.params
        return [TemporalParam(name=name) for name in self.inputs]


class TemporalWorkflowDesign(WorkflowBaseModel):
    """A complete Temporal workflow blueprint (declarations + plan IR)."""

    workflow_name: str = Field(..., description="Temporal workflow type name.")
    task_queue: str | None = Field(default=None, description="Recommended task queue name.")
    description: str | None = Field(default=None, description="Workflow purpose.")
    workflow_inputs: list[TemporalParam] = Field(
        default_factory=list, description="Typed fields of the top-level WorkflowInput."
    )
    result_type: str = Field(default="str", description="Workflow run return type annotation.")
    activities: list[TemporalActivityDesign] = Field(
        default_factory=list, description="Activity declarations."
    )
    signals: list[TemporalSignalDesign] = Field(
        default_factory=list, description="Signal handler designs."
    )
    queries: list[TemporalQueryDesign] = Field(
        default_factory=list, description="Query handler designs."
    )
    child_workflows: list[TemporalChildWorkflowDesign] = Field(
        default_factory=list, description="Child workflow designs."
    )
    timers: list[TemporalTimerDesign] = Field(default_factory=list, description="Timer designs.")
    compensation_activities: list[TemporalCompensationDesign] = Field(
        default_factory=list, description="Compensation (saga rollback) activity designs."
    )
    default_retry_policy: RetryPolicyDesign | None = Field(
        default=None, description="Workflow-wide default retry policy."
    )
    plan: list[TemporalStep] = Field(
        default_factory=list,
        description=(
            "Ordered control-and-data-flow plan (IR). When empty, the generator "
            "synthesizes a linear plan from the declarations and the graph order."
        ),
    )


class GeneratedFile(WorkflowBaseModel):
    """A single generated source file in a Temporal code bundle."""

    path: str = Field(..., description="Relative file path within the generated package.")
    language: str = Field(default="python", description="Source language of the file.")
    content: str = Field(..., description="Full file contents.")


class TemporalCodeBundle(WorkflowBaseModel):
    """Executable Temporal SDK source files rendered from a TemporalWorkflowDesign.

    This is produced by a **deterministic** generator (no LLM) that mechanically
    renders the approved :class:`TemporalWorkflowDesign` into runnable Temporal
    code via templates — the design itself remains specification-only.
    """

    target: str = Field(default="python", description="Temporal SDK target language.")
    package_name: str = Field(..., description="Generated package / module directory name.")
    files: list[GeneratedFile] = Field(
        default_factory=list, description="Generated source files, in write order."
    )


# ``TemporalStep`` is self-referential (lanes hold nested steps); rebuild so the
# forward reference under ``from __future__ import annotations`` is resolved.
TemporalStep.model_rebuild()


#: Tokens too generic to pair a timer with a signal by themselves.
_GENERIC_TIMER_TOKENS = frozenset(
    {"timeout", "timer", "deadline", "sla", "wait", "confirmation", "signal", "event"}
)


def _timer_tokens(name: str) -> set[str]:
    """Meaningful (>2-char) tokens of ``name``, splitting camelCase and delimiters.

    ``CarrierPickupTimeout`` → ``{carrier, pickup, timeout}`` and
    ``carrier.picked_up`` → ``{carrier, picked}`` so the two can be compared.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name or "")
    return {t for t in re.findall(r"[a-z0-9]+", spaced.lower()) if len(t) > 2}


def pair_gate_timer(
    explicit_timer: str | None,
    signal_name: str,
    timers: list[TemporalTimerDesign],
) -> TemporalTimerDesign | None:
    """Return the declared timer that bounds a signal gate, or ``None``.

    Documents that follow the format guide pair every human/external wait with a
    deadline ("shipping confirmation must arrive within 24 hours"), recorded as a
    timer. Pairing order: an explicit timer name on the step, then the unique
    timer sharing a meaningful name/description token with the signal
    (``carrier.picked_up`` ↔ ``CarrierPickupTimeout``). An ambiguous tie binds
    nothing (leave the wait unbounded rather than guess). Shared by the code
    generator (to emit ``timeout=``) and the design agent (to decide whether a
    gate is a bounded wait) so the two never diverge.
    """
    if explicit_timer:
        target = "".join(re.findall(r"[a-z0-9]+", explicit_timer.lower()))
        for timer in timers:
            if "".join(re.findall(r"[a-z0-9]+", timer.name.lower())) == target:
                return timer
    signal_tokens = _timer_tokens(signal_name) - _GENERIC_TIMER_TOKENS
    if not signal_tokens:
        return None
    scored: list[tuple[int, TemporalTimerDesign]] = []
    for timer in timers:
        timer_tokens = (
            _timer_tokens(timer.name) | _timer_tokens(timer.description or "")
        ) - _GENERIC_TIMER_TOKENS
        overlap = len(signal_tokens & timer_tokens)
        if overlap:
            scored.append((overlap, timer))
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None  # ambiguous — leave the wait unbounded rather than guess
    return scored[0][1]

"""Render a :class:`TemporalWorkflowDesign` into runnable Temporal Python code.

This generator is **deterministic** — it uses no LLM. It is the executable
counterpart to :class:`~workflow_compiler.agents.temporal.TemporalGeneratorAgent`:
the agent produces a specification, and this generator mechanically renders that
specification into Temporal Python SDK source files.

The generator walks the design's **plan** (an IR of typed
:class:`~workflow_compiler.models.TemporalStep` "categories of actions"):

* **activity / child_workflow** — a call whose inputs are bound (from the
  workflow input or an earlier step's output) and whose result is captured;
* **signal_gate** — ``await workflow.wait_condition(...)`` to pause for a signal;
* **timer** — ``await workflow.sleep(...)`` on a declared durable timer;
* **parallel** — concurrent activity calls via ``asyncio.gather``;
* **branch** — a real ``if/else`` over a (TODO) predicate.

Saga compensations registered for an activity fire in reverse on failure. When
the plan is empty the generator synthesizes a linear plan from the activity
declarations ordered by the workflow graph, preserving backward compatibility.

The complex control/data-flow body of ``@workflow.run`` is emitted here (in
Python, where it is testable); Jinja templates render the surrounding file
skeletons and the simple signal/query/timer/child declarations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from workflow_compiler.models import (
    BindingSource,
    EdgeType,
    GeneratedFile,
    RetryPolicyDesign,
    StepKind,
    TemporalActivityDesign,
    TemporalChildWorkflowDesign,
    TemporalCompensationDesign,
    TemporalParam,
    TemporalStep,
    TemporalWorkflowDesign,
    WorkflowGraph,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

#: Edge kinds that form the workflow's forward "backbone" used for ordering.
_BACKBONE_EDGES = frozenset({EdgeType.SEQUENCE, EdgeType.DEFAULT, EdgeType.CONDITIONAL})

#: Fallback start-to-close timeout (seconds) when a design activity omits one.
_DEFAULT_TIMEOUT_SECONDS = 60.0

#: Timeout used when executing saga compensation activities.
_COMPENSATION_TIMEOUT_SECONDS = 60.0

_INDENT = "    "


def _snake(name: str) -> str:
    """Convert any name to a safe ``snake_case`` Python identifier."""
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"x_{cleaned}" if cleaned else "item"
    return cleaned


def _pascal(name: str) -> str:
    """Convert any name to a safe ``PascalCase`` Python identifier."""
    words = "".join(c if c.isalnum() else " " for c in name).split()
    pascal = "".join(word[:1].upper() + word[1:] for word in words)
    if not pascal or pascal[0].isdigit():
        pascal = f"X{pascal}" if pascal else "Item"
    return pascal


def _num(value: float) -> str:
    """Render a number without a trailing ``.0`` when it is integral."""
    return str(int(value)) if float(value).is_integer() else repr(value)


def _dedupe(names: list[str]) -> list[str]:
    """Return ``names`` with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _default_for(type_str: str) -> str:
    """A safe literal default for a dataclass field of the given annotation."""
    return {
        "str": '""',
        "int": "0",
        "float": "0.0",
        "bool": "False",
        "dict": "field(default_factory=dict)",
        "list": "field(default_factory=list)",
    }.get(type_str.strip(), "None")


# --- Template context dataclasses ------------------------------------------


@dataclass(frozen=True)
class _Field:
    name: str
    annotation: str
    default: str


@dataclass(frozen=True)
class _InputClass:
    name: str
    fields: list[_Field]


@dataclass(frozen=True)
class _Activity:
    activity_name: str
    fn_name: str
    input_class: str
    description: str | None
    return_type: str = "str"


@dataclass(frozen=True)
class _Child:
    class_name: str
    run_symbol: str
    input_class: str
    description: str | None


@dataclass(frozen=True)
class _Signal:
    method: str
    attr: str
    params: list[str]
    signal_name: str


@dataclass(frozen=True)
class _Query:
    method: str
    query_name: str
    return_type: str
    description: str | None


@dataclass(frozen=True)
class _Timer:
    const: str
    seconds: str
    description: str | None


class TemporalPythonCodeGenerator:
    """Render a :class:`TemporalWorkflowDesign` into a :class:`TemporalCodeBundle`."""

    def __init__(self) -> None:
        """Configure the Jinja environment over the bundled templates."""
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            autoescape=False,
        )

    def generate(
        self,
        design: TemporalWorkflowDesign,
        *,
        graph: WorkflowGraph | None = None,
    ) -> "TemporalCodeBundle":  # noqa: F821 (imported lazily below)
        """Render ``design`` (ordered by ``graph`` when available) into files."""
        from workflow_compiler.models import TemporalCodeBundle

        workflow_class = _pascal(design.workflow_name)
        package_name = _snake(design.workflow_name)

        activities = self._activities(design)
        children = self._children(design)
        input_classes = self._input_classes(design)
        signals = self._signals(design)
        queries = self._queries(design)
        timers = self._timers(design)

        plan = design.plan or self._synthesize_plan(design, graph)
        body = _RunBodyEmitter(design).emit(plan)

        context: dict[str, object] = {
            "workflow_class": workflow_class,
            "package_name": package_name,
            "task_queue": design.task_queue or f"{package_name}-task-queue",
            "description": design.description,
            "activities": activities,
            "children": children,
            "input_classes": input_classes,
            "workflow_input_fields": self._workflow_input_fields(design),
            "signals": signals,
            "queries": queries,
            "timers": timers,
            "run_body": body.text,
            "uses_asyncio": body.uses_asyncio,
            "activity_fn_names": [a.fn_name for a in activities],
            "child_class_names": [c.class_name for c in children],
        }

        files = [
            GeneratedFile(path="shared.py", content=self._render("shared.py.jinja", context)),
            GeneratedFile(
                path="activities.py", content=self._render("activities.py.jinja", context)
            ),
            GeneratedFile(path="workflow.py", content=self._render("workflow.py.jinja", context)),
            GeneratedFile(path="worker.py", content=self._render("worker.py.jinja", context)),
            GeneratedFile(path="starter.py", content=self._render("starter.py.jinja", context)),
            GeneratedFile(
                path="README.md",
                language="markdown",
                content=self._render("README.md.jinja", context),
            ),
        ]
        return TemporalCodeBundle(target="python", package_name=package_name, files=files)

    def _render(self, template_name: str, context: dict[str, object]) -> str:
        """Render a single template to text."""
        return self._env.get_template(template_name).render(**context)

    # -- declaration context builders ---------------------------------------

    def _activities(self, design: TemporalWorkflowDesign) -> list[_Activity]:
        """Activity functions emitted into ``activities.py`` (incl. compensations)."""
        out: list[_Activity] = []
        for activity in design.activities:
            out.append(
                _Activity(
                    activity_name=activity.name,
                    fn_name=_snake(activity.name),
                    input_class=f"{_pascal(activity.name)}Input",
                    description=activity.description,
                    return_type=activity.result_type or "str",
                )
            )
        for comp in design.compensation_activities:
            out.append(
                _Activity(
                    activity_name=comp.name,
                    fn_name=_snake(comp.name),
                    input_class=f"{_pascal(comp.name)}Input",
                    description=comp.description
                    or (f"Compensates {comp.compensates}." if comp.compensates else None),
                )
            )
        return out

    @staticmethod
    def _children(design: TemporalWorkflowDesign) -> list[_Child]:
        out: list[_Child] = []
        for child in design.child_workflows:
            class_name = _pascal(child.name)
            out.append(
                _Child(
                    class_name=class_name,
                    run_symbol=f"{class_name}.run",
                    input_class=f"{class_name}Input",
                    description=child.description,
                )
            )
        return out

    @staticmethod
    def _params_to_fields(params: list[TemporalParam]) -> list[_Field]:
        fields: list[_Field] = []
        seen: set[str] = set()
        for param in params:
            name = _snake(param.name)
            if not name or name in seen:
                continue
            seen.add(name)
            annotation = (param.type or "str").strip() or "str"
            fields.append(_Field(name=name, annotation=annotation, default=_default_for(annotation)))
        return fields

    def _input_classes(self, design: TemporalWorkflowDesign) -> list[_InputClass]:
        """Unique typed input dataclasses for activity, compensation, and child."""
        classes: dict[str, _InputClass] = {}

        def add(raw_name: str, params: list[TemporalParam]) -> None:
            class_name = f"{_pascal(raw_name)}Input"
            if class_name not in classes:
                classes[class_name] = _InputClass(
                    name=class_name, fields=self._params_to_fields(params)
                )

        for activity in design.activities:
            add(activity.name, activity.effective_params())
        for comp in design.compensation_activities:
            add(comp.name, [])
        for child in design.child_workflows:
            add(child.name, child.effective_params())
        return list(classes.values())

    def _workflow_input_fields(self, design: TemporalWorkflowDesign) -> list[_Field]:
        """Typed fields for the top-level ``WorkflowInput`` dataclass."""
        return self._params_to_fields(design.workflow_inputs)

    @staticmethod
    def _signals(design: TemporalWorkflowDesign) -> list[_Signal]:
        out: list[_Signal] = []
        for signal in design.signals:
            method = _snake(signal.name)
            out.append(
                _Signal(
                    method=method,
                    attr=f"_{method}_received",
                    params=_dedupe([_snake(p) for p in signal.payload]),
                    signal_name=signal.name,
                )
            )
        return out

    @staticmethod
    def _queries(design: TemporalWorkflowDesign) -> list[_Query]:
        out: list[_Query] = []
        for query in design.queries:
            out.append(
                _Query(
                    method=_snake(query.name),
                    query_name=query.name,
                    return_type="str",
                    description=query.description or query.returns,
                )
            )
        return out

    @staticmethod
    def _timers(design: TemporalWorkflowDesign) -> list[_Timer]:
        out: list[_Timer] = []
        for timer in design.timers:
            out.append(
                _Timer(
                    const=_snake(timer.name).upper(),
                    seconds=_num(timer.duration_seconds),
                    description=timer.description,
                )
            )
        return out

    # -- plan synthesis (backward-compat for designs without an IR) ----------

    def _synthesize_plan(
        self, design: TemporalWorkflowDesign, graph: WorkflowGraph | None
    ) -> list[TemporalStep]:
        """Build a linear plan from activity + child declarations in graph order."""
        order = self._execution_order(graph)
        unplaced = len(order) + 1

        indexed: list[tuple[int, int, TemporalStep]] = []
        for i, activity in enumerate(design.activities):
            pos = order.get(activity.source_node_id or "", unplaced)
            indexed.append(
                (
                    pos,
                    i,
                    TemporalStep(
                        id=_snake(activity.name),
                        kind=StepKind.ACTIVITY,
                        ref=activity.name,
                        result_name=f"{_snake(activity.name)}_result",
                    ),
                )
            )
        offset = len(design.activities)
        for j, child in enumerate(design.child_workflows):
            pos = order.get(child.source_node_id or "", unplaced)
            indexed.append(
                (
                    pos,
                    offset + j,
                    TemporalStep(
                        id=_snake(child.name),
                        kind=StepKind.CHILD_WORKFLOW,
                        ref=child.name,
                        result_name=f"{_snake(child.name)}_result",
                    ),
                )
            )
        indexed.sort(key=lambda item: (item[0], item[1]))
        return [step for _pos, _idx, step in indexed]

    @staticmethod
    def _execution_order(graph: WorkflowGraph | None) -> dict[str, int]:
        """Topologically order node ids over the forward backbone edges."""
        if graph is None:
            return {}
        digraph: nx.DiGraph = nx.DiGraph()
        for node in graph.nodes:
            digraph.add_node(node.id)
        for edge in graph.edges:
            if edge.edge_type in _BACKBONE_EDGES:
                digraph.add_edge(edge.source, edge.target)
        try:
            ordered = list(nx.topological_sort(digraph))
        except nx.NetworkXUnfeasible:
            ordered = [node.id for node in graph.nodes]
        return {node_id: index for index, node_id in enumerate(ordered)}


def _timeout_expr(seconds: float | None) -> str:
    value = seconds if seconds and seconds > 0 else _DEFAULT_TIMEOUT_SECONDS
    return f"timedelta(seconds={_num(value)})"


def _retry_expr(policy: RetryPolicyDesign | None) -> str | None:
    """Render a ``RetryPolicy(...)`` constructor expression, or ``None``."""
    if policy is None:
        return None
    parts = [
        f"initial_interval=timedelta(seconds={_num(policy.initial_interval_seconds)})",
        f"backoff_coefficient={_num(policy.backoff_coefficient)}",
        f"maximum_attempts={policy.maximum_attempts}",
    ]
    if policy.maximum_interval_seconds is not None:
        parts.append(
            f"maximum_interval=timedelta(seconds={_num(policy.maximum_interval_seconds)})"
        )
    if policy.non_retryable_error_types:
        types = ", ".join(repr(t) for t in policy.non_retryable_error_types)
        parts.append(f"non_retryable_error_types=[{types}]")
    return "RetryPolicy(" + ", ".join(parts) + ")"


@dataclass
class _Body:
    text: str
    uses_asyncio: bool


class _RunBodyEmitter:
    """Emit the full body of ``@workflow.run`` from a plan (IR)."""

    def __init__(self, design: TemporalWorkflowDesign) -> None:
        self._design = design
        self._activities = {a.name: a for a in design.activities}
        self._children = {c.name: c for c in design.child_workflows}
        self._signals = {_snake(s.name): s for s in design.signals}
        self._timers = {_snake(t.name): t for t in design.timers}
        self._comps_by_activity = self._compensations_by_activity(design)
        # step id -> variable name holding its result.
        self._result_vars: dict[str, str] = {}
        self._uses_asyncio = False

    def emit(self, plan: list[TemporalStep]) -> _Body:
        self._index_result_vars(plan)
        lines: list[str] = []
        lines.append('self._status = "running"')
        lines.append("compensations: list[tuple[Callable[..., Any], Any]] = []")
        lines.append("try:")
        body = self._emit_steps(plan, depth=1)
        if not body:
            body = [_INDENT + "pass  # TODO: no activities were derived from the design."]
        lines.extend(body)
        lines.append("except Exception:")
        lines.append(_INDENT + "for _comp_fn, _comp_arg in reversed(compensations):")
        lines.append(_INDENT * 2 + "await workflow.execute_activity(")
        lines.append(_INDENT * 3 + "_comp_fn,")
        lines.append(_INDENT * 3 + "_comp_arg,")
        lines.append(
            _INDENT * 3
            + f"start_to_close_timeout={_timeout_expr(_COMPENSATION_TIMEOUT_SECONDS)},"
        )
        lines.append(_INDENT * 2 + ")")
        lines.append(_INDENT + 'self._status = "compensated"')
        lines.append(_INDENT + "raise")
        lines.append('self._status = "completed"')
        lines.append("return self._status")
        # Re-indent the whole body to 8 spaces (inside the method).
        text = "\n".join((_INDENT * 2 + line) if line else line for line in lines)
        return _Body(text=text, uses_asyncio=self._uses_asyncio)

    # -- result variable indexing -------------------------------------------

    def _index_result_vars(self, steps: list[TemporalStep]) -> None:
        for step in steps:
            if step.kind in (StepKind.ACTIVITY, StepKind.CHILD_WORKFLOW):
                self._result_vars[step.id] = (
                    _snake(step.result_name) if step.result_name else f"{_snake(step.id)}_result"
                )
            for lane in step.lanes:
                self._index_result_vars(lane)

    # -- step emission ------------------------------------------------------

    def _emit_steps(self, steps: list[TemporalStep], *, depth: int) -> list[str]:
        out: list[str] = []
        for step in steps:
            out.extend(self._emit_step(step, depth=depth))
        return out

    def _emit_step(self, step: TemporalStep, *, depth: int) -> list[str]:
        if step.kind is StepKind.ACTIVITY:
            return self._emit_activity(step, depth=depth)
        if step.kind is StepKind.CHILD_WORKFLOW:
            return self._emit_child(step, depth=depth)
        if step.kind is StepKind.SIGNAL_GATE:
            return self._emit_gate(step, depth=depth)
        if step.kind is StepKind.TIMER:
            return self._emit_timer(step, depth=depth)
        if step.kind is StepKind.PARALLEL:
            return self._emit_parallel(step, depth=depth)
        if step.kind is StepKind.BRANCH:
            return self._emit_branch(step, depth=depth)
        return []

    def _emit_activity(self, step: TemporalStep, *, depth: int) -> list[str]:
        pad = _INDENT * depth
        activity = self._activities.get(step.ref or "")
        fn = _snake(step.ref or step.id)
        input_class = f"{_pascal(step.ref or step.id)}Input"
        var = self._result_vars.get(step.id)
        timeout = _timeout_expr(activity.timeout_seconds if activity else None)
        retry = _retry_expr(
            (activity.retry_policy if activity else None) or self._design.default_retry_policy
        )
        lines: list[str] = []
        assign = f"{var} = " if var else ""
        lines.append(f"{pad}{assign}await workflow.execute_activity(")
        lines.append(f"{pad}{_INDENT}{fn},")
        lines.append(f"{pad}{_INDENT}{self._input_expr(input_class, step)},")
        lines.append(f"{pad}{_INDENT}start_to_close_timeout={timeout},")
        if retry:
            lines.append(f"{pad}{_INDENT}retry_policy={retry},")
        lines.append(f"{pad})")
        lines.extend(self._emit_compensation_registrations(step.ref or "", depth=depth))
        return lines

    def _emit_child(self, step: TemporalStep, *, depth: int) -> list[str]:
        pad = _INDENT * depth
        child = self._children.get(step.ref or "")
        class_name = _pascal(step.ref or step.id)
        input_class = f"{class_name}Input"
        var = self._result_vars.get(step.id)
        slug = _snake(step.ref or step.id)
        lines: list[str] = []
        assign = f"{var} = " if var else ""
        lines.append(f"{pad}{assign}await workflow.execute_child_workflow(")
        lines.append(f"{pad}{_INDENT}{class_name}.run,")
        lines.append(f"{pad}{_INDENT}{self._input_expr(input_class, step)},")
        lines.append(f'{pad}{_INDENT}id=f"{{workflow.info().workflow_id}}-{slug}",')
        if child and child.task_queue:
            lines.append(f'{pad}{_INDENT}task_queue="{child.task_queue}",')
        lines.append(f"{pad})")
        return lines

    def _emit_gate(self, step: TemporalStep, *, depth: int) -> list[str]:
        pad = _INDENT * depth
        signal = self._signals.get(_snake(step.signal or ""))
        lines: list[str] = []
        if step.condition:
            lines.append(f"{pad}# Wait until: {step.condition}")
        if signal:
            attr = f"_{_snake(signal.name)}_received"
            lines.append(f"{pad}await workflow.wait_condition(lambda: self.{attr})")
        else:
            lines.append(f"{pad}await workflow.wait_condition(lambda: True)  # TODO: real condition")
        return lines

    def _emit_timer(self, step: TemporalStep, *, depth: int) -> list[str]:
        pad = _INDENT * depth
        timer = self._timers.get(_snake(step.timer or ""))
        if timer:
            const = _snake(timer.name).upper()
            return [f"{pad}await workflow.sleep({const})"]
        return [f"{pad}await workflow.sleep(timedelta(seconds=60))  # TODO: timer duration"]

    def _emit_parallel(self, step: TemporalStep, *, depth: int) -> list[str]:
        pad = _INDENT * depth
        # Collect the leading activity/child of each lane into a single gather.
        calls: list[TemporalStep] = []
        for lane in step.lanes:
            for inner in lane:
                if inner.kind in (StepKind.ACTIVITY, StepKind.CHILD_WORKFLOW):
                    calls.append(inner)
                    break
        if not calls:
            return [f"{pad}pass  # TODO: empty parallel group"]
        self._uses_asyncio = True
        lines = [f"{pad}await asyncio.gather("]
        for call in calls:
            lines.extend(self._gather_call_expr(call, depth=depth + 1))
        lines.append(f"{pad})")
        return lines

    def _gather_call_expr(self, step: TemporalStep, *, depth: int) -> list[str]:
        """A single ``workflow.execute_*`` expression (no ``await``) for gather()."""
        pad = _INDENT * depth
        if step.kind is StepKind.CHILD_WORKFLOW:
            class_name = _pascal(step.ref or step.id)
            slug = _snake(step.ref or step.id)
            return [
                f"{pad}workflow.execute_child_workflow(",
                f"{pad}{_INDENT}{class_name}.run,",
                f"{pad}{_INDENT}{class_name}Input(),",
                f'{pad}{_INDENT}id=f"{{workflow.info().workflow_id}}-{slug}",',
                f"{pad}),",
            ]
        activity = self._activities.get(step.ref or "")
        fn = _snake(step.ref or step.id)
        input_class = f"{_pascal(step.ref or step.id)}Input"
        timeout = _timeout_expr(activity.timeout_seconds if activity else None)
        retry = _retry_expr(
            (activity.retry_policy if activity else None) or self._design.default_retry_policy
        )
        lines = [
            f"{pad}workflow.execute_activity(",
            f"{pad}{_INDENT}{fn},",
            f"{pad}{_INDENT}{self._input_expr(input_class, step)},",
            f"{pad}{_INDENT}start_to_close_timeout={timeout},",
        ]
        if retry:
            lines.append(f"{pad}{_INDENT}retry_policy={retry},")
        lines.append(f"{pad}),")
        return lines

    def _emit_branch(self, step: TemporalStep, *, depth: int) -> list[str]:
        pad = _INDENT * depth
        then_lane = step.lanes[0] if len(step.lanes) >= 1 else []
        else_lane = step.lanes[1] if len(step.lanes) >= 2 else []
        predicate = step.predicate or "condition"
        lines = [f"{pad}if True:  # TODO: replace with real condition: {predicate}"]
        then_body = self._emit_steps(then_lane, depth=depth + 1)
        lines.extend(then_body or [f"{pad}{_INDENT}pass"])
        if else_lane:
            lines.append(f"{pad}else:")
            lines.extend(self._emit_steps(else_lane, depth=depth + 1))
        return lines

    # -- helpers ------------------------------------------------------------

    def _input_expr(self, input_class: str, step: TemporalStep) -> str:
        """Construct the input dataclass, binding params that have a source."""
        kwargs: list[str] = []
        for binding in step.bindings:
            expr = self._binding_expr(binding)
            if expr is None:
                continue
            kwargs.append(f"{_snake(binding.param)}={expr}")
        return f"{input_class}({', '.join(kwargs)})"

    def _binding_expr(self, binding) -> str | None:  # type: ignore[no-untyped-def]
        if binding.source is BindingSource.WORKFLOW_INPUT and binding.ref:
            return f"arg.{_snake(binding.ref)}"
        if binding.source is BindingSource.STEP_OUTPUT and binding.ref:
            var = self._result_vars.get(binding.ref) or self._result_vars.get(_snake(binding.ref))
            return var or f"{_snake(binding.ref)}_result"
        return None  # CONSTANT: rely on the dataclass default.

    def _emit_compensation_registrations(self, activity_name: str, *, depth: int) -> list[str]:
        pad = _INDENT * depth
        out: list[str] = []
        for comp in self._comps_by_activity.get(_pascal_key(activity_name), []):
            fn = _snake(comp.name)
            input_class = f"{_pascal(comp.name)}Input"
            out.append(f"{pad}compensations.append(({fn}, {input_class}()))")
        return out

    @staticmethod
    def _compensations_by_activity(
        design: TemporalWorkflowDesign,
    ) -> dict[str, list[TemporalCompensationDesign]]:
        """Map an activity name to compensations registered after it succeeds."""
        by_node = {a.source_node_id: a.name for a in design.activities if a.source_node_id}
        mapping: dict[str, list[TemporalCompensationDesign]] = {}
        for comp in design.compensation_activities:
            key = comp.compensates or by_node.get(comp.source_node_id or "")
            if key:
                mapping.setdefault(_pascal_key(key), []).append(comp)
        return mapping


def _pascal_key(name: str) -> str:
    """Normalize an activity name so ``compensates`` matches regardless of casing."""
    return _pascal(name)


def to_temporal_python(
    design: TemporalWorkflowDesign, *, graph: WorkflowGraph | None = None
) -> "TemporalCodeBundle":  # noqa: F821
    """Convenience wrapper around :class:`TemporalPythonCodeGenerator`."""
    return TemporalPythonCodeGenerator().generate(design, graph=graph)

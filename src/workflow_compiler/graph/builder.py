"""Deterministic workflow graph construction from WorkflowFacts.

No LLM is used here: the graph is inferred from the categorized facts
(activities, decisions, state transitions, events, exceptions, retries,
compensations) using fixed, documented rules and a NetworkX ``MultiDiGraph``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise

import networkx as nx

from workflow_compiler.models import (
    EdgeType,
    FactCategory,
    NodeType,
    WorkflowEdge,
    WorkflowFacts,
    WorkflowGraph,
    WorkflowNode,
    WorkflowStructure,
)
from workflow_compiler.models.structure import TERMINAL_TARGETS

_PARALLEL_RE = re.compile(
    r"\b(in\s+parallel|parallel|concurrent(?:ly)?|simultaneous(?:ly)?|at the same time)\b",
    re.IGNORECASE,
)
_TRIGGER_RE = re.compile(
    r"\b(submit|receiv|request|creat|plac|initiat|trigger|arriv)\w*",
    re.IGNORECASE,
)
_TRANSITION_SPLIT = re.compile(r"\s*(?:->|→|=>)\s*")

_START = "start"
_END = "end"


@dataclass
class _EdgeSpec:
    source: str
    target: str
    edge_type: EdgeType
    label: str | None = None
    condition: str | None = None


@dataclass
class _Categorized:
    activities: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    retries: list[str] = field(default_factory=list)
    compensations: list[str] = field(default_factory=list)
    transitions: list[str] = field(default_factory=list)


def _normalize(label: str) -> str:
    return " ".join(label.split()).strip().lower()


class WorkflowGraphBuilder:
    """Build a :class:`WorkflowGraph` deterministically from facts."""

    def build(self, facts: WorkflowFacts) -> tuple[WorkflowGraph, nx.MultiDiGraph]:
        """Return the canonical graph and its backing NetworkX graph."""
        self._nodes: dict[str, WorkflowNode] = {}
        self._edges: list[WorkflowEdge] = []
        self._nx = nx.MultiDiGraph()
        self._name_index: dict[str, str] = {}
        self._state_counter = 0
        self._edge_counter = 0

        cats = self._categorize(facts)

        self._add_node(_START, "Start", NodeType.START)
        self._add_node(_END, "End", NodeType.END)

        seq_ids, par_ids = self._add_activities(cats.activities)
        dec_ids = [
            self._add_node(f"decision_{i}", stmt, NodeType.DECISION)
            for i, stmt in enumerate(cats.decisions, start=1)
        ]
        exc_ids = [
            self._add_node(f"exception_{i}", stmt, NodeType.EVENT, kind="exception")
            for i, stmt in enumerate(cats.exceptions, start=1)
        ]
        comp_ids = [
            self._add_node(f"compensation_{i}", stmt, NodeType.TASK, role="compensation")
            for i, stmt in enumerate(cats.compensations, start=1)
        ]
        evt_ids = [
            self._add_node(f"event_{i}", stmt, NodeType.EVENT)
            for i, stmt in enumerate(cats.events, start=1)
        ]

        specs: list[_EdgeSpec] = self._linear_specs(seq_ids)
        if par_ids:
            self._weave_parallel(specs, seq_ids, par_ids)
        for i, dec in enumerate(dec_ids):
            self._weave_decision(specs, seq_ids, dec, i, exc_ids)

        used_comp: set[str] = set()
        for j, exc in enumerate(exc_ids):
            self._attach_exception(specs, seq_ids, exc, j, comp_ids, used_comp)
        for comp in comp_ids:
            if comp not in used_comp:
                self._attach_leftover_compensation(specs, seq_ids, exc_ids, comp)
        for k in range(len(cats.retries)):
            self._attach_retry(specs, seq_ids, exc_ids, k)
        for evt in evt_ids:
            self._attach_event(specs, seq_ids, evt)
        for transition in cats.transitions:
            self._attach_transition(specs, transition)

        self._emit(specs)
        graph = WorkflowGraph(nodes=list(self._nodes.values()), edges=self._edges)
        return graph, self._nx

    # -- semantic construction (from relational structure) ------------------

    def build_from_structure(
        self, structure: WorkflowStructure
    ) -> tuple[WorkflowGraph, nx.MultiDiGraph]:
        """Build the graph by *reading* id-referenced relations, not guessing.

        Edges are placed from the structure's explicit links — a decision after
        its activity, an exception on the activity that raises it, a compensation
        on the activity it reverses, an event at its emission point, parallel
        groups as fork/join — after referential-integrity validation drops any
        dangling reference. This is the accurate counterpart to :meth:`build`
        (which can only pair facts by position when no relations are available).
        """
        structure, _warnings = structure.validated()

        self._nodes = {}
        self._edges = []
        self._nx = nx.MultiDiGraph()
        self._name_index = {}
        self._state_counter = 0
        self._edge_counter = 0
        self._gateway_counter = 0

        self._add_node(_START, "Start", NodeType.START)
        self._add_node(_END, "End", NodeType.END)

        amap: dict[str, str] = {}
        ordered: list[tuple[str, str | None]] = []  # (graph node id, parallel group)
        for i, activity in enumerate(structure.activities, start=1):
            node_id = self._add_node(f"activity_{i}", activity.name, NodeType.TASK)
            self._name_index.setdefault(_normalize(activity.name), node_id)
            amap[activity.id] = node_id
            ordered.append((node_id, activity.parallel_group))

        dmap = {
            d.id: self._add_node(f"decision_{i}", d.question, NodeType.DECISION)
            for i, d in enumerate(structure.decisions, start=1)
        }
        xmap = {
            x.id: self._add_node(f"exception_{i}", x.reason, NodeType.EVENT, kind="exception")
            for i, x in enumerate(structure.exceptions, start=1)
        }
        cmap = {
            c.id: self._add_node(f"compensation_{i}", c.name, NodeType.TASK, role="compensation")
            for i, c in enumerate(structure.compensations, start=1)
        }
        vmap = {
            v.id: self._add_node(f"event_{i}", v.name, NodeType.EVENT)
            for i, v in enumerate(structure.events, start=1)
        }
        target_map: dict[str, str] = {**amap, **xmap, **vmap}
        default_anchor = ordered[-1][0] if ordered else _START

        specs = self._structure_spine(ordered)
        for decision in structure.decisions:
            self._weave_structure_decision(
                specs,
                dmap[decision.id],
                amap.get(decision.after) or default_anchor,
                self._resolve_target(decision.yes_target, target_map),
                self._resolve_target(decision.no_target, target_map),
            )
        for exc in structure.exceptions:
            source = amap.get(exc.raised_by)
            if source is not None:
                specs.append(_EdgeSpec(source, xmap[exc.id], EdgeType.ERROR, label="on error"))
        for comp in structure.compensations:
            self._attach_structure_compensation(specs, comp, cmap, xmap, amap, structure)
        for event in structure.events:
            self._attach_structure_event(specs, event, vmap[event.id], amap, ordered)
        for transition in structure.transitions:
            source = self._get_or_create_state(transition.source)
            target = self._get_or_create_state(transition.target)
            specs.append(_EdgeSpec(source, target, EdgeType.SEQUENCE, label="transition"))

        # Terminate any exception with no outgoing edge (no compensation) so it
        # ends the flow (reject/fail) instead of dangling as a dead-end.
        exception_nodes = set(xmap.values())
        have_outgoing = {spec.source for spec in specs if spec.source in exception_nodes}
        for exc_node in exception_nodes:
            if exc_node not in have_outgoing:
                specs.append(_EdgeSpec(exc_node, _END, EdgeType.SEQUENCE, label="terminates"))

        self._emit(specs)
        graph = WorkflowGraph(nodes=list(self._nodes.values()), edges=self._edges)
        return graph, self._nx

    def _structure_spine(
        self, ordered: list[tuple[str, str | None]]
    ) -> list[_EdgeSpec]:
        """Chain activities start→…→end, weaving parallel groups into fork/join."""
        units: list[tuple[str, list[str]]] = []
        group_unit: dict[str, int] = {}
        for node_id, group in ordered:
            if group is None:
                units.append(("seq", [node_id]))
            elif group in group_unit:
                units[group_unit[group]][1].append(node_id)
            else:
                group_unit[group] = len(units)
                units.append(("par", [node_id]))

        specs: list[_EdgeSpec] = []
        prev_out = _START
        for kind, node_ids in units:
            if kind == "seq" or len(node_ids) == 1:
                node_id = node_ids[0]
                specs.append(_EdgeSpec(prev_out, node_id, EdgeType.SEQUENCE))
                prev_out = node_id
                continue
            self._gateway_counter += 1
            fork = self._add_node(
                f"gateway_fork_{self._gateway_counter}", "Parallel split", NodeType.GATEWAY
            )
            join = self._add_node(
                f"gateway_join_{self._gateway_counter}", "Parallel join", NodeType.GATEWAY
            )
            specs.append(_EdgeSpec(prev_out, fork, EdgeType.SEQUENCE))
            for node_id in node_ids:
                specs.append(_EdgeSpec(fork, node_id, EdgeType.SEQUENCE, label="parallel"))
                specs.append(_EdgeSpec(node_id, join, EdgeType.SEQUENCE, label="parallel"))
            prev_out = join
        specs.append(_EdgeSpec(prev_out, _END, EdgeType.SEQUENCE))
        return specs

    def _weave_structure_decision(
        self,
        specs: list[_EdgeSpec],
        decision: str,
        anchor: str,
        yes_target: str | None,
        no_target: str | None,
    ) -> None:
        """Insert ``decision`` after ``anchor`` with explicit yes/no branch targets."""
        index = self._find_sequence(specs, anchor)
        follower = specs[index].target if index is not None else _END
        replacement = [
            _EdgeSpec(anchor, decision, EdgeType.SEQUENCE),
            _EdgeSpec(decision, yes_target or follower, EdgeType.CONDITIONAL, condition="yes"),
            _EdgeSpec(decision, no_target or _END, EdgeType.CONDITIONAL, condition="no"),
        ]
        if index is not None:
            specs[index : index + 1] = replacement
        else:
            specs.extend(replacement)

    def _attach_structure_compensation(
        self,
        specs: list[_EdgeSpec],
        comp,  # type: ignore[no-untyped-def]
        cmap: dict[str, str],
        xmap: dict[str, str],
        amap: dict[str, str],
        structure: WorkflowStructure,
    ) -> None:
        """Wire a compensation off the exception (or activity) it reverses."""
        comp_node = cmap[comp.id]
        source: str | None = None
        if comp.compensates is not None:
            for exc in structure.exceptions:
                if exc.raised_by == comp.compensates:
                    source = xmap[exc.id]
                    break
            source = source or amap.get(comp.compensates)
        if source is None:
            return  # no grounded link — do not guess.
        specs.append(_EdgeSpec(source, comp_node, EdgeType.COMPENSATION, label="compensate"))
        specs.append(_EdgeSpec(comp_node, _END, EdgeType.SEQUENCE))

    def _attach_structure_event(
        self,
        specs: list[_EdgeSpec],
        event,  # type: ignore[no-untyped-def]
        event_node: str,
        amap: dict[str, str],
        ordered: list[tuple[str, str | None]],
    ) -> None:
        """Emit an event from its declared activity, or from start if it triggers."""
        emitter = event.emitted_by
        if emitter in amap:
            specs.append(_EdgeSpec(amap[emitter], event_node, EdgeType.SIGNAL, label="emits"))
        elif (emitter in {"start", "trigger"}) or (
            emitter is None and _TRIGGER_RE.search(self._nodes[event_node].label)
        ):
            first = ordered[0][0] if ordered else _END
            specs.append(_EdgeSpec(_START, event_node, EdgeType.SIGNAL, label="event"))
            specs.append(_EdgeSpec(event_node, first, EdgeType.SIGNAL, label="triggers"))
        # else: no grounded emission point — leave unattached rather than guess.

    @staticmethod
    def _resolve_target(ref: str | None, target_map: dict[str, str]) -> str | None:
        """Resolve a branch target id to a graph node id (or terminal)."""
        if ref is None:
            return None
        if ref in target_map:
            return target_map[ref]
        if ref in TERMINAL_TARGETS:
            return _START if ref == "start" else _END
        return None

    # -- categorization -----------------------------------------------------

    @staticmethod
    def _categorize(facts: WorkflowFacts) -> _Categorized:
        cats = _Categorized()
        bucket = {
            FactCategory.ACTIVITY: cats.activities,
            FactCategory.DECISION: cats.decisions,
            FactCategory.EVENT: cats.events,
            FactCategory.EXCEPTION: cats.exceptions,
            FactCategory.RETRY: cats.retries,
            FactCategory.COMPENSATION: cats.compensations,
            FactCategory.STATE_TRANSITION: cats.transitions,
        }
        for fact in facts.facts:
            target = bucket.get(fact.category)
            if target is not None:
                target.append(fact.statement)
        return cats

    # -- node helpers -------------------------------------------------------

    def _add_node(
        self, node_id: str, label: str, node_type: NodeType, **attributes: str
    ) -> str:
        self._nodes[node_id] = WorkflowNode(
            id=node_id, label=label, node_type=node_type, attributes=dict(attributes)
        )
        self._nx.add_node(node_id, label=label, node_type=node_type.value)
        return node_id

    def _add_activities(self, activities: list[str]) -> tuple[list[str], list[str]]:
        seq_ids: list[str] = []
        par_ids: list[str] = []
        for i, stmt in enumerate(activities, start=1):
            node_id = self._add_node(f"activity_{i}", stmt, NodeType.TASK)
            self._name_index.setdefault(_normalize(stmt), node_id)
            if _PARALLEL_RE.search(stmt):
                par_ids.append(node_id)
            else:
                seq_ids.append(node_id)
        return seq_ids, par_ids

    def _get_or_create_state(self, name: str) -> str:
        key = _normalize(name)
        if key in self._name_index:
            return self._name_index[key]
        self._state_counter += 1
        node_id = self._add_node(f"state_{self._state_counter}", name.strip(), NodeType.TASK,
                                 kind="state")
        self._name_index[key] = node_id
        return node_id

    # -- spine construction -------------------------------------------------

    @staticmethod
    def _linear_specs(seq_ids: list[str]) -> list[_EdgeSpec]:
        chain = [_START, *seq_ids, _END]
        return [
            _EdgeSpec(chain[i], chain[i + 1], EdgeType.SEQUENCE)
            for i in range(len(chain) - 1)
        ]

    @staticmethod
    def _find_sequence(specs: list[_EdgeSpec], source: str) -> int | None:
        for index, spec in enumerate(specs):
            if spec.source == source and spec.edge_type is EdgeType.SEQUENCE:
                return index
        return None

    def _weave_parallel(
        self, specs: list[_EdgeSpec], seq_ids: list[str], par_ids: list[str]
    ) -> None:
        anchor = seq_ids[0] if seq_ids else _START
        index = self._find_sequence(specs, anchor)
        follower = specs[index].target if index is not None else _END
        fork = self._add_node("gateway_fork", "Parallel split", NodeType.GATEWAY)
        join = self._add_node("gateway_join", "Parallel join", NodeType.GATEWAY)

        replacement = [_EdgeSpec(anchor, fork, EdgeType.SEQUENCE)]
        for par in par_ids:
            replacement.append(_EdgeSpec(fork, par, EdgeType.SEQUENCE, label="parallel"))
            replacement.append(_EdgeSpec(par, join, EdgeType.SEQUENCE, label="parallel"))
        replacement.append(_EdgeSpec(join, follower, EdgeType.SEQUENCE))

        if index is not None:
            specs[index : index + 1] = replacement
        else:
            specs.extend(replacement)

    def _weave_decision(
        self,
        specs: list[_EdgeSpec],
        seq_ids: list[str],
        decision: str,
        position: int,
        exc_ids: list[str],
    ) -> None:
        anchor = seq_ids[position] if position < len(seq_ids) else (
            seq_ids[-1] if seq_ids else _START
        )
        failure = exc_ids[position] if position < len(exc_ids) else (
            exc_ids[0] if exc_ids else _END
        )
        index = self._find_sequence(specs, anchor)
        follower = specs[index].target if index is not None else _END
        replacement = [
            _EdgeSpec(anchor, decision, EdgeType.SEQUENCE),
            _EdgeSpec(decision, follower, EdgeType.CONDITIONAL, condition="yes"),
            _EdgeSpec(decision, failure, EdgeType.CONDITIONAL, condition="no"),
        ]
        if index is not None:
            specs[index : index + 1] = replacement
        else:
            specs.extend(replacement)

    # -- augmentations ------------------------------------------------------

    def _attach_exception(
        self,
        specs: list[_EdgeSpec],
        seq_ids: list[str],
        exception: str,
        position: int,
        comp_ids: list[str],
        used_comp: set[str],
    ) -> None:
        source = seq_ids[position] if position < len(seq_ids) else (
            seq_ids[-1] if seq_ids else _START
        )
        specs.append(_EdgeSpec(source, exception, EdgeType.ERROR, label="on error"))
        comp = comp_ids[position] if position < len(comp_ids) else (
            comp_ids[0] if comp_ids else None
        )
        if comp is not None:
            specs.append(_EdgeSpec(exception, comp, EdgeType.COMPENSATION, label="compensate"))
            specs.append(_EdgeSpec(comp, _END, EdgeType.SEQUENCE))
            used_comp.add(comp)
        else:
            specs.append(_EdgeSpec(exception, _END, EdgeType.SEQUENCE))

    def _attach_leftover_compensation(
        self,
        specs: list[_EdgeSpec],
        seq_ids: list[str],
        exc_ids: list[str],
        comp: str,
    ) -> None:
        source = exc_ids[0] if exc_ids else (seq_ids[-1] if seq_ids else _START)
        specs.append(_EdgeSpec(source, comp, EdgeType.COMPENSATION, label="compensate"))
        specs.append(_EdgeSpec(comp, _END, EdgeType.SEQUENCE))

    def _attach_retry(
        self, specs: list[_EdgeSpec], seq_ids: list[str], exc_ids: list[str], position: int
    ) -> None:
        target = seq_ids[position] if position < len(seq_ids) else (
            seq_ids[-1] if seq_ids else _START
        )
        source = exc_ids[position] if position < len(exc_ids) else (
            exc_ids[0] if exc_ids else target
        )
        if source == target and target == _START:
            return
        specs.append(_EdgeSpec(source, target, EdgeType.RETRY, label="retry"))

    def _attach_event(self, specs: list[_EdgeSpec], seq_ids: list[str], event: str) -> None:
        label = self._nodes[event].label
        if _TRIGGER_RE.search(label):
            first = seq_ids[0] if seq_ids else _END
            specs.append(_EdgeSpec(_START, event, EdgeType.SIGNAL, label="event"))
            specs.append(_EdgeSpec(event, first, EdgeType.SIGNAL, label="triggers"))
        else:
            anchor = seq_ids[-1] if seq_ids else _START
            specs.append(_EdgeSpec(anchor, event, EdgeType.SIGNAL, label="emits"))

    def _attach_transition(self, specs: list[_EdgeSpec], transition: str) -> None:
        parts = [p for p in _TRANSITION_SPLIT.split(transition) if p.strip()]
        if len(parts) < 2:
            return
        for left, right in pairwise(parts):
            source = self._get_or_create_state(left)
            target = self._get_or_create_state(right)
            specs.append(_EdgeSpec(source, target, EdgeType.SEQUENCE, label="transition"))

    # -- emission -----------------------------------------------------------

    def _emit(self, specs: list[_EdgeSpec]) -> None:
        seen: set[tuple[str, str, str, str | None, str | None]] = set()
        for spec in specs:
            if spec.source not in self._nodes or spec.target not in self._nodes:
                continue
            key = (spec.source, spec.target, spec.edge_type.value, spec.label, spec.condition)
            if key in seen:
                continue
            seen.add(key)
            self._edge_counter += 1
            edge_id = f"e{self._edge_counter}"
            self._edges.append(
                WorkflowEdge(
                    id=edge_id,
                    source=spec.source,
                    target=spec.target,
                    edge_type=spec.edge_type,
                    label=spec.label,
                    condition=spec.condition,
                )
            )
            self._nx.add_edge(
                spec.source,
                spec.target,
                key=edge_id,
                edge_type=spec.edge_type.value,
                label=spec.label,
                condition=spec.condition,
            )

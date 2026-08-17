"""Deterministic structural review of a WorkflowGraph (NetworkX-backed).

Detects disconnected/orphan/unreachable/dead-end nodes, cycles, duplicate
nodes, missing decision branches, and missing start/end nodes, and produces a
:class:`ReviewReport` with a health score, a confidence score, warnings,
errors, and suggested fixes. No LLM is used.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

import networkx as nx

from workflow_compiler.models import (
    EdgeType,
    NodeType,
    ReviewIssue,
    ReviewReport,
    ReviewSeverity,
    WorkflowGraph,
    WorkflowNode,
)

_REVIEWER = "workflow-review"

#: Health penalty applied per finding, by severity.
_SEVERITY_WEIGHT = {
    ReviewSeverity.CRITICAL: 0.5,
    ReviewSeverity.ERROR: 0.25,
    ReviewSeverity.WARNING: 0.05,
    ReviewSeverity.INFO: 0.0,
}

#: Edge types whose presence in a cycle marks it an intended loop.
_LOOP_EDGES = {EdgeType.RETRY, EdgeType.COMPENSATION}

#: Cap on the number of cycles reported to keep the report bounded.
_MAX_CYCLES = 20


def _normalize(label: str) -> str:
    return " ".join(label.split()).strip().lower()


class GraphReviewer:
    """Analyze a :class:`WorkflowGraph` and produce a :class:`ReviewReport`."""

    def review(self, graph: WorkflowGraph) -> ReviewReport:
        """Run all structural checks and assemble a report."""
        nx_graph = self._to_nx(graph)
        pair_types = self._edge_type_index(graph)
        issues: list[ReviewIssue] = []

        starts = [n for n in graph.nodes if n.node_type is NodeType.START]
        ends = [n for n in graph.nodes if n.node_type is NodeType.END]
        reachable = self._reachable(nx_graph, starts)

        self._check_start_end(issues, starts, ends)
        isolated = self._check_isolated(issues, graph, nx_graph)
        orphans = self._check_orphans(issues, graph, nx_graph, isolated)
        self._check_dead_ends(issues, graph, nx_graph, isolated)
        self._check_unreachable(issues, graph, starts, reachable, isolated, orphans)
        self._check_duplicates(issues, graph)
        self._check_missing_branches(issues, graph, nx_graph)
        self._check_cycles(issues, nx_graph, pair_types)

        health = self._health_score(issues)
        confidence = self._confidence(graph, reachable)
        severe = {ReviewSeverity.ERROR, ReviewSeverity.CRITICAL}
        error_count = sum(1 for i in issues if i.severity in severe)
        warning_count = sum(1 for i in issues if i.severity is ReviewSeverity.WARNING)
        summary = (
            f"Graph health {health}: {error_count} error(s), {warning_count} warning(s)."
        )

        return ReviewReport(
            summary=summary,
            issues=self._number(issues),
            score=health,
            health_score=health,
            confidence=confidence,
            reviewer=_REVIEWER,
            reviewed_at=datetime.now(UTC),
        )

    # -- graph helpers ------------------------------------------------------

    @staticmethod
    def _to_nx(graph: WorkflowGraph) -> nx.MultiDiGraph:
        nx_graph: nx.MultiDiGraph = nx.MultiDiGraph()
        for node in graph.nodes:
            nx_graph.add_node(node.id, node_type=node.node_type)
        for edge in graph.edges:
            nx_graph.add_edge(edge.source, edge.target, edge_type=edge.edge_type)
        return nx_graph

    @staticmethod
    def _edge_type_index(graph: WorkflowGraph) -> dict[tuple[str, str], set[EdgeType]]:
        index: dict[tuple[str, str], set[EdgeType]] = defaultdict(set)
        for edge in graph.edges:
            index[(edge.source, edge.target)].add(edge.edge_type)
        return index

    @staticmethod
    def _reachable(nx_graph: nx.MultiDiGraph, starts: list[WorkflowNode]) -> set[str]:
        reachable: set[str] = set()
        for start in starts:
            reachable.add(start.id)
            reachable |= nx.descendants(nx_graph, start.id)
        return reachable

    # -- checks -------------------------------------------------------------

    @staticmethod
    def _check_start_end(
        issues: list[ReviewIssue], starts: list[WorkflowNode], ends: list[WorkflowNode]
    ) -> None:
        if not starts:
            issues.append(
                ReviewIssue(
                    id="",
                    severity=ReviewSeverity.ERROR,
                    message="Workflow graph has no start node.",
                    suggestion="Add a START node and connect it to the first activity.",
                )
            )
        elif len(starts) > 1:
            issues.append(
                ReviewIssue(
                    id="",
                    severity=ReviewSeverity.WARNING,
                    message=f"Workflow graph has {len(starts)} start nodes.",
                    location=", ".join(n.id for n in starts),
                    suggestion="Consolidate to a single START node.",
                )
            )
        if not ends:
            issues.append(
                ReviewIssue(
                    id="",
                    severity=ReviewSeverity.ERROR,
                    message="Workflow graph has no end node.",
                    suggestion="Add an END node reachable from terminal activities.",
                )
            )

    @staticmethod
    def _check_isolated(
        issues: list[ReviewIssue], graph: WorkflowGraph, nx_graph: nx.MultiDiGraph
    ) -> set[str]:
        isolated: set[str] = set()
        for node in graph.nodes:
            if node.node_type in (NodeType.START, NodeType.END):
                continue
            if nx_graph.in_degree(node.id) == 0 and nx_graph.out_degree(node.id) == 0:
                isolated.add(node.id)
                issues.append(
                    ReviewIssue(
                        id="",
                        severity=ReviewSeverity.WARNING,
                        message=f"Node '{node.label}' is disconnected (no edges).",
                        location=node.id,
                        suggestion="Connect the node into the flow or remove it.",
                    )
                )
        return isolated

    @staticmethod
    def _check_orphans(
        issues: list[ReviewIssue],
        graph: WorkflowGraph,
        nx_graph: nx.MultiDiGraph,
        isolated: set[str],
    ) -> set[str]:
        orphans: set[str] = set()
        for node in graph.nodes:
            if node.node_type is NodeType.START or node.id in isolated:
                continue
            if nx_graph.in_degree(node.id) == 0:
                orphans.add(node.id)
                issues.append(
                    ReviewIssue(
                        id="",
                        severity=ReviewSeverity.WARNING,
                        message=f"Orphan node '{node.label}' has no incoming edges.",
                        location=node.id,
                        suggestion="Add a transition from a predecessor node.",
                    )
                )
        return orphans

    @staticmethod
    def _check_dead_ends(
        issues: list[ReviewIssue],
        graph: WorkflowGraph,
        nx_graph: nx.MultiDiGraph,
        isolated: set[str],
    ) -> None:
        for node in graph.nodes:
            if node.node_type is NodeType.END or node.id in isolated:
                continue
            # Terminal EVENT and TRIGGER nodes are intentional, not dead ends:
            #   EVENT   -- the builder wires an output-emit as ``activity -> event`` with no
            #              continuation (the event is data leaving the workflow, not control flow).
            #   TRIGGER -- a fire-and-forget trigger starts *another* workflow and by definition
            #              has no continuation in this one; control does not come back.
            # Signal waits are NodeType.SIGNAL and stay subject to this check.
            if node.node_type in (NodeType.EVENT, NodeType.TRIGGER):
                continue
            if nx_graph.out_degree(node.id) == 0:
                issues.append(
                    ReviewIssue(
                        id="",
                        severity=ReviewSeverity.WARNING,
                        message=f"Dead-end node '{node.label}' has no outgoing edges.",
                        location=node.id,
                        suggestion="Add a transition toward an END node.",
                    )
                )

    @staticmethod
    def _check_unreachable(
        issues: list[ReviewIssue],
        graph: WorkflowGraph,
        starts: list[WorkflowNode],
        reachable: set[str],
        isolated: set[str],
        orphans: set[str],
    ) -> None:
        if not starts:
            return
        for node in graph.nodes:
            if node.node_type is NodeType.START:
                continue
            if node.id in reachable or node.id in isolated or node.id in orphans:
                continue
            issues.append(
                ReviewIssue(
                    id="",
                    severity=ReviewSeverity.WARNING,
                    message=f"State '{node.label}' is unreachable from the start node.",
                    location=node.id,
                    suggestion="Connect this state to the reachable graph from start.",
                )
            )

    @staticmethod
    def _check_duplicates(issues: list[ReviewIssue], graph: WorkflowGraph) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for node in graph.nodes:
            if node.node_type in (NodeType.START, NodeType.END):
                continue
            groups[_normalize(node.label)].append(node.id)
        for label, ids in groups.items():
            if len(ids) > 1:
                issues.append(
                    ReviewIssue(
                        id="",
                        severity=ReviewSeverity.WARNING,
                        message=f"Duplicate nodes share the label '{label}'.",
                        location=", ".join(ids),
                        suggestion="Merge the duplicate nodes into one.",
                    )
                )

    @staticmethod
    def _check_missing_branches(
        issues: list[ReviewIssue], graph: WorkflowGraph, nx_graph: nx.MultiDiGraph
    ) -> None:
        for node in graph.nodes:
            if node.node_type is not NodeType.DECISION:
                continue
            out_targets = set(nx_graph.successors(node.id))
            if len(out_targets) < 2:
                issues.append(
                    ReviewIssue(
                        id="",
                        severity=ReviewSeverity.WARNING,
                        message=(
                            f"Decision '{node.label}' has {len(out_targets)} branch(es); "
                            "expected at least 2."
                        ),
                        location=node.id,
                        suggestion="Add the missing branch (e.g. the failure/no path).",
                    )
                )

    def _check_cycles(
        self,
        issues: list[ReviewIssue],
        nx_graph: nx.MultiDiGraph,
        pair_types: dict[tuple[str, str], set[EdgeType]],
    ) -> None:
        for cycle in list(nx.simple_cycles(nx_graph))[:_MAX_CYCLES]:
            if self._is_intended_loop(cycle, pair_types):
                continue
            issues.append(
                ReviewIssue(
                    id="",
                    severity=ReviewSeverity.WARNING,
                    message=f"Unexpected cycle detected: {' -> '.join(cycle)}.",
                    location=", ".join(cycle),
                    suggestion="Break the cycle or model it as an explicit retry/compensation.",
                )
            )

    @staticmethod
    def _is_intended_loop(
        cycle: list[str], pair_types: dict[tuple[str, str], set[EdgeType]]
    ) -> bool:
        length = len(cycle)
        for i in range(length):
            pair = (cycle[i], cycle[(i + 1) % length])
            if pair_types.get(pair, set()) & _LOOP_EDGES:
                return True
        return False

    # -- scoring ------------------------------------------------------------

    @staticmethod
    def _health_score(issues: list[ReviewIssue]) -> float:
        penalty = sum(_SEVERITY_WEIGHT[issue.severity] for issue in issues)
        return round(max(0.0, 1.0 - penalty), 4)

    @staticmethod
    def _confidence(graph: WorkflowGraph, reachable: set[str]) -> float:
        total = len(graph.nodes)
        if total == 0:
            return 0.0
        reachable_fraction = len(reachable & {n.id for n in graph.nodes}) / total
        return round(min(1.0, 0.5 + 0.5 * reachable_fraction), 4)

    @staticmethod
    def _number(issues: list[ReviewIssue]) -> list[ReviewIssue]:
        return [issue.model_copy(update={"id": f"issue-{i}"}) for i, issue in enumerate(issues, 1)]

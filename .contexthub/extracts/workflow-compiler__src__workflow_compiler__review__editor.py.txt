"""GraphEditor: safe, validated mutations of a WorkflowGraph.

Every operation is pure: it takes a :class:`WorkflowGraph`, returns a new
validated graph, and never mutates its input. Invalid operations raise
:class:`GraphEditError` rather than producing a corrupt graph.
"""

from __future__ import annotations

import re

from workflow_compiler.exceptions import GraphEditError
from workflow_compiler.models import (
    EdgeType,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)

#: Pattern for auto-generated edge ids, e.g. ``e1``, ``e2`` ...
_EDGE_ID_RE = re.compile(r"^e(\d+)$")


class GraphEditor:
    """Stateless helper applying single, validated edits to a workflow graph.

    The editor backs the human-in-the-loop review flow: a reviewer requests an
    edit (add a missing branch, rename a node, retype a step) and receives a new
    graph that is guaranteed to satisfy :class:`WorkflowGraph` invariants.
    """

    @staticmethod
    def _require_node(graph: WorkflowGraph, node_id: str) -> None:
        """Raise if ``node_id`` is not present in ``graph``."""
        if node_id not in graph.node_ids:
            raise GraphEditError(f"Unknown node id {node_id!r}.")

    @staticmethod
    def _build(nodes: list[WorkflowNode], edges: list[WorkflowEdge]) -> WorkflowGraph:
        """Construct a validated graph, surfacing validation as ``GraphEditError``."""
        try:
            return WorkflowGraph(nodes=nodes, edges=edges)
        except ValueError as exc:
            raise GraphEditError(str(exc)) from exc

    @staticmethod
    def _next_edge_id(graph: WorkflowGraph) -> str:
        """Return the next free ``eN`` edge id for ``graph``."""
        highest = 0
        for edge in graph.edges:
            match = _EDGE_ID_RE.match(edge.id)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"e{highest + 1}"

    # -- node operations ----------------------------------------------------

    @classmethod
    def add_node(
        cls,
        graph: WorkflowGraph,
        *,
        node_id: str,
        label: str,
        node_type: NodeType = NodeType.TASK,
        description: str | None = None,
    ) -> WorkflowGraph:
        """Add a new node; raise if ``node_id`` already exists."""
        if node_id in graph.node_ids:
            raise GraphEditError(f"Node id {node_id!r} already exists.")
        node = WorkflowNode(
            id=node_id, label=label, node_type=node_type, description=description
        )
        return cls._build([*graph.nodes, node], list(graph.edges))

    @classmethod
    def remove_node(cls, graph: WorkflowGraph, node_id: str) -> WorkflowGraph:
        """Remove a node and every edge incident to it."""
        cls._require_node(graph, node_id)
        nodes = [n for n in graph.nodes if n.id != node_id]
        edges = [e for e in graph.edges if e.source != node_id and e.target != node_id]
        return cls._build(nodes, edges)

    @classmethod
    def rename_node(
        cls,
        graph: WorkflowGraph,
        node_id: str,
        *,
        label: str,
    ) -> WorkflowGraph:
        """Change a node's human-readable ``label`` (its id is unchanged)."""
        cls._require_node(graph, node_id)
        nodes = [
            n.model_copy(update={"label": label}) if n.id == node_id else n
            for n in graph.nodes
        ]
        return cls._build(nodes, list(graph.edges))

    @classmethod
    def modify_node_type(
        cls,
        graph: WorkflowGraph,
        node_id: str,
        *,
        node_type: NodeType,
    ) -> WorkflowGraph:
        """Change a node's :class:`NodeType`."""
        cls._require_node(graph, node_id)
        nodes = [
            n.model_copy(update={"node_type": node_type}) if n.id == node_id else n
            for n in graph.nodes
        ]
        return cls._build(nodes, list(graph.edges))

    # -- edge operations ----------------------------------------------------

    @classmethod
    def add_edge(
        cls,
        graph: WorkflowGraph,
        *,
        source: str,
        target: str,
        edge_id: str | None = None,
        edge_type: EdgeType = EdgeType.SEQUENCE,
        label: str | None = None,
        condition: str | None = None,
    ) -> WorkflowGraph:
        """Add an edge between two existing nodes; auto-assigns an id if needed."""
        cls._require_node(graph, source)
        cls._require_node(graph, target)
        edge_id = edge_id or cls._next_edge_id(graph)
        if any(e.id == edge_id for e in graph.edges):
            raise GraphEditError(f"Edge id {edge_id!r} already exists.")
        edge = WorkflowEdge(
            id=edge_id,
            source=source,
            target=target,
            edge_type=edge_type,
            label=label,
            condition=condition,
        )
        return cls._build(list(graph.nodes), [*graph.edges, edge])

    @classmethod
    def remove_edge(cls, graph: WorkflowGraph, edge_id: str) -> WorkflowGraph:
        """Remove an edge by id; raise if it does not exist."""
        if not any(e.id == edge_id for e in graph.edges):
            raise GraphEditError(f"Unknown edge id {edge_id!r}.")
        edges = [e for e in graph.edges if e.id != edge_id]
        return cls._build(list(graph.nodes), edges)

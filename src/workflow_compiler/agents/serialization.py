"""Compact text serializations of domain objects for LLM prompts.

Prompts read better (and cost fewer tokens) with a terse, line-oriented view of
the graph than with raw JSON, while still being unambiguous.
"""

from __future__ import annotations

from workflow_compiler.models import CVPAClassification, WorkflowGraph


def graph_to_text(graph: WorkflowGraph) -> str:
    """Render a workflow graph as a readable ``Nodes:`` / ``Edges:`` block."""
    lines: list[str] = ["Nodes:"]
    for node in graph.nodes:
        lines.append(f"- {node.id} [{node.node_type.value}] {node.label}")
    lines.append("Edges:")
    for edge in graph.edges:
        suffix = f" ({edge.label})" if edge.label else ""
        lines.append(f"- {edge.source} -> {edge.target} [{edge.edge_type.value}]{suffix}")
    return "\n".join(lines)


def cvpa_to_text(classification: CVPAClassification) -> str:
    """Render a CVPA classification as one ``node_id: phase`` line per node."""
    return "\n".join(
        f"- {assignment.node_id}: {assignment.phase.value}"
        for assignment in classification.assignments
    )

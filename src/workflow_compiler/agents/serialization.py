"""Compact text serializations of domain objects for LLM prompts.

Prompts read better (and cost fewer tokens) with a terse, line-oriented view of
the graph than with raw JSON, while still being unambiguous.
"""

from __future__ import annotations

from workflow_compiler.models import (
    CVPAClassification,
    FactCategory,
    WorkflowFacts,
    WorkflowGraph,
)


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


#: Fact categories that materially shape the Temporal design, in display order.
_DESIGN_FACT_CATEGORIES: tuple[FactCategory, ...] = (
    FactCategory.INPUT,
    FactCategory.OUTPUT,
    FactCategory.ACTIVITY,
    FactCategory.API,
    FactCategory.DECISION,
    FactCategory.EVENT,
    FactCategory.STATE_TRANSITION,
    FactCategory.RETRY,
    FactCategory.TIMER,
    FactCategory.COMPENSATION,
    FactCategory.EXCEPTION,
    FactCategory.RULE,
)


def facts_to_text(facts: WorkflowFacts) -> str:
    """Render design-relevant facts grouped by category for the design prompt.

    The Temporal design stage previously saw only the graph; the precise retry,
    timer, compensation, and I/O facts extracted from the document were dropped,
    forcing the model to hallucinate them. This surfaces those facts verbatim so
    the design is *derived from* the document, not guessed.
    """
    lines: list[str] = []
    for category in _DESIGN_FACT_CATEGORIES:
        matching = facts.by_category(category)
        if not matching:
            continue
        lines.append(f"{category.value.upper()}:")
        for fact in matching:
            subject = f" [{fact.subject}]" if fact.subject else ""
            lines.append(f"- {fact.statement}{subject}")
    return "\n".join(lines) if lines else "(no detailed facts extracted)"


def cvpa_to_text(classification: CVPAClassification) -> str:
    """Render a CVPA classification as one ``node_id: phase`` line per node."""
    return "\n".join(
        f"- {assignment.node_id}: {assignment.phase.value}"
        for assignment in classification.assignments
    )

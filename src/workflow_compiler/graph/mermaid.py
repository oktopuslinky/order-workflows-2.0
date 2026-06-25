"""Deterministic Mermaid rendering of a WorkflowGraph.

The output is intended to render as-is on mermaid.live and the Mermaid CLI. Two
things matter for that:

* Node ids must not collide with Mermaid keywords. In particular ``end`` is
  reserved (it closes ``subgraph`` blocks), so any node id that is a reserved
  word is rewritten to a safe form.
* Edge labels use the bare ``-->|label|`` form (no surrounding quotes), and all
  labels have characters that would break the parser (quotes, pipes, newlines)
  neutralized.
"""

from __future__ import annotations

from workflow_compiler.models import (
    CVPAClassification,
    CVPAPhase,
    EdgeType,
    MermaidDiagram,
    MermaidDiagramType,
    MermaidDirection,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)

#: Edge types rendered with a dotted arrow.
_DOTTED = {EdgeType.ERROR, EdgeType.RETRY, EdgeType.COMPENSATION, EdgeType.SIGNAL}

#: CVPA phases in canonical (pipeline) order, used for deterministic output.
_PHASE_ORDER = (
    CVPAPhase.CAPTURE,
    CVPAPhase.VALIDATE,
    CVPAPhase.PROCESS,
    CVPAPhase.ACTIVATE,
    CVPAPhase.UNCLASSIFIED,
)

#: ``classDef`` styling per CVPA phase (fill / stroke / text color).
_PHASE_STYLE: dict[CVPAPhase, str] = {
    CVPAPhase.CAPTURE: "fill:#e3f2fd,stroke:#1565c0,color:#0d47a1", # blue
    CVPAPhase.VALIDATE: "fill:#fff8e1,stroke:#f9a825,color:#e65100", # red/orange
    CVPAPhase.PROCESS: "fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20", # green
    CVPAPhase.ACTIVATE: "fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c", # purple
    CVPAPhase.UNCLASSIFIED: "fill:#eeeeee,stroke:#9e9e9e,color:#424242", # gray
}

#: Mermaid reserved words that must not be used as bare node ids.
_RESERVED_IDS = frozenset(
    {
        "end",
        "graph",
        "flowchart",
        "subgraph",
        "class",
        "classdef",
        "click",
        "style",
        "linkstyle",
        "direction",
        "default",
    }
)


def _safe_id(node_id: str) -> str:
    """Return a node id that cannot collide with a Mermaid keyword."""
    return f"{node_id}_node" if node_id.lower() in _RESERVED_IDS else node_id


def _node_label(label: str) -> str:
    """Escape a node label for use inside a quoted Mermaid string."""
    return label.replace('"', "'").replace("\r\n", "\n").replace("\n", "<br/>").strip()


def _edge_label(label: str) -> str:
    """Escape an edge label for the bare ``|label|`` form."""
    return label.replace('"', "'").replace("|", "/").replace("\n", " ").strip()


def _node_decl(node: WorkflowNode) -> str:
    node_id = _safe_id(node.id)
    label = _node_label(node.label)
    if node.node_type in (NodeType.START, NodeType.END):
        return f'{node_id}(["{label}"])'
    if node.node_type is NodeType.DECISION:
        return f'{node_id}{{"{label}"}}'
    if node.node_type is NodeType.GATEWAY:
        return f'{node_id}{{{{"{label}"}}}}'
    if node.node_type is NodeType.EVENT:
        return f'{node_id}(["{label}"])'
    return f'{node_id}["{label}"]'


def _edge_decl(edge: WorkflowEdge) -> str:
    source = _safe_id(edge.source)
    target = _safe_id(edge.target)
    arrow = "-.->" if edge.edge_type in _DOTTED else "-->"
    label = edge.condition or edge.label
    if label:
        return f"{source} {arrow}|{_edge_label(label)}| {target}"
    return f"{source} {arrow} {target}"


def _body_lines(graph: WorkflowGraph) -> list[str]:
    """Render the node and edge declaration lines (without the header)."""
    lines = [f"    {_node_decl(node)}" for node in graph.nodes]
    lines.extend(f"    {_edge_decl(edge)}" for edge in graph.edges)
    return lines


def _cvpa_lines(graph: WorkflowGraph, classification: CVPAClassification) -> list[str]:
    """Render ``classDef`` + ``class`` lines coloring nodes by CVPA phase."""
    phase_by_node = {a.node_id: a.phase for a in classification.assignments}
    grouped: dict[CVPAPhase, list[str]] = {}
    for node in graph.nodes:
        phase = phase_by_node.get(node.id, CVPAPhase.UNCLASSIFIED)
        grouped.setdefault(phase, []).append(_safe_id(node.id))

    lines: list[str] = []
    for phase in _PHASE_ORDER:
        if phase in grouped:
            lines.append(f"    classDef {phase.value} {_PHASE_STYLE[phase]};")
    for phase in _PHASE_ORDER:
        ids = grouped.get(phase)
        if ids:
            lines.append(f"    class {','.join(ids)} {phase.value};")
    return lines


def to_mermaid(graph: WorkflowGraph, *, title: str | None = None) -> MermaidDiagram:
    """Render ``graph`` as a top-down Mermaid flowchart that renders as-is."""
    lines = ["flowchart TD", *_body_lines(graph)]
    return MermaidDiagram(
        diagram_type=MermaidDiagramType.FLOWCHART,
        direction=MermaidDirection.TOP_DOWN,
        source="\n".join(lines),
        title=title,
    )


def to_mermaid_with_cvpa(
    graph: WorkflowGraph,
    classification: CVPAClassification,
    *,
    title: str | None = None,
) -> MermaidDiagram:
    """Render ``graph`` as a flowchart with nodes color-coded by CVPA phase.

    Each node is assigned a Mermaid class (``capture`` / ``validate`` /
    ``process`` / ``activate`` / ``unclassified``) via ``classDef`` so the
    Capture/Validate/Process/Activate grouping is visible at a glance. The
    diagram still renders as-is on mermaid.live and the Mermaid CLI.
    """
    lines = ["flowchart TD", *_body_lines(graph), *_cvpa_lines(graph, classification)]
    return MermaidDiagram(
        diagram_type=MermaidDiagramType.FLOWCHART,
        direction=MermaidDirection.TOP_DOWN,
        source="\n".join(lines),
        title=title,
    )

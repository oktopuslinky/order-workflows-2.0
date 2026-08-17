"""Persist / load a Graph as JSON.

Separates the (potentially slow) ingest step from fast repeated queries:
    ingest a repo -> save graph.json -> ask/impact load graph.json
"""
from __future__ import annotations

import json
from pathlib import Path

from ..model.schema import (
    Confidence,
    Edge,
    EdgeType,
    Graph,
    Node,
    NodeType,
    Source,
)

from ..paths import DEFAULT_GRAPH_PATH


def save(graph: Graph, path: Path = DEFAULT_GRAPH_PATH) -> Path:
    data = {
        "nodes": [
            {
                "id": n.id, "type": n.type.value, "name": n.name, "domain": n.domain,
                "summary": n.summary, "summary_tokens": n.summary_tokens,
                "documentation": n.documentation, "metadata": n.metadata,
            }
            for n in graph.nodes.values()
        ],
        "edges": [
            {
                "type": e.type.value, "src": e.src, "dst": e.dst,
                "attributes": e.attributes, "confidence": e.confidence.value,
                "source": e.source.value, "weight": e.weight,
            }
            for e in graph.edges
        ],
    }
    path.write_text(json.dumps(data, indent=2))
    return path


def load(path: Path = DEFAULT_GRAPH_PATH) -> Graph:
    data = json.loads(Path(path).read_text())
    graph = Graph()
    for n in data["nodes"]:
        graph.add_node(Node(
            id=n["id"], type=NodeType(n["type"]), name=n["name"],
            domain=n.get("domain"), summary=n.get("summary", ""),
            summary_tokens=n.get("summary_tokens", 0),
            documentation=n.get("documentation", []), metadata=n.get("metadata", {}),
        ))
    for e in data["edges"]:
        graph.add_edge(Edge(
            type=EdgeType(e["type"]), src=e["src"], dst=e["dst"],
            attributes=e.get("attributes", {}),
            confidence=Confidence(e.get("confidence", "confirmed")),
            source=Source(e.get("source", "static")), weight=e.get("weight", 1.0),
        ))
    graph.build_index()
    return graph

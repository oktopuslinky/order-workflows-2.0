"""Typed node/edge model for the context-hub knowledge graph.

This is the foundation the rest of v2 builds on. It encodes the two-layer model:

  Layer 1 (business flow):  DOMAIN -> SUBDOMAIN -> STAGE
  Layer 2 (relational):     STAGE  -> SERVICE -> ENDPOINT -> SCHEMA, plus docs

Two distinct kinds of connection (see the plan doc):
  * CONTAINS  — hierarchy (parent contains child); the vertical axis.
  * everything else — relationships (the horizontal axis), e.g. DEPENDS_ON.

Every node is a self-describing container (summary + documentation + metadata +
cache). Every edge carries confidence and provenance so trust is explicit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    DOMAIN = "Domain"
    SUBDOMAIN = "Subdomain"
    STAGE = "Stage"          # a business-flow stage (WorkflowStage in the plan)
    DATA_ARTIFACT = "DataArtifact"  # a business object that flows between stages
    JOURNEY = "Journey"      # a curated end-to-end business path across domains
    SERVICE = "Service"
    COMPONENT = "Component"  # a declared component id (CMP-*), bridged to code
    ENDPOINT = "Endpoint"
    SCHEMA = "Schema"
    DOCUMENT = "Document"
    CONFIG = "Config"
    TEAM = "Team"
    # Backlog / traceability types, recovered from `PREFIX-Identifier` tokens
    # that thread the prose of a corpus (see bootstrap/idlinks.py). Each is an
    # entity in its own right, not a mention: one node per id, shared by every
    # artifact that names it.
    REQUIREMENT = "Requirement"  # REQ-*
    USER_STORY = "UserStory"     # US-*
    TEST_CASE = "TestCase"       # TC-*
    EPIC = "Epic"                # EPIC-*
    TERM = "Term"                # TERM-*, a glossary entry
    # Code-oriented types (populated by ingest.py from a real repo)
    REPOSITORY = "Repository"
    MODULE = "Module"        # a source file
    FUNCTION = "Function"
    CLASS = "Class"
    CHUNK = "Chunk"          # line-range span inside a Module/Document (retrieval unit)


class EdgeType(str, Enum):
    # Hierarchy (vertical / containment)
    CONTAINS = "CONTAINS"
    # Business flow (horizontal)
    PRECEDES = "PRECEDES"
    TRIGGERS = "TRIGGERS"
    FLOWS_TO = "FLOWS_TO"        # Stage -> Stage, derived from shared data artifacts
    NEXT = "NEXT"               # Stage -> Stage, curated journey order (business view)
    PRODUCES = "PRODUCES"        # Stage -> DataArtifact (an output)
    CONSUMES = "CONSUMES"        # Stage -> DataArtifact (an input)
    # Technical relationships (horizontal)
    REALIZES = "REALIZES"        # Service -> Stage
    CALLS = "CALLS"
    IMPLEMENTS = "IMPLEMENTS"    # Service -> Endpoint
    USES_SCHEMA = "USES_SCHEMA"
    DEPENDS_ON = "DEPENDS_ON"    # may be CROSS-DOMAIN / CROSS-SERVICE (any layer)
    READS_CONFIG = "READS_CONFIG"
    DOCUMENTED_BY = "DOCUMENTED_BY"
    RELATES_TO = "RELATES_TO"    # lateral link between peers, e.g. Document <-> Document
    OWNED_BY = "OWNED_BY"
    IMPORTS = "IMPORTS"          # module -> module/package (from import statements)


# Canonical edge groupings for the unified graph model. These are additive helpers
# used by retrieval/inference to reason about workflow vs code vs impact paths
# without changing the underlying graph.json shape.
WORKFLOW_EDGE_TYPES = {
    EdgeType.CONTAINS, EdgeType.PRECEDES, EdgeType.TRIGGERS,
    EdgeType.FLOWS_TO, EdgeType.NEXT, EdgeType.PRODUCES, EdgeType.CONSUMES,
    EdgeType.REALIZES, EdgeType.DOCUMENTED_BY, EdgeType.RELATES_TO,
}
CODE_EDGE_TYPES = {
    EdgeType.CONTAINS, EdgeType.IMPLEMENTS, EdgeType.USES_SCHEMA,
    EdgeType.DEPENDS_ON, EdgeType.READS_CONFIG, EdgeType.IMPORTS, EdgeType.CALLS,
    EdgeType.NEXT, EdgeType.RELATES_TO,
}
IMPACT_EDGE_TYPES = {
    EdgeType.DEPENDS_ON, EdgeType.CALLS, EdgeType.IMPORTS, EdgeType.TRIGGERS,
    EdgeType.READS_CONFIG, EdgeType.DOCUMENTED_BY, EdgeType.RELATES_TO,
}
POINTER_METADATA_KEYS = (
    "path", "repo_path", "file", "extract_path", "language", "extension",
    "topics", "entities", "doc_type", "process", "process_id",
    "start_line", "end_line", "chunk_index", "symbol", "parent_id",
)


class Confidence(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"


class Source(str, Enum):
    STATIC = "static"    # pure static analysis / declared in spec
    PARSED = "parsed"    # parsed from a structured file
    LLM = "llm"          # inferred by a model


@dataclass
class Node:
    """A typed, self-describing entity in the graph."""

    id: str
    type: NodeType
    name: str
    domain: str | None = None                       # owning domain id (for partitioning)
    summary: str = ""                               # pre-computed once; served at query time
    summary_tokens: int = 0                         # cost used by token-budgeted assembly
    documentation: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)  # k-hop neighborhoods, rollups, etc.


@dataclass
class Edge:
    """A typed, attributed, provenance-tagged relationship."""

    type: EdgeType
    src: str                                        # source node id
    dst: str                                        # destination node id
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: Confidence = Confidence.CONFIRMED
    source: Source = Source.STATIC
    weight: float = 1.0                             # used by weighted traversal / pruning


@dataclass
class Graph:
    """In-memory graph with optional adjacency index for fast traversal."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    _adj_out: dict[str, list[tuple[Edge, str]]] = field(default_factory=dict, repr=False)
    _adj_in: dict[str, list[tuple[Edge, str]]] = field(default_factory=dict, repr=False)
    _indexed: bool = field(default=False, repr=False)

    def add_node(self, node: Node) -> Node:
        self.nodes.setdefault(node.id, node)
        self._indexed = False
        return self.nodes[node.id]

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)
        self._indexed = False

    def build_index(self) -> None:
        """Precompute bidirectional adjacency for O(degree) traversal."""
        self._adj_out.clear()
        self._adj_in.clear()
        for e in self.edges:
            if e.src in self.nodes and e.dst in self.nodes:
                self._adj_out.setdefault(e.src, []).append((e, e.dst))
                self._adj_in.setdefault(e.dst, []).append((e, e.src))
        self._indexed = True

    def _ensure_index(self) -> None:
        if not self._indexed:
            self.build_index()

    def incident(self, node_id: str) -> list[tuple[Edge, str]]:
        """All edges touching node_id, paired with the node on the other end."""
        self._ensure_index()
        out: list[tuple[Edge, str]] = list(self._adj_out.get(node_id, []))
        out.extend(self._adj_in.get(node_id, []))
        return out

    def neighbors(self, node_id: str, *, etypes: set[EdgeType] | None = None) -> list[Edge]:
        """Outgoing edges from a node, optionally filtered by edge type."""
        self._ensure_index()
        return [
            e for e, _ in self._adj_out.get(node_id, [])
            if etypes is None or e.type in etypes
        ]

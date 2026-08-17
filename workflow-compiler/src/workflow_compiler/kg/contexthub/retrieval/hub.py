"""The context hub: prompt -> minimal sufficient context.

Three stages (see the plan doc, sections 4 and 5):

  1. anchor   — resolve the prompt to entry node(s). This implementation is
                deterministic and offline: it scores nodes by keyword/id/path
                overlap with the prompt. (Embeddings are a later drop-in for the
                fuzzy natural-language case.)
  2. traverse — bounded breadth-first expansion from the anchors over the graph,
                BOTH directions, so we capture "what this depends on" AND "what
                depends on this" (impact analysis). Pure graph op: zero tokens.
  3. assemble — token-budgeted packing (greedy 0/1 knapsack): add the most
                relevant node summaries (closest hop, then highest degree) until
                the token cap is reached.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .index import get_index, query_token_set as _tokens
from ..model.schema import Edge, EdgeType, Graph, Node


@dataclass
class ContextPacket:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    total_tokens: int = 0
    seeds: list[str] = field(default_factory=list)
    hops: dict[str, int] = field(default_factory=dict)


def anchor_scored(graph: Graph, prompt: str, *, k: int = 3) -> list[tuple[str, float]]:
    """Resolve a prompt to scored entry nodes via inverted-index BM25."""
    return get_index(graph).score(prompt, k=k)


def anchor(graph: Graph, prompt: str, *, k: int = 3) -> list[str]:
    """Resolve a prompt to entry node ids (BM25-ranked)."""
    return [nid for nid, _ in anchor_scored(graph, prompt, k=k)]


def query_terms(graph: Graph, prompt: str) -> list[tuple[str, float]]:
    """Prompt terms that exist in the corpus, with their IDF (rare = high)."""
    return get_index(graph).query_terms(prompt)


def _incident_edges(graph: Graph, node_id: str) -> list[tuple[Edge, str]]:
    """All edges touching node_id, paired with the node on the other end."""
    return graph.incident(node_id)


def traverse(graph: Graph, seeds: list[str], *, max_hops: int = 2) -> tuple[Graph, dict[str, int]]:
    """Bounded BFS (both directions) from seeds into a relevant subgraph."""
    hops: dict[str, int] = {s: 0 for s in seeds if s in graph.nodes}
    queue: deque[str] = deque(hops)
    while queue:
        cur = queue.popleft()
        if hops[cur] >= max_hops:
            continue
        for _edge, other in _incident_edges(graph, cur):
            if other not in hops:
                hops[other] = hops[cur] + 1
                queue.append(other)

    sub = Graph()
    for nid in hops:
        sub.add_node(graph.nodes[nid])
    for e in graph.edges:
        if e.src in hops and e.dst in hops:
            sub.add_edge(e)
    return sub, hops


def assemble(subgraph: Graph, hops: dict[str, int], *, token_budget: int = 1500) -> ContextPacket:
    """Greedy token-budgeted packing: closest hop first, then highest degree."""
    degree: dict[str, int] = {nid: 0 for nid in subgraph.nodes}
    for e in subgraph.edges:
        degree[e.src] = degree.get(e.src, 0) + 1
        degree[e.dst] = degree.get(e.dst, 0) + 1

    ranked = sorted(
        subgraph.nodes.values(),
        key=lambda n: (hops.get(n.id, 99), -degree.get(n.id, 0), n.id),
    )

    packet = ContextPacket(hops=hops)
    chosen: set[str] = set()
    for node in ranked:
        cost = node.summary_tokens or 1
        if packet.total_tokens + cost > token_budget:
            continue
        packet.nodes.append(node)
        packet.total_tokens += cost
        chosen.add(node.id)
    packet.edges = [e for e in subgraph.edges if e.src in chosen and e.dst in chosen]
    return packet


def ask(graph: Graph, prompt: str, *, max_hops: int = 2, token_budget: int = 1500,
        k: int = 3) -> ContextPacket:
    """End-to-end: anchor -> traverse -> assemble."""
    seeds = anchor(graph, prompt, k=k)
    subgraph, hops = traverse(graph, seeds, max_hops=max_hops)
    packet = assemble(subgraph, hops, token_budget=token_budget)
    packet.seeds = seeds
    return packet


# --------------------------------------------------------------------------- #
# Chain extraction: pull the EXACT branch as context memory.
#
# `ask` resolves a fuzzy prompt to a k-hop ball. `chain` instead follows the
# directed relationships from a known seed to extract the precise connected
# branch — the flow it is part of, the services that run it, what those depend
# on, and the sub-nodes (endpoints/schemas/docs/configs) — then packs it to a
# token budget. The point is to hand an LLM only the relevant slice instead of
# the whole graph, cutting input tokens dramatically.
# --------------------------------------------------------------------------- #

# Relationships that constitute "the flow / dependency chain" (followed by hop).
_CHAIN_FLOW = {
    EdgeType.NEXT, EdgeType.FLOWS_TO, EdgeType.PRECEDES, EdgeType.TRIGGERS,
    EdgeType.REALIZES, EdgeType.DEPENDS_ON, EdgeType.CALLS, EdgeType.IMPORTS,
}
# Sub-node attachments pulled in for any node already on the chain.
_CHAIN_SUBNODE = {
    EdgeType.CONTAINS, EdgeType.IMPLEMENTS, EdgeType.USES_SCHEMA,
    EdgeType.DOCUMENTED_BY, EdgeType.READS_CONFIG, EdgeType.PRODUCES,
    EdgeType.CONSUMES, EdgeType.RELATES_TO,
}


@dataclass
class ChainPacket:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    hops: dict[str, int] = field(default_factory=dict)
    seed: str = ""
    direction: str = "down"
    total_tokens: int = 0
    full_tokens: int = 0
    reached: int = 0          # nodes reached before budgeting


def chain(graph: Graph, seed: str, *, direction: str = "down",
          token_budget: int = 2000, with_subnodes: bool = True,
          max_hops: int = 8) -> ChainPacket:
    """Extract the connected branch from `seed` as a token-budgeted packet.

    direction: 'down' (what this leads to / depends on), 'up' (what leads here /
    depends on this — impact), or 'both'.
    """
    out_adj: dict[str, list[Edge]] = defaultdict(list)
    in_adj: dict[str, list[Edge]] = defaultdict(list)
    for e in graph.edges:
        out_adj[e.src].append(e)
        in_adj[e.dst].append(e)

    hops: dict[str, int] = {seed: 0} if seed in graph.nodes else {}
    order: list[str] = [seed] if seed in graph.nodes else []
    queue: deque[str] = deque(order)
    while queue:
        cur = queue.popleft()
        if hops[cur] >= max_hops:
            continue
        nbrs: list[str] = []
        if direction in ("down", "both"):
            nbrs += [e.dst for e in out_adj[cur] if e.type in _CHAIN_FLOW]
        if direction in ("up", "both"):
            # Going up follows the flow in reverse AND climbs sub-node edges, so
            # the impact of a shared sub-node reaches every parent that uses it.
            nbrs += [e.src for e in in_adj[cur]
                     if e.type in _CHAIN_FLOW or e.type in _CHAIN_SUBNODE]
        for nxt in nbrs:
            if nxt in graph.nodes and nxt not in hops:
                hops[nxt] = hops[cur] + 1
                order.append(nxt)
                queue.append(nxt)

    if with_subnodes and direction in ("down", "both"):
        for nid in list(order):
            for e in out_adj[nid]:
                if e.type in _CHAIN_SUBNODE and e.dst in graph.nodes and e.dst not in hops:
                    hops[e.dst] = hops[nid] + 1
                    order.append(e.dst)

    reached = len(order)
    chosen: list[str] = []
    total = 0
    for nid in sorted(order, key=lambda n: (hops[n], n)):
        cost = graph.nodes[nid].summary_tokens or 1
        if total + cost > token_budget:
            continue
        chosen.append(nid)
        total += cost
    chosen_set = set(chosen)
    edges = [e for e in graph.edges if e.src in chosen_set and e.dst in chosen_set]
    full_tokens = sum((n.summary_tokens or 1) for n in graph.nodes.values())
    return ChainPacket(
        nodes=[graph.nodes[n] for n in chosen], edges=edges, hops=hops,
        seed=seed, direction=direction, total_tokens=total,
        full_tokens=full_tokens, reached=reached,
    )

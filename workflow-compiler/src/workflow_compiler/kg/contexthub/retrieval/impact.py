"""Shared impact scan — the single implementation behind ``kg.get_impact``.

Both the agent registry (contexthub/agent/tools.py) and the MCP projection
(contexthub/interface/mcp_server.py) used to carry a copy of this scan; they now
both call :func:`impact_scan`.
"""
from __future__ import annotations

from typing import Any

from . import hub as hub_mod

_IMPACT_EDGE_TYPES = ("DEPENDS_ON", "CALLS", "TRIGGERS", "IMPORTS")


def impact_scan(graph: Any, node_id: str, *, budget: int = 1200):
    """Return ``(dependents, chain_packet)`` for a node.

    ``dependents`` are the sorted ids of nodes with a direct dependency edge onto
    ``node_id``; the packet is a token-budgeted upward chain from it.
    """
    dependents = sorted(
        {
            e.src
            for e in graph.edges
            if e.dst == node_id and e.type.value in _IMPACT_EDGE_TYPES
        }
    )
    packet = hub_mod.chain(graph, node_id, direction="up", token_budget=budget)
    return dependents, packet

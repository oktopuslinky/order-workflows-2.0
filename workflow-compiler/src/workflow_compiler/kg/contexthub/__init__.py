"""Vendored subset of Context Hub (``contexthub``) — see ``VENDORED.md``.

Only the three pure-Python layers needed to build and query a graph are kept:

    model      Layer 0 — typed graph schema
    bootstrap  Layer 1 — repo scan → graph.json (+ optional LLM enrichment)
    retrieval  Layer 2 — prompt → context packet

The upstream ``interface`` / ``hub`` / ``agent`` / ``viz`` layers are not
vendored. This subpackage is excluded from ``mypy --strict``; the typed façade
is :mod:`workflow_compiler.kg.service`.
"""

__version__ = "2.0.0+wc"

from . import bootstrap, model, retrieval

__all__ = ["__version__", "bootstrap", "model", "retrieval"]

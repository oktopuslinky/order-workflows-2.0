"""Bootstrap a production repository into a context-hub graph.

Orchestrates static ingest (Wave 1) and optional merge of curated domain YAML.
Output: graph.json + manifest.json under .contexthub/ (or custom out dir).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .build import build as build_graph
from .enrich import enrich_graph
from .ingest import ingest
from .llm import JsonChatClient, LlmConfig
from .store import save
from ..model.schema import Graph
from ..retrieval.index import invalidate_cache


@dataclass
class InitResult:
    graph: Graph
    graph_path: Path
    manifest_path: Path
    manifest: dict[str, Any] = field(default_factory=dict)


def _git_commit(repo: Path) -> str | None:
    head = repo / ".git" / "HEAD"
    if not head.is_file():
        return None
    ref = head.read_text(encoding="utf-8").strip()
    if ref.startswith("ref: "):
        ref_path = repo / ".git" / ref[5:]
        if ref_path.is_file():
            return ref_path.read_text(encoding="utf-8").strip()[:12]
    return ref[:12] if ref else None


def init_repo(
    repo_path: Path,
    out_dir: Path | None = None,
    *,
    merge_domains_dir: Path | None = None,
    include_functions: bool = True,
    max_defs_per_module: int = 60,
    include_chunks: bool = True,
    max_chunks_per_file: int = 40,
    llm_config: LlmConfig | None = None,
    verbose: bool = False,
    llm_client: JsonChatClient | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> InitResult:
    """Index a production repo into graph.json (primary bootstrap entry point).

    workflow-compiler edit: ``llm_client`` enables enrichment through an injected
    JSON-chat client (no ``LlmConfig``/HTTP needed); ``on_progress`` receives
    ``(label, done, total)`` during enrichment.
    """
    repo_path = Path(repo_path).resolve()
    out = out_dir or (repo_path / ".contexthub")
    out.mkdir(parents=True, exist_ok=True)

    graph = ingest(
        repo_path,
        verbose=verbose,
        include_functions=include_functions,
        max_defs_per_module=max_defs_per_module,
        include_chunks=include_chunks,
        max_chunks_per_file=max_chunks_per_file,
        cache_dir=out / "extracts",
    )

    if llm_config or llm_client:
        if verbose:
            print("  running LLM enrichment (summaries + topic links)...")
        graph = enrich_graph(
            graph, repo_path, llm_config,
            contexthub_dir=out, verbose=verbose,
            client=llm_client, on_progress=on_progress,
        )

    if merge_domains_dir and Path(merge_domains_dir).exists():
        curated = build_graph(domains_dir=Path(merge_domains_dir), verbose=verbose)
        graph = _merge_graphs(graph, curated)

    graph.build_index()
    invalidate_cache()

    graph_path = out / "graph.json"
    save(graph, graph_path)

    commit = _git_commit(repo_path)
    manifest = {
        "version": "1.0",
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        # Top-level too: the Hub records this as kg_registry.indexed_commit and
        # diffs the next re-index against it. Without it every re-index compares
        # against nothing and looks like a whole-repo change.
        "git_commit": commit,
        "repo": {
            "path": str(repo_path),
            "name": repo_path.name,
            "commit": commit,
        },
        "stats": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "domains": len({n.domain for n in graph.nodes.values() if n.domain}),
        },
        "graph": graph_path.name,
        "options": {
            "include_functions": include_functions,
            "include_chunks": include_chunks,
            "max_chunks_per_file": max_chunks_per_file,
            "merge_domains": str(merge_domains_dir) if merge_domains_dir else None,
            "llm_enrich": llm_config is not None or llm_client is not None,
        },
    }
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if verbose:
        print(f"  manifest -> {manifest_path}")

    return InitResult(
        graph=graph,
        graph_path=graph_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def _merge_graphs(base: Graph, overlay: Graph) -> Graph:
    """Add curated business nodes/edges from domain YAML onto a code graph."""
    for node in overlay.nodes.values():
        if node.id not in base.nodes:
            base.add_node(node)
    existing = {(e.type, e.src, e.dst) for e in base.edges}
    for edge in overlay.edges:
        key = (edge.type, edge.src, edge.dst)
        if key not in existing:
            base.add_edge(edge)
            existing.add(key)
    return base

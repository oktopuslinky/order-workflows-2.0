"""LLM enrichment: per-file summaries, topic/entity nodes, cross-file RELATES_TO links."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

from .build import est_tokens
from .formats import clip_for_llm
from .cluster import cluster_processes
from .llm import JsonChatClient, LlmClient, LlmConfig, LlmError
from ..model.schema import Confidence, Edge, EdgeType, Graph, Node, NodeType, Source

_FILE_NODE_TYPES = {NodeType.DOCUMENT, NodeType.MODULE}
_TOPIC_PREFIX = "topic:"
_ENTITY_PREFIX = "entity:"

_SYSTEM = """You analyze repository files for a knowledge graph.
Return ONLY valid JSON with this shape:
{
  "summary": "2-3 sentences describing what this file contains and its role",
  "topics": ["short topic phrases shared across enterprise docs/code"],
  "entities": ["named systems, APIs, components, processes, or requirements mentioned"],
  "doc_type": "code|api_spec|brd|tdd|aid|test|config|sequence|data|other"
}
Rules:
- topics: 3-8 concise phrases (2-6 words) that could appear in OTHER files too
- entities: proper nouns, API names, service names, requirement IDs
- Use the file path only as context, do not invent facts not in the content
"""


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s[:96] or "unknown"


def _cache_path(cache_dir: Path, node_id: str, content_hash: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", node_id)[:120]
    return cache_dir / f"{safe}.{content_hash[:16]}.json"


def _load_extract(repo_root: Path, contexthub_dir: Path, metadata: dict) -> str:
    rel = metadata.get("extract_path")
    if rel:
        p = contexthub_dir / rel
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="ignore")
    repo_path = metadata.get("repo_path") or metadata.get("path")
    if repo_path:
        from .formats import extract_text
        return extract_text(repo_root / repo_path)
    return ""


def enrich_graph(
    graph: Graph,
    repo_root: Path,
    config: LlmConfig | None,
    *,
    contexthub_dir: Path | None = None,
    verbose: bool = False,
    client: JsonChatClient | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> Graph:
    """Run LLM over every file node; create topic/entity nodes and link shared concepts.

    workflow-compiler edit: ``client`` injects any object with
    ``chat_json(messages, *, label, retries) -> dict`` (see
    :class:`~workflow_compiler.kg.llm_bridge.ProviderJsonClient`); when omitted an
    HTTP :class:`LlmClient` is built from ``config`` as upstream. ``on_progress``
    is called as ``(node_id, done, total)`` before each file is enriched.
    """
    repo_root = Path(repo_root).resolve()
    hub_dir = contexthub_dir or (repo_root / ".contexthub")
    cache_dir = hub_dir / "llm_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if client is None:
        if config is None:
            raise ValueError("enrich_graph needs either an LLM client or an LlmConfig")
        client = LlmClient(config)
    file_nodes = [n for n in graph.nodes.values() if n.type in _FILE_NODE_TYPES]
    total_files = len(file_nodes)
    topic_registry: dict[str, str] = {}
    entity_registry: dict[str, str] = {}

    # Pre-register existing topic/entity nodes
    for nid in graph.nodes:
        if nid.startswith(_TOPIC_PREFIX):
            topic_registry[nid[len(_TOPIC_PREFIX):]] = nid
        elif nid.startswith(_ENTITY_PREFIX):
            entity_registry[nid[len(_ENTITY_PREFIX):]] = nid

    enriched = 0
    for index, node in enumerate(file_nodes, start=1):
        if on_progress is not None:
            on_progress(node.id, index, total_files)
        text = _load_extract(repo_root, hub_dir, node.metadata or {})
        if not text or len(text.strip()) < 20:
            continue

        content_hash = hashlib.sha256(text.encode()).hexdigest()
        cache_file = _cache_path(cache_dir, node.id, content_hash)
        if cache_file.is_file():
            result = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            clipped = clip_for_llm(text)
            path_hint = (node.metadata or {}).get("path", node.name)
            try:
                result = client.chat_json([
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": (
                        f"File path: {path_hint}\n"
                        f"Node type: {node.type.value}\n\n"
                        f"--- content ---\n{clipped}"
                    )},
                ], label=node.id)
            except LlmError as exc:
                if verbose:
                    print(f"  llm skip {node.id}: {exc}")
                continue
            cache_file.write_text(json.dumps(result, indent=2), encoding="utf-8")

        summary = str(result.get("summary") or node.summary or "").strip()
        topics = [str(t).strip() for t in (result.get("topics") or []) if str(t).strip()]
        entities = [str(e).strip() for e in (result.get("entities") or []) if str(e).strip()]
        doc_type = str(result.get("doc_type") or "other").strip()

        md = dict(node.metadata or {})
        md["topics"] = topics
        md["entities"] = entities
        md["doc_type"] = doc_type
        md["llm_enriched"] = True
        node.summary = summary
        node.summary_tokens = est_tokens(summary)
        node.metadata = md
        enriched += 1

        repo_id = next(
            (n.id for n in graph.nodes.values() if n.type == NodeType.REPOSITORY),
            None,
        )

        for topic in topics:
            slug = _slug(topic)
            tid = topic_registry.get(slug)
            if not tid:
                tid = f"{_TOPIC_PREFIX}{slug}"
                topic_registry[slug] = tid
                graph.add_node(Node(
                    tid, NodeType.DATA_ARTIFACT, topic,
                    domain=node.domain,
                    summary=f"Topic: {topic}",
                    summary_tokens=est_tokens(topic),
                    metadata={"kind": "topic", "label": topic},
                ))
                if repo_id:
                    graph.add_edge(Edge(EdgeType.CONTAINS, repo_id, tid, source=Source.LLM))
            graph.add_edge(Edge(
                EdgeType.RELATES_TO, node.id, tid,
                attributes={"link": "mentions_topic", "topic": topic},
                confidence=Confidence.INFERRED, source=Source.LLM,
            ))

        for entity in entities:
            slug = _slug(entity)
            eid = entity_registry.get(slug)
            if not eid:
                eid = f"{_ENTITY_PREFIX}{slug}"
                entity_registry[slug] = eid
                graph.add_node(Node(
                    eid, NodeType.DATA_ARTIFACT, entity,
                    domain=node.domain,
                    summary=f"Entity: {entity}",
                    summary_tokens=est_tokens(entity),
                    metadata={"kind": "entity", "label": entity},
                ))
                if repo_id:
                    graph.add_edge(Edge(EdgeType.CONTAINS, repo_id, eid, source=Source.LLM))
            graph.add_edge(Edge(
                EdgeType.RELATES_TO, node.id, eid,
                attributes={"link": "mentions_entity", "entity": entity},
                confidence=Confidence.INFERRED, source=Source.LLM,
            ))

    if on_progress is not None:
        on_progress("process clustering", total_files, total_files)
    graph = cluster_processes(
        graph, config, cache_dir=cache_dir, verbose=verbose, client=client,
    )

    graph.build_index()
    if verbose:
        topics_n = sum(1 for n in graph.nodes.values() if n.id.startswith(_TOPIC_PREFIX))
        entities_n = sum(1 for n in graph.nodes.values() if n.id.startswith(_ENTITY_PREFIX))
        relates = sum(1 for e in graph.edges if e.type == EdgeType.RELATES_TO)
        print(f"  llm enriched {enriched} files -> {topics_n} topics, "
              f"{entities_n} entities, {relates} RELATES_TO edges")
    return graph

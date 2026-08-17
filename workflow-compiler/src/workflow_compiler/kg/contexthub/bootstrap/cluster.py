"""LLM process clustering — group file nodes under Service (process) parents."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .build import est_tokens
from .llm import JsonChatClient, LlmClient, LlmConfig, LlmError
from ..model.schema import Confidence, Edge, EdgeType, Graph, Node, NodeType, Source

_PROCESS_PREFIX = "svc:proc:"
_FILE_TYPES = {NodeType.DOCUMENT, NodeType.MODULE}

_CLUSTER_SYSTEM = """You cluster repository files into business processes / microservices.
Each file belongs to exactly ONE primary process (the system it mainly describes or implements).

Return ONLY valid JSON:
{
  "processes": [
    {
      "id": "order-service",
      "name": "Order Service",
      "summary": "2 sentences: scope and main capabilities",
      "file_ids": ["doc:brd_order_management.docx", "mod:src/order/handler.py"],
      "depends_on": ["billing-service"]
    }
  ],
  "unassigned": []
}

Rules:
- Group BRD + TDD + AID + OpenAPI + CSV + sequence + code for the SAME system together
- id: lowercase slug (order-service, billing-service)
- file_ids: must be from the provided list exactly
- depends_on: optional slugs of other processes this one calls or relies on
- Every file should appear in exactly one process unless truly cross-cutting (then pick best fit)
"""


def _slug(value: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s[:96] or "unknown"


def _file_manifest(graph: Graph) -> list[dict]:
    rows: list[dict] = []
    for n in graph.nodes.values():
        if n.type not in _FILE_TYPES:
            continue
        md = n.metadata or {}
        rows.append({
            "file_id": n.id,
            "path": md.get("path") or n.name,
            "doc_type": md.get("doc_type", "other"),
            "summary": (n.summary or "")[:400],
            "entities": (md.get("entities") or [])[:8],
        })
    return rows


def _catalog_lines(batch: list[dict]) -> str:
    lines = []
    for row in batch:
        ents = ", ".join(row["entities"][:4]) if row["entities"] else "-"
        summary = row["summary"][:200]
        lines.append(
            f"- {row['file_id']} ({row['doc_type']}): {summary}\n  entities: {ents}"
        )
    return "\n".join(lines)


def _merge_processes(accum: dict[str, dict], batch_result: dict) -> None:
    for proc in batch_result.get("processes") or []:
        slug = _slug(str(proc.get("id") or proc.get("name") or "unknown"))
        if slug not in accum:
            accum[slug] = {
                "id": slug,
                "name": proc.get("name", slug),
                "summary": proc.get("summary", ""),
                "file_ids": list(proc.get("file_ids") or []),
                "depends_on": list(proc.get("depends_on") or []),
            }
        else:
            cur = accum[slug]
            cur["file_ids"].extend(proc.get("file_ids") or [])
            for dep in proc.get("depends_on") or []:
                if dep not in cur["depends_on"]:
                    cur["depends_on"].append(dep)
            if len(str(proc.get("summary") or "")) > len(str(cur.get("summary") or "")):
                cur["summary"] = proc.get("summary", "")


def _tokens(*values: str) -> set[str]:
    out: set[str] = set()
    for value in values:
        out.update({t for t in re.findall(r"[a-z0-9]+", value.lower()) if len(t) >= 3})
    return out


def _reconcile_unassigned(graph: Graph, processes: list[dict]) -> list[dict]:
    if not processes:
        return processes
    proc_terms: dict[str, set[str]] = {}
    proc_by_slug: dict[str, dict] = {}
    for proc in processes:
        slug = _slug(str(proc.get("id") or proc.get("name") or "unknown"))
        proc_by_slug[slug] = proc
        proc_terms[slug] = _tokens(
            slug, str(proc.get("name") or ""), str(proc.get("summary") or "")
        )
    already = {fid for proc in processes for fid in (proc.get("file_ids") or [])}
    for node in graph.nodes.values():
        if node.type not in _FILE_TYPES or node.id in already:
            continue
        md = node.metadata or {}
        text_terms = _tokens(
            node.name, str(md.get("path") or ""), node.summary,
            " ".join(md.get("topics") or []), " ".join(md.get("entities") or []),
        )
        best_slug = ""
        best_score = 0
        for slug, terms in proc_terms.items():
            score = len(text_terms & terms)
            if slug in str(md.get("path") or "").lower():
                score += 2
            if score > best_score:
                best_slug = slug
                best_score = score
        if best_slug and best_score > 0:
            proc_by_slug[best_slug].setdefault("file_ids", []).append(node.id)
    return list(proc_by_slug.values())


def _cluster_batched(
    client: JsonChatClient,
    manifest: list[dict],
    *,
    batch_size: int = 12,
    verbose: bool = False,
) -> dict:
    """Cluster in batches to stay within model context limits."""
    merged: dict[str, dict] = {}
    for i in range(0, len(manifest), batch_size):
        batch = manifest[i : i + batch_size]
        catalog = _catalog_lines(batch)
        part = None
        for attempt, size in enumerate((batch_size, max(batch_size // 2, 6))):
            if attempt and len(batch) > size:
                for j in range(0, len(batch), size):
                    sub = batch[j : j + size]
                    try:
                        sub_part = client.chat_json([
                            {"role": "system", "content": _CLUSTER_SYSTEM},
                            {"role": "user", "content": (
                                f"Cluster these {len(sub)} files.\n\n--- files ---\n"
                                f"{_catalog_lines(sub)}"
                            )},
                        ], label=f"process_cluster_{i // batch_size + 1}_{j // size + 1}")
                        _merge_processes(merged, sub_part)
                    except LlmError as exc:
                        if verbose:
                            print(f"  process cluster sub-batch skip: {exc}")
                part = {"processes": list(merged.values())}
                break
            try:
                part = client.chat_json([
                    {"role": "system", "content": _CLUSTER_SYSTEM},
                    {"role": "user", "content": (
                        f"Batch {i // batch_size + 1}: cluster these {len(batch)} files "
                        f"(part of {len(manifest)} total).\n\n--- files ---\n{catalog}"
                    )},
                ], label=f"process_cluster_{i // batch_size + 1}")
                break
            except LlmError as exc:
                if attempt == 0 and verbose:
                    print(f"  process cluster batch {i // batch_size + 1} retry smaller: {exc}")
                elif verbose:
                    print(f"  process cluster batch {i // batch_size + 1} skip: {exc}")
        if part:
            _merge_processes(merged, part)
    return {"processes": list(merged.values()), "unassigned": []}


def cluster_processes(
    graph: Graph,
    config: LlmConfig | None,
    *,
    cache_dir: Path,
    verbose: bool = False,
    client: JsonChatClient | None = None,
) -> Graph:
    """Second LLM pass: create Service process nodes; CONTAINS file artifacts.

    workflow-compiler edit: ``client`` may be injected (see ``enrich_graph``).
    """
    manifest = _file_manifest(graph)
    if len(manifest) < 2:
        return graph

    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()
    cache_file = cache_dir / f"process_clusters.{manifest_hash[:16]}.json"

    if client is None:
        if config is None:
            raise ValueError("cluster_processes needs either an LLM client or an LlmConfig")
        client = LlmClient(config)
    if cache_file.is_file():
        result = json.loads(cache_file.read_text(encoding="utf-8"))
        result["processes"] = _reconcile_unassigned(graph, result.get("processes") or [])
    else:
        result = _cluster_batched(client, manifest, verbose=verbose)
        if not result.get("processes"):
            if verbose:
                print("  process cluster skip: no batches succeeded")
            return graph
        result["processes"] = _reconcile_unassigned(graph, result.get("processes") or [])
        cache_file.write_text(json.dumps(result, indent=2), encoding="utf-8")

    repo_id = next(
        (n.id for n in graph.nodes.values() if n.type == NodeType.REPOSITORY),
        None,
    )
    valid_ids = {n.id for n in graph.nodes.values()}
    proc_id_by_slug: dict[str, str] = {}
    assigned: set[str] = set()

    for proc in result.get("processes") or []:
        slug = _slug(str(proc.get("id") or proc.get("name") or "unknown"))
        pid = f"{_PROCESS_PREFIX}{slug}"
        name = str(proc.get("name") or slug.replace("-", " ").title()).strip()
        summary = str(proc.get("summary") or f"Process: {name}").strip()
        proc_id_by_slug[slug] = pid

        if pid not in graph.nodes:
            graph.add_node(Node(
                pid, NodeType.SERVICE, name,
                domain=name,
                summary=summary,
                summary_tokens=est_tokens(summary),
                metadata={"kind": "process", "slug": slug, "llm_clustered": True},
            ))
            if repo_id:
                graph.add_edge(Edge(
                    EdgeType.CONTAINS, repo_id, pid, source=Source.LLM,
                ))

        for fid in proc.get("file_ids") or []:
            fid = str(fid).strip()
            if fid not in valid_ids or fid in assigned:
                continue
            file_node = graph.nodes[fid]
            assigned.add(fid)
            file_node.domain = name
            md = dict(file_node.metadata or {})
            md["process"] = slug
            md["process_id"] = pid
            file_node.metadata = md
            graph.add_edge(Edge(
                EdgeType.CONTAINS, pid, fid,
                attributes={"role": "artifact"},
                confidence=Confidence.INFERRED, source=Source.LLM,
            ))
            graph.add_edge(Edge(
                EdgeType.DOCUMENTED_BY, pid, fid,
                confidence=Confidence.INFERRED, source=Source.LLM,
            ))

    # Cross-process dependencies
    for proc in result.get("processes") or []:
        slug = _slug(str(proc.get("id") or proc.get("name") or ""))
        src_id = proc_id_by_slug.get(slug)
        if not src_id:
            continue
        for dep in proc.get("depends_on") or []:
            dep_slug = _slug(str(dep))
            dst_id = proc_id_by_slug.get(dep_slug)
            if dst_id and dst_id != src_id:
                graph.add_edge(Edge(
                    EdgeType.DEPENDS_ON, src_id, dst_id,
                    attributes={"reason": "process dependency"},
                    confidence=Confidence.INFERRED, source=Source.LLM,
                ))

    graph.build_index()
    if verbose:
        n_proc = sum(
            1 for n in graph.nodes.values()
            if n.type == NodeType.SERVICE and (n.metadata or {}).get("kind") == "process"
        )
        n_contains = sum(
            1 for e in graph.edges
            if e.type == EdgeType.CONTAINS
            and e.src.startswith(_PROCESS_PREFIX)
        )
        print(f"  process clusters: {n_proc} processes, {n_contains} artifact links, "
              f"{len(assigned)}/{len(manifest)} files assigned")
    return graph

"""Graduated (Gaussian) context assembly.

Given a prompt, decide the focus domain, then hand the model context shaped like a
bell curve centered on that focus:

    focus     the targeted domain/microservice  -> FULL  (real code + docs + sigs)
    connected domains 1 hop away                 -> SUMMARY (signatures only)
    rest      every other domain                 -> LINE  (one Domain.summary line)

Budget is split by a Gaussian weight per band, w(d) = exp(-d^2 / 2σ^2). The thin
one-line tail (awareness of every department) is always included first because it
is tiny; the remainder is split between focus and connected by w(0):w(1).

Built on top of `hub.anchor` / `hub.traverse`; the dereference into real files is
done by `fetcher`.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import fetcher
from ..bootstrap.build import est_tokens
from .fetcher import Level
from .hub import anchor_scored, query_terms, traverse
from .index import query_token_set as _hub_tokens
from ..model.schema import EdgeType, Graph, Node, NodeType

# Order in which to render focus nodes (most useful first).
_TYPE_RANK = {
    NodeType.SERVICE: 0, NodeType.STAGE: 1, NodeType.CHUNK: 2,
    NodeType.MODULE: 3, NodeType.ENDPOINT: 4, NodeType.FUNCTION: 5,
    NodeType.CLASS: 6, NodeType.SCHEMA: 7, NodeType.DOCUMENT: 8,
}
_SEED_TYPES = {
    NodeType.SERVICE, NodeType.STAGE, NodeType.CHUNK, NodeType.MODULE,
    NodeType.ENDPOINT, NodeType.FUNCTION, NodeType.CLASS, NodeType.SCHEMA,
    NodeType.DOCUMENT,
}
_SKIP_TYPES = {NodeType.DOMAIN, NodeType.TEAM, NodeType.JOURNEY, NodeType.DATA_ARTIFACT}
_CONNECTED_PER_DOMAIN = 3


@dataclass
class Section:
    band: str            # "focus" | "connected" | "rest"
    node_id: str
    text: str
    tokens: int
    path: str | None = None          # repo-relative file this section dereferenced
    start_line: int | None = None    # 1-indexed span, when the node is a line slice
    end_line: int | None = None


@dataclass
class FileRef:
    """A repo file that contributed content to the packet (packet provenance)."""
    path: str
    band: str                                       # strongest band citing it
    tokens: int = 0                                 # tokens contributed by its sections
    node_ids: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class ContextPacket:
    prompt: str
    seeds: list[str] = field(default_factory=list)
    focus_domain: str | None = None
    repo_root: str | None = None
    sections: list[Section] = field(default_factory=list)
    files: list[FileRef] = field(default_factory=list)
    total_tokens: int = 0
    rendered: str = ""
    band_budgets: dict[str, int] = field(default_factory=dict)
    coverage: float = 1.0                       # fraction of prompt signal grounded
    uncovered_terms: list[str] = field(default_factory=list)
    low_confidence: bool = False
    refinement_rounds: int = 0


_BAND_RANK = {"focus": 0, "connected": 1, "rest": 2}
# Types whose `path` metadata is a repo file. On an Endpoint `path` is an HTTP
# route, so it is read only from the unambiguous `repo_path`/`file` keys.
_FILE_PATH_TYPES = {
    NodeType.MODULE, NodeType.DOCUMENT, NodeType.CHUNK,
    NodeType.FUNCTION, NodeType.CLASS, NodeType.CONFIG,
}


def _node_file(node: Node, root: Path | None) -> tuple[str | None, int | None, int | None]:
    """Repo-relative file (+ line span) a node points at, or (None, None, None).

    Directory pointers (a Service's `repo_path`) are dropped: they are not a file
    the user can open, and the concrete entry file picked by the fetcher is an
    implementation detail of the render.
    """
    md = node.metadata or {}
    keys = ("path", "repo_path", "file") if node.type in _FILE_PATH_TYPES else ("repo_path", "file")
    ref = next((md[k] for k in keys if md.get(k)), None)
    if not ref:
        return None, None, None
    rel = str(ref).replace("\\", "/")
    if root is not None:
        target = root / rel
        if target.is_dir():
            return None, None, None
        if not target.is_file() and not Path(rel).suffix:
            return None, None, None
    elif not Path(rel).suffix:
        return None, None, None

    start = end = None
    try:
        s, e = int(md["start_line"]), int(md["end_line"])
        if s >= 1 and e >= s:
            start, end = s, e
    except (KeyError, TypeError, ValueError):
        pass
    return rel, start, end


def _make_section(band: str, node: Node, text: str, tokens: int, root: Path | None) -> Section:
    path, start, end = _node_file(node, root)
    return Section(band, node.id, text, tokens, path=path, start_line=start, end_line=end)


def _collect_files(sections: list[Section]) -> list[FileRef]:
    """Fold sections into one entry per file, strongest band wins."""
    by_path: dict[str, FileRef] = {}
    for s in sections:
        if not s.path:
            continue
        ref = by_path.get(s.path)
        if ref is None:
            ref = FileRef(path=s.path, band=s.band)
            by_path[s.path] = ref
        if _BAND_RANK.get(s.band, 9) < _BAND_RANK.get(ref.band, 9):
            ref.band = s.band
        ref.tokens += s.tokens
        if s.node_id not in ref.node_ids:
            ref.node_ids.append(s.node_id)
        if s.start_line and s.end_line:
            span = (s.start_line, s.end_line)
            if span not in ref.spans:
                ref.spans.append(span)
    for ref in by_path.values():
        ref.spans.sort()
    return sorted(
        by_path.values(),
        key=lambda f: (_BAND_RANK.get(f.band, 9), -f.tokens, f.path),
    )


def _gaussian(d: int, sigma: float) -> float:
    return math.exp(-(d * d) / (2.0 * sigma * sigma))


def _select_focus_domain(graph: Graph, scored: list[tuple[str, float]]) -> str | None:
    """Pick the focus domain by its single strongest match (max BM25), with the
    per-domain sum as a tiebreak.

    Max-primary matters: it lets a prompt's most discriminating hit decide the
    focus (e.g. 'device shipped' -> devices.inventory.ship) instead of letting a
    domain win on the *breadth* of a common word ('customer' appearing in many
    customer nodes). Type boosting in the scorer already dampens leaf flukes.
    """
    best: dict[str, float] = {}
    total: dict[str, float] = defaultdict(float)
    for nid, s in scored:
        n = graph.nodes.get(nid)
        if n and n.domain and n.domain != "shared":
            best[n.domain] = max(best.get(n.domain, 0.0), s)
            total[n.domain] += s
    if not best:
        return None
    return max(best, key=lambda d: (best[d], total[d], d))


def _domain_node(graph: Graph, domain: str) -> Node | None:
    n = graph.nodes.get(domain)
    if n and n.type == NodeType.DOMAIN:
        return n
    for nd in graph.nodes.values():
        if nd.type == NodeType.DOMAIN and nd.domain == domain:
            return nd
    return None


def _process_children(graph: Graph, process_id: str) -> list[str]:
    """Artifact node ids owned by a clustered process Service."""
    out: list[str] = []
    for e in graph.edges:
        if e.type == EdgeType.CONTAINS and e.src == process_id and e.dst in graph.nodes:
            child = graph.nodes[e.dst]
            if child.type in (NodeType.DOCUMENT, NodeType.MODULE):
                out.append(e.dst)
    return out


def _expand_process_seeds(graph: Graph, seeds: list[str]) -> list[str]:
    """When a process Service is seeded, include all its file artifacts."""
    expanded = list(seeds)
    seen = set(seeds)
    for sid in seeds:
        node = graph.nodes.get(sid)
        if not node or node.type != NodeType.SERVICE:
            continue
        if (node.metadata or {}).get("kind") != "process":
            continue
        for cid in _process_children(graph, sid):
            if cid not in seen:
                expanded.append(cid)
                seen.add(cid)
    return expanded


def _expand_chunk_seeds(graph: Graph, seeds: list[str], *, neighbor_hops: int = 1) -> list[str]:
    """Include NEXT-linked neighbor chunks so related spans travel together."""
    expanded = list(seeds)
    seen = set(seeds)
    frontier = [
        s for s in seeds
        if (n := graph.nodes.get(s)) is not None and n.type == NodeType.CHUNK
    ]
    for _ in range(max(neighbor_hops, 0)):
        nxt: list[str] = []
        for cid in frontier:
            for edge, other in graph.incident(cid):
                if edge.type != EdgeType.NEXT:
                    continue
                if other in seen:
                    continue
                on = graph.nodes.get(other)
                if not on or on.type != NodeType.CHUNK:
                    continue
                expanded.append(other)
                seen.add(other)
                nxt.append(other)
        frontier = nxt
        if not frontier:
            break
    return expanded


def _prompt_term_set(graph: Graph, prompt: str) -> set[str]:
    return {t for t, _ in query_terms(graph, prompt)}


def _pick_seeds(graph: Graph, scored: list[tuple[str, float]], k: int) -> list[str]:
    """Prefer concrete artifacts — chunks first — over topic/entity nodes."""
    picked: list[str] = []
    fallback: list[str] = []
    covered_files: set[str] = set()

    def _file_key(node: Node) -> str:
        md = node.metadata or {}
        return str(md.get("path") or md.get("repo_path") or md.get("file") or node.id)

    # Pass 1: prefer Chunk seeds (dedupe by file so one strong span wins).
    for nid, _ in scored:
        node = graph.nodes.get(nid)
        if not node or node.type != NodeType.CHUNK:
            continue
        fk = _file_key(node)
        if fk in covered_files:
            continue
        picked.append(nid)
        covered_files.add(fk)
        if len(picked) >= k:
            return picked[:k]

    # Pass 2: other seed types; skip Module/Document if a chunk from same file already picked.
    for nid, _ in scored:
        if nid in picked:
            continue
        node = graph.nodes.get(nid)
        if not node:
            continue
        if node.type in (NodeType.MODULE, NodeType.DOCUMENT):
            if _file_key(node) in covered_files:
                continue
        if node.type in _SEED_TYPES:
            picked.append(nid)
            if node.type in (NodeType.MODULE, NodeType.DOCUMENT, NodeType.CHUNK):
                covered_files.add(_file_key(node))
        elif node.type not in _SKIP_TYPES:
            fallback.append(nid)
        if len(picked) >= k:
            break
    if len(picked) < k:
        for nid in fallback:
            if nid not in picked:
                picked.append(nid)
            if len(picked) >= k:
                break
    return picked[:k]


def _focus_order(
    n: Node,
    *,
    hops: dict[str, int],
    seed_set: set[str],
    terms: set[str],
    root: Path | None,
) -> tuple:
    overlap = fetcher.node_term_overlap(root, n, terms) if terms else 0.0
    return (
        -overlap,
        hops.get(n.id, 9),
        n.id not in seed_set,
        _TYPE_RANK.get(n.type, 8),
        n.id,
    )


def _partition_bands(
    graph: Graph,
    sub: Graph,
    hops: dict[str, int],
    *,
    seeds: list[str],
    focus_domain: str | None,
) -> tuple[list[Node], list[Node], list[str]]:
    seed_set = set(seeds)
    focus_nodes: list[Node] = [
        n for n in sub.nodes.values()
        if n.type not in _SKIP_TYPES
        and ((n.domain == focus_domain) if focus_domain else (n.id in seed_set))
    ]
    focus_ids = {n.id for n in focus_nodes}

    cross: dict[str, list[Node]] = {}
    for e in graph.edges:
        pairs: list[Node] = []
        if e.src in focus_ids and e.dst in graph.nodes:
            pairs.append(graph.nodes[e.dst])
        if e.dst in focus_ids and e.src in graph.nodes:
            pairs.append(graph.nodes[e.src])
        for other in pairs:
            od = other.domain
            if not od or od in ("shared", focus_domain) or other.type in _SKIP_TYPES:
                continue
            bucket = cross.setdefault(od, [])
            if other.id not in {x.id for x in bucket}:
                bucket.append(other)

    connected_nodes: list[Node] = []
    for od in sorted(cross):
        ranked = sorted(cross[od], key=lambda n: (hops.get(n.id, 9),
                                                   _TYPE_RANK.get(n.type, 8), n.id))
        connected_nodes.extend(ranked[:_CONNECTED_PER_DOMAIN])

    connected_domains = set(cross)
    all_domains = {n.domain for n in graph.nodes.values() if n.domain and n.domain != "shared"}
    rest_domains = sorted(all_domains - {focus_domain} - connected_domains)
    return focus_nodes, connected_nodes, rest_domains


def _assemble_bands(
    graph: Graph,
    packet: ContextPacket,
    *,
    sub: Graph,
    hops: dict[str, int],
    root: Path | None,
    total_budget: int,
    sigma: float,
    terms: set[str],
    highlight_terms: set[str] | None = None,
) -> None:
    """Fill packet.sections and band_budgets from a traversed subgraph."""
    focus_nodes, connected_nodes, rest_domains = _partition_bands(
        graph, sub, hops, seeds=packet.seeds, focus_domain=packet.focus_domain,
    )
    seed_set = set(packet.seeds)

    tail_sections: list[Section] = []
    for dom in rest_domains:
        dnode = _domain_node(graph, dom)
        if not dnode:
            continue
        text, tok = fetcher.render(graph, dnode, Level.LINE)
        tail_sections.append(_make_section("rest", dnode, text, tok, root))
    tail_cost = sum(s.tokens for s in tail_sections)

    remaining = max(total_budget - tail_cost, total_budget // 2)
    w0, w1 = _gaussian(0, sigma), _gaussian(1, sigma)
    focus_budget = int(remaining * w0 / (w0 + w1))
    connected_budget = remaining - focus_budget
    packet.band_budgets = {"focus": focus_budget, "connected": connected_budget,
                           "rest": tail_cost}
    packet.sections = []

    # Prefer rendering Chunks; skip Module/Document FULL dump when a chunk from
    # the same file is already in the focus set (avoids duplicate whole-file cost).
    focus_file_chunks: set[str] = set()
    for n in focus_nodes:
        if n.type == NodeType.CHUNK:
            md = n.metadata or {}
            focus_file_chunks.add(str(md.get("path") or md.get("repo_path") or ""))

    used = 0
    for n in sorted(
        focus_nodes,
        key=lambda node: _focus_order(node, hops=hops, seed_set=seed_set, terms=terms, root=root),
    ):
        if used >= focus_budget:
            break
        if n.type in (NodeType.MODULE, NodeType.DOCUMENT):
            md = n.metadata or {}
            fk = str(md.get("path") or md.get("repo_path") or "")
            if fk and fk in focus_file_chunks:
                # Summaries only — chunks already carry the dense payload.
                text, tok = fetcher.render(graph, n, Level.SUMMARY)
                if used + tok > focus_budget and packet.sections:
                    continue
                packet.sections.append(_make_section("focus", n, text, tok, root))
                used += tok
                continue
        per_node = min(focus_budget - used, 1200)
        text, tok = fetcher.render(
            graph, n, Level.FULL, repo_root=root, budget=per_node,
            highlight_terms=highlight_terms,
        )
        if used + tok > focus_budget and packet.sections:
            continue
        packet.sections.append(_make_section("focus", n, text, tok, root))
        used += tok

    used_c = 0
    for n in sorted(
        connected_nodes,
        key=lambda node: _focus_order(node, hops=hops, seed_set=seed_set, terms=terms, root=root),
    ):
        if used_c >= connected_budget:
            break
        text, tok = fetcher.render(graph, n, Level.SUMMARY)
        if used_c + tok > connected_budget and any(s.band == "connected" for s in packet.sections):
            continue
        packet.sections.append(_make_section("connected", n, text, tok, root))
        used_c += tok

    packet.sections.extend(tail_sections)
    packet.total_tokens = sum(s.tokens for s in packet.sections)
    packet.files = _collect_files(packet.sections)


def _score_coverage(packet: ContextPacket, graph: Graph, prompt: str) -> None:
    grounded_tokens: set[str] = set()
    for s in packet.sections:
        if s.band in ("focus", "connected"):
            grounded_tokens |= _hub_tokens(s.text)
    terms = query_terms(graph, prompt)
    total_idf = sum(idf for _, idf in terms)
    covered_idf = sum(idf for t, idf in terms if t in grounded_tokens)
    packet.coverage = (covered_idf / total_idf) if total_idf else 1.0
    packet.uncovered_terms = [t for t, _ in terms if t not in grounded_tokens]
    packet.low_confidence = packet.coverage < 0.75 or not packet.sections


def _build_context_once(
    graph: Graph,
    prompt: str,
    *,
    repo_root: str | Path | None = None,
    total_budget: int = 4000,
    sigma: float = 0.85,
    max_hops: int = 2,
    k: int = 3,
    forced_seeds: list[str] | None = None,
) -> tuple[ContextPacket, Graph, dict[str, int], Path | None]:
    scored = anchor_scored(graph, prompt, k=max(k * 4, 12))
    root = fetcher.resolve_repo_root(graph, repo_root)
    focus_domain = _select_focus_domain(graph, scored)

    seeds = list(forced_seeds or _pick_seeds(graph, scored, k))
    seeds = _expand_process_seeds(graph, seeds)
    seeds = _expand_chunk_seeds(graph, seeds, neighbor_hops=1)
    if focus_domain:
        for nid, _ in scored:
            if graph.nodes[nid].domain == focus_domain:
                if nid not in seeds:
                    seeds.append(nid)
                break
        for n in graph.nodes.values():
            if (n.type == NodeType.SERVICE
                    and (n.metadata or {}).get("kind") == "process"
                    and n.domain == focus_domain
                    and n.id not in seeds):
                seeds.append(n.id)
        seeds = _expand_process_seeds(graph, seeds)
    sub, hops = traverse(graph, seeds, max_hops=max_hops)

    packet = ContextPacket(prompt=prompt, seeds=seeds, focus_domain=focus_domain,
                           repo_root=str(root) if root else None)
    return packet, sub, hops, root


def build_context(graph: Graph, prompt: str, *, repo_root: str | Path | None = None,
                  total_budget: int = 4000, sigma: float = 0.85,
                  max_hops: int = 2, k: int = 3) -> ContextPacket:
    terms = _prompt_term_set(graph, prompt)
    packet, sub, hops, root = _build_context_once(
        graph, prompt, repo_root=repo_root, total_budget=total_budget,
        sigma=sigma, max_hops=max_hops, k=k,
    )

    _assemble_bands(
        graph, packet, sub=sub, hops=hops, root=root,
        total_budget=total_budget, sigma=sigma, terms=terms,
        highlight_terms=terms if terms else None,
    )

    _score_coverage(packet, graph, prompt)
    if packet.coverage < 0.75 and packet.uncovered_terms:
        uncovered = set(packet.uncovered_terms)
        retry_prompt = f"{prompt} {' '.join(packet.uncovered_terms[:6])}".strip()
        rescored = anchor_scored(graph, retry_prompt, k=max((k + 2) * 4, 16))
        retry_seeds = list(packet.seeds)
        for nid in _pick_seeds(graph, rescored, k + 3):
            if nid not in retry_seeds:
                retry_seeds.append(nid)
        for nid in fetcher.find_leaf_nodes_for_terms(graph, root, uncovered, limit=5):
            if nid not in retry_seeds:
                retry_seeds.append(nid)
        retry, retry_sub, retry_hops, retry_root = _build_context_once(
            graph, retry_prompt, repo_root=repo_root, total_budget=total_budget,
            sigma=sigma, max_hops=max(max_hops, 3), k=k + 2, forced_seeds=retry_seeds,
        )
        _assemble_bands(
            graph, retry, sub=retry_sub, hops=retry_hops, root=retry_root,
            total_budget=total_budget, sigma=sigma, terms=terms | uncovered,
            highlight_terms=uncovered,
        )
        retry.refinement_rounds = 1
        _score_coverage(retry, graph, prompt)
        if retry.coverage > packet.coverage or (
            retry.coverage == packet.coverage and retry.total_tokens > packet.total_tokens
        ):
            packet = retry
    packet.low_confidence = packet.coverage < 0.75 or bool(packet.uncovered_terms)
    packet.rendered = render_packet(packet, graph)
    return packet


def render_packet(packet: ContextPacket, graph: Graph) -> str:
    out: list[str] = []
    if packet.uncovered_terms:
        out.append(f"> ⚠ coverage {packet.coverage:.0%} — prompt terms not grounded "
                   f"in the context: {', '.join(packet.uncovered_terms)} "
                   f"(consider re-querying focused on these)")
        out.append("")
    if packet.low_confidence and not packet.uncovered_terms:
        out.append("> ⚠ low confidence — retrieval found limited grounded evidence for this prompt")
        out.append("")
    fd = packet.focus_domain
    dnode = _domain_node(graph, fd) if fd else None
    title = dnode.name if dnode else (fd or "(prompt focus)")
    out.append(f"## FOCUS — {title}")
    if dnode and dnode.summary:
        out.append(dnode.summary)
    for s in packet.sections:
        if s.band == "focus":
            out.append("")
            out.append(s.text)

    connected = [s for s in packet.sections if s.band == "connected"]
    if connected:
        out.append("\n## CONNECTED (1 hop)")
        for s in connected:
            out.append(s.text)

    rest = [s for s in packet.sections if s.band == "rest"]
    if rest:
        out.append("\n## REST OF SYSTEM (one line each)")
        for s in rest:
            out.append(s.text)
    return "\n".join(out)

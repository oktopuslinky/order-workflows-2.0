"""Scalable BM25 anchor index for large graphs.

Uses an inverted index (term → posting list) so query time is O(|postings|)
instead of O(|nodes| × |terms|). Rebuild when graph identity or node count
changes; cache keyed on graph version stamp.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from ..model.schema import Graph, Node, NodeType

_STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "what", "which",
    "is", "are", "if", "i", "do", "does", "with", "how", "when", "where", "this",
    "that", "new", "add", "adding", "want", "would", "change", "changes", "break",
    "breaks", "happens", "happen", "need", "use", "using", "should", "system",
    "into", "onto", "via", "out", "your", "our", "their", "from", "about", "work",
    "works", "working", "make",
}

_TYPE_BOOST = {
    "Domain": 1.4, "Subdomain": 1.2, "Stage": 1.3, "Service": 1.6,
    "Repository": 1.3, "Module": 1.0, "Function": 0.9, "Class": 0.95,
    "Chunk": 1.45,  # prefer exact spans over whole-file Module/Document hits
    "Endpoint": 0.8, "Schema": 0.7, "Document": 0.9, "Team": 0.6, "Config": 0.8,
    "DataArtifact": 1.15,
}

_DERIV_SUFFIXES = (
    "ements", "ement", "izations", "ization", "ations", "ation", "sions",
    "sion", "tions", "tion", "ments", "ment", "ings", "ing", "ied", "ed",
)

_BM25_K1 = 1.5
_BM25_B = 0.75
_BODY_CHARS = 6000
_NOISE_PATH_PARTS = {
    "test", "tests", "testing", "fixture", "fixtures", "example", "examples",
    "demo", "demos", "sample", "samples", "tool", "tools", "vendor",
}

_INDEX_CACHE: dict[str, "AnchorIndex"] = {}


def _stem(w: str) -> str:
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 5:
        w = w[:-3] + "y"
    elif not w.endswith("ss") and not w.endswith("us") and w.endswith("s") and len(w) > 4:
        w = w[:-1]
    for suf in _DERIV_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            base = w[:-len(suf)]
            if len(base) >= 2 and base[-1] == base[-2] and base[-1] not in "aeiou":
                base = base[:-1]
            w = base
            break
    return w


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) >= 3 and w not in _STOP]


def query_token_set(text: str) -> set[str]:
    return set(tokenize(text))


def node_text(node: Node) -> str:
    parts = [node.id, node.name, node.summary, node.domain or ""]
    parts.append(json.dumps(node.metadata))
    return " ".join(parts).lower()


def _repo_root(graph: Graph) -> Path | None:
    for node in graph.nodes.values():
        if node.type == NodeType.REPOSITORY:
            path = (node.metadata or {}).get("path")
            if path and Path(path).exists():
                return Path(path).resolve()
    return None


def _extract_text_for_index(repo_root: Path | None, node: Node) -> str:
    """Read a bounded slice of extracted file text for body-aware retrieval."""
    if repo_root is None:
        return ""
    md = node.metadata or {}
    extract_rel = md.get("extract_path")
    if extract_rel:
        path = (repo_root / ".contexthub" / extract_rel).resolve()
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="ignore")[:_BODY_CHARS]
            except OSError:
                return ""
    return ""


def _slice_lines(text: str, start_line: int, end_line: int) -> str:
    """1-indexed inclusive line slice."""
    if not text or start_line < 1:
        return ""
    lines = text.splitlines()
    end = min(end_line, len(lines)) if end_line else len(lines)
    start = min(start_line, end)
    return "\n".join(lines[start - 1 : end])


def _chunk_text_for_index(repo_root: Path | None, node: Node) -> str:
    """Index the exact chunk span (not the whole file)."""
    if repo_root is None:
        return ""
    md = node.metadata or {}
    start = int(md.get("start_line") or 0)
    end = int(md.get("end_line") or 0)
    if not start or not end:
        return ""
    body = ""
    extract_rel = md.get("extract_path")
    if extract_rel:
        path = (repo_root / ".contexthub" / extract_rel).resolve()
        if path.is_file():
            try:
                body = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                body = ""
    if not body:
        ref = md.get("repo_path") or md.get("path") or md.get("file")
        if ref:
            path = (repo_root / ref).resolve()
            if path.is_file():
                try:
                    body = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    body = ""
    if not body:
        return ""
    return _slice_lines(body, start, end)


def _is_noise_path(path: str | None) -> bool:
    if not path:
        return False
    parts = {p.lower() for p in re.split(r"[\\/]+", path) if p}
    return any(p in _NOISE_PATH_PARTS for p in parts)


def _path_boost(node: Node, qset: set[str]) -> float:
    md = node.metadata or {}
    path = str(md.get("repo_path") or md.get("path") or md.get("file") or "")
    if not path:
        return 1.0
    boost = 1.0
    if _is_noise_path(path):
        if qset & {"test", "tests", "fixture", "fixtures", "example", "examples", "demo"}:
            boost *= 1.0
        else:
            boost *= 0.35
    if path.count("/") >= 4 and "node_modules" not in path:
        boost *= 0.95
    return boost


def _artifact_boost(node: Node) -> float:
    md = node.metadata or {}
    kind = str(md.get("kind") or md.get("doc_kind") or "").lower()
    if node.type == NodeType.CHUNK:
        return 1.4
    if node.type == NodeType.DOCUMENT:
        return 1.3
    if node.type == NodeType.ENDPOINT:
        return 1.25
    if node.type == NodeType.SCHEMA:
        return 1.15
    if node.type in (NodeType.MODULE, NodeType.SERVICE):
        return 1.12
    if node.type == NodeType.DATA_ARTIFACT and kind in {"topic", "entity"}:
        return 0.35
    return 1.0


def _is_anchor_candidate(node: Node) -> bool:
    """Minted reference stubs (``declared: False``) are not anchor material.

    Such a node carries no content beyond the identifier itself, and every
    artifact that mentions the id contains the same string — so the stub is
    reachable by traversal from a seeded artifact, never needed as a lexical
    seed. Indexing stubs also shifts the corpus document-frequency statistics:
    Phase 9 measured golden-question retrieval on synthetic-telecom dropping
    from 3 matched terms to 1 purely from the 25 minted id stubs entering
    BM25 (docs/handoff-sources-onboarding.md §15). Declared catalog nodes
    (Components, Terms) carry real names/definitions and stay indexed.
    """
    return (node.metadata or {}).get("declared") is not False


class AnchorIndex:
    """Inverted-index BM25 over graph node text."""

    def __init__(self, graph: Graph) -> None:
        self.n_docs = len(graph.nodes)
        self.avgdl = 1.0
        self.idf: dict[str, float] = {}
        self.doc_len: dict[str, int] = {}
        self.postings: dict[str, dict[str, int]] = defaultdict(dict)
        self._nodes: dict[str, Node] = dict(graph.nodes)
        self._repo_root = _repo_root(graph)
        self._build(graph)

    def _build(self, graph: Graph) -> None:
        df: dict[str, int] = defaultdict(int)
        total_len = 0
        indexed = 0
        for nid, node in graph.nodes.items():
            if not _is_anchor_candidate(node):
                continue
            indexed += 1
            text = node_text(node)
            if node.type == NodeType.CHUNK:
                body = _chunk_text_for_index(self._repo_root, node)
                if body:
                    text = f"{text}\n{body}"
            elif node.type in (NodeType.DOCUMENT, NodeType.MODULE):
                # Keep a short body for recall, but Chunk nodes are preferred at score time.
                body = _extract_text_for_index(self._repo_root, node)
                if body:
                    text = f"{text}\n{body}"
            toks = tokenize(text)
            tf = Counter(toks)
            self.doc_len[nid] = sum(tf.values()) or 1
            total_len += self.doc_len[nid]
            for t, f in tf.items():
                self.postings[t][nid] = f
                df[t] += 1
        n = max(indexed, 1)
        self.n_docs = indexed
        self.avgdl = total_len / n
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def score(self, prompt: str, *, k: int = 10) -> list[tuple[str, float]]:
        qset = query_token_set(prompt)
        if not qset:
            return []

        candidates: set[str] = set()
        for t in qset:
            candidates.update(self.postings.get(t, {}).keys())

        scored: list[tuple[float, str]] = []
        for nid in candidates:
            node = self._nodes.get(nid)
            if not node:
                continue
            dl = self.doc_len.get(nid, 1)
            s = 0.0
            for t in qset:
                f = self.postings.get(t, {}).get(nid, 0)
                if not f:
                    continue
                s += self.idf.get(t, 0.0) * (f * (_BM25_K1 + 1)) / (
                    f + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / self.avgdl))
            if s <= 0:
                continue
            for seg in re.split(r"[.\-_/]", nid.lower()):
                if seg in qset:
                    s += 1.5
            s *= _TYPE_BOOST.get(node.type.value, 1.0)
            s *= _artifact_boost(node)
            s *= _path_boost(node, qset)
            scored.append((s, nid))

        scored.sort(key=lambda t: (-t[0], t[1]))
        return [(nid, round(s, 3)) for s, nid in scored[:k]]

    def query_terms(self, prompt: str) -> list[tuple[str, float]]:
        qset = query_token_set(prompt)
        terms = [(t, self.idf[t]) for t in qset if t in self.idf]
        terms.sort(key=lambda x: -x[1])
        return terms


def graph_stamp(graph: Graph) -> str:
    return f"{id(graph)}:{len(graph.nodes)}:{len(graph.edges)}"


def get_index(graph: Graph) -> AnchorIndex:
    stamp = graph_stamp(graph)
    cached = _INDEX_CACHE.get(stamp)
    if cached is not None:
        return cached
    # Evict stale entries for same graph object with different size
    prefix = f"{id(graph)}:"
    for key in list(_INDEX_CACHE):
        if key.startswith(prefix) and key != stamp:
            del _INDEX_CACHE[key]
    idx = AnchorIndex(graph)
    _INDEX_CACHE[stamp] = idx
    return idx


def invalidate_cache(graph: Graph | None = None) -> None:
    if graph is None:
        _INDEX_CACHE.clear()
        return
    prefix = f"{id(graph)}:"
    for key in list(_INDEX_CACHE):
        if key.startswith(prefix):
            del _INDEX_CACHE[key]

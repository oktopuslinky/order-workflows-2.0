"""Fetch real content for a graph node — the dereference step.

A graph node is a *pointer*: it carries a summary plus metadata (repo_path,
entrypoint, language, doc path, schema fields, start_line/end_line for Chunks).
The working repo is the *content store*. This module turns a pointer into
actual content at a requested detail level:

    Level.LINE     name + one clause of the summary          (the thin tail)
    Level.SUMMARY  summary + signatures (endpoints/schema)   (connected band)
    Level.FULL     summary + signatures + README/docs + REAL source code

Chunk nodes fetch an exact line span (`path:start-end`). Module/Document FULL
prefer matching Chunk children when present, instead of dumping the whole file.

It is generator-agnostic: it works whether the graph came from hand-authored
`domains/*.yaml` (`build.py`) or from scanning a real repo (`ingest.py`). It
relies only on a small metadata contract and degrades gracefully (FULL -> summary)
when no source is on disk.

No new dependencies: stdlib `pathlib` + `ast` (Python slicing). `tree-sitter`
would only be needed for precise slicing of non-Python source.
"""
from __future__ import annotations

import ast
import os
import re
from enum import IntEnum
from pathlib import Path

from ..bootstrap.build import est_tokens
from ..model.schema import EdgeType, Graph, Node, NodeType
from .index import tokenize

MAX_FILE_BYTES = 1_000_000
SOURCE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".rs", ".php",
    ".cs", ".kt", ".scala",
}
# Files worth picking as a service entrypoint when none is declared.
_ENTRY_CANDIDATES = (
    "main.py", "app.py", "__init__.py", "index.ts", "index.js", "main.go",
    "main.rs", "Main.java",
)


class Level(IntEnum):
    LINE = 1
    SUMMARY = 2
    FULL = 3


# --------------------------------------------------------------------------- #
# Repo root resolution
# --------------------------------------------------------------------------- #
def resolve_repo_root(graph: Graph, explicit: str | Path | None = None) -> Path | None:
    """Find the working-repo root: explicit arg > env > Repository node metadata."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        return p if p.exists() else None
    env = os.environ.get("CONTEXTHUB_REPO_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p
    for n in graph.nodes.values():
        if n.type == NodeType.REPOSITORY:
            mp = (n.metadata or {}).get("path")
            if mp and Path(mp).exists():
                return Path(mp).resolve()
    return None


# --------------------------------------------------------------------------- #
# Path / child helpers
# --------------------------------------------------------------------------- #
def _meta(node: Node) -> dict:
    return node.metadata or {}


def _code_ref(node: Node) -> str | None:
    """Relative repo path this node points at (dir or file), if any."""
    md = _meta(node)
    return md.get("repo_path") or md.get("path") or md.get("file")


def _children(graph: Graph, node_id: str, etypes: set[EdgeType]) -> list[Node]:
    out: list[Node] = []
    seen: set[str] = set()
    for e in graph.edges:
        if e.src == node_id and e.type in etypes and e.dst in graph.nodes:
            if e.dst not in seen:
                seen.add(e.dst)
                out.append(graph.nodes[e.dst])
    return out


def _read(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_node_content(repo_root: Path, node: Node) -> str:
    """Read full file content for a graph node (uses extract cache for binary formats)."""
    md = _meta(node)
    hub = repo_root / ".contexthub"
    extract_rel = md.get("extract_path")
    if extract_rel:
        cached = hub / extract_rel
        if cached.is_file():
            return _read(cached)
    ref = md.get("repo_path") or md.get("path") or md.get("file")
    if not ref:
        return ""
    path = (repo_root / ref).resolve()
    try:
        path.relative_to(repo_root)
    except ValueError:
        return ""
    if not path.is_file():
        return ""
    from ..bootstrap.formats import extract_text
    return extract_text(path)


def _resolve_code_file(repo_root: Path, node: Node) -> Path | None:
    """Map a node's metadata to a concrete source file inside the repo."""
    ref = _code_ref(node)
    if not ref:
        return None
    base = (repo_root / ref).resolve()
    # Guard against path traversal outside the repo.
    try:
        base.relative_to(repo_root)
    except ValueError:
        return None
    if base.is_file():
        return base
    if base.is_dir():
        entry = _meta(node).get("entrypoint")
        if entry and (base / entry).is_file():
            return base / entry
        for cand in _ENTRY_CANDIDATES:
            if (base / cand).is_file():
                return base / cand
        # else: first source file in the dir (shallow)
        for child in sorted(base.iterdir()):
            if child.is_file() and child.suffix in SOURCE_EXTS:
                return child
    return None


def _slice_lines(text: str, start_line: int, end_line: int) -> str:
    """Return 1-indexed inclusive line slice."""
    if not text or start_line < 1:
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    end = min(int(end_line), len(lines)) if end_line else len(lines)
    start = min(max(int(start_line), 1), end)
    return "\n".join(lines[start - 1 : end])


def _line_range(node: Node) -> tuple[int, int] | None:
    md = _meta(node)
    start = md.get("start_line")
    end = md.get("end_line")
    if start is None or end is None:
        return None
    try:
        s, e = int(start), int(end)
    except (TypeError, ValueError):
        return None
    if s < 1 or e < s:
        return None
    return s, e


# --------------------------------------------------------------------------- #
# Source slicing
# --------------------------------------------------------------------------- #
def _slice_python(text: str, symbol: str) -> tuple[str, tuple[int, int] | None]:
    """Return the source of a top-level function/class named `symbol`."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "", None
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == symbol:
            seg = ast.get_source_segment(text, n)
            if seg:
                start = int(n.lineno)
                if getattr(n, "decorator_list", None):
                    start = min(start, min(d.lineno for d in n.decorator_list))
                return seg, (start, getattr(n, "end_lineno", n.lineno))
    return "", None


def read_chunk_span(repo_root: Path, node: Node, *, max_tokens: int = 0) -> tuple[str, int]:
    """Fetch the exact line span for a Chunk (or any node with start/end lines)."""
    lines = _line_range(node)
    if not lines:
        return "", 0
    text = _read_node_content(repo_root, node)
    if not text:
        file_ref = _meta(node).get("file") or _code_ref(node)
        if file_ref:
            text = _read((repo_root / file_ref).resolve())
    if not text:
        return "", 0
    body = _slice_lines(text, lines[0], lines[1])
    if not body:
        return "", 0
    if max_tokens > 0:
        body = _truncate_to_tokens(body, max_tokens)
    file_ref = _meta(node).get("path") or _code_ref(node) or node.name
    loc = f"{file_ref}:{lines[0]}-{lines[1]}"
    rendered = f"// {loc}\n{body}"
    return rendered, est_tokens(rendered)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0 or not text:
        return ""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n… (truncated)"


def extract_snippet(text: str, terms: set[str], *, max_tokens: int) -> str:
    """Return text centered on lines/paragraphs that contain prompt terms."""
    if not text or not terms or max_tokens <= 0:
        return _truncate_to_tokens(text, max_tokens)
    lower = text.lower()
    term_list = [t.lower() for t in terms if len(t) >= 3]
    if not term_list:
        return _truncate_to_tokens(text, max_tokens)

    chunks = re.split(r"\n\s*\n", text)
    if len(chunks) <= 1:
        chunks = text.splitlines()

    scored: list[tuple[float, int, str]] = []
    for i, chunk in enumerate(chunks):
        cl = chunk.lower()
        hits = sum(1 for t in term_list if t in cl)
        if hits:
            scored.append((hits, i, chunk.strip()))

    if not scored:
        return _truncate_to_tokens(text, max_tokens)

    scored.sort(key=lambda x: (-x[0], x[1]))
    picked_idx = {i for _, i, _ in scored[:8]}
    ordered = [chunks[i].strip() for i in sorted(picked_idx) if chunks[i].strip()]
    merged = "\n\n".join(ordered)
    return _truncate_to_tokens(merged, max_tokens)


def node_term_overlap(repo_root: Path | None, node: Node, terms: set[str]) -> float:
    """How many prompt terms appear in this node's extract (for focus ranking)."""
    if not terms or repo_root is None:
        return 0.0
    if node.type == NodeType.CHUNK or _line_range(node):
        text, _ = read_chunk_span(repo_root, node)
        # Strip the // path header for scoring.
        if text.startswith("// "):
            text = text.split("\n", 1)[-1]
    else:
        text = _read_node_content(repo_root, node)
    if not text:
        return 0.0
    lower = text.lower()
    body_toks = set(tokenize(text))
    score = 0.0
    for t in terms:
        tl = t.lower()
        if tl in lower:
            score += 2.0
        elif t in body_toks:
            score += 1.0
    md = _meta(node)
    name_blob = f"{node.name} {node.id} {md.get('path', '')}".lower()
    for t in terms:
        if t.lower() in name_blob:
            score += 0.5
    return score


def find_leaf_nodes_for_terms(
    graph: Graph,
    repo_root: Path | None,
    terms: set[str],
    *,
    limit: int = 5,
) -> list[str]:
    """Scan document/module/chunk leaves for extracts that contain the terms."""
    if not terms or repo_root is None:
        return []
    scored: list[tuple[float, str]] = []
    for node in graph.nodes.values():
        if node.type not in (NodeType.DOCUMENT, NodeType.MODULE, NodeType.CHUNK):
            continue
        s = node_term_overlap(repo_root, node, terms)
        if s > 0:
            # Prefer chunks when scores are close.
            bonus = 0.5 if node.type == NodeType.CHUNK else 0.0
            scored.append((s + bonus, node.id))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [nid for _, nid in scored[:limit]]


def read_source(graph: Graph, node: Node, repo_root: Path | None,
                max_tokens: int, *, highlight_terms: set[str] | None = None) -> tuple[str, int]:
    """Fetch REAL source for a node, AST-sliced / line-sliced when possible.

    Returns (annotated_text, tokens). Empty when no source is resolvable.
    """
    if repo_root is None or max_tokens <= 0:
        return "", 0

    # Chunk nodes: exact persisted line span.
    if node.type == NodeType.CHUNK:
        return read_chunk_span(repo_root, node, max_tokens=max_tokens)

    # Function/Class: prefer stored line range, else AST slice.
    if node.type in (NodeType.FUNCTION, NodeType.CLASS):
        file_ref = _meta(node).get("file") or _code_ref(node)
        if not file_ref:
            return "", 0
        path = (repo_root / file_ref).resolve()
        text = _read(path)
        if not text:
            return "", 0
        stored = _line_range(node)
        if stored:
            sliced = _slice_lines(text, stored[0], stored[1])
            lines = stored
        elif path.suffix == ".py":
            sliced, lines = _slice_python(text, node.name)
        else:
            sliced, lines = "", None
        if sliced:
            body = (
                extract_snippet(sliced, highlight_terms, max_tokens=max_tokens)
                if highlight_terms
                else _truncate_to_tokens(sliced, max_tokens)
            )
            loc = f"{file_ref}:{lines[0]}-{lines[1]}" if lines else file_ref
            rendered = f"// {loc}\n{body}"
            return rendered, est_tokens(rendered)
        body = (
            extract_snippet(text, highlight_terms, max_tokens=max_tokens)
            if highlight_terms
            else _truncate_to_tokens(text, max_tokens)
        )
        return f"// {file_ref}\n{body}", est_tokens(f"// {file_ref}\n{body}")

    # Module/Document with chunk children: compose from matching spans.
    if node.type in (NodeType.MODULE, NodeType.DOCUMENT):
        chunk_children = [
            c for c in _children(graph, node.id, {EdgeType.CONTAINS})
            if c.type == NodeType.CHUNK
        ]
        if chunk_children:
            ranked = sorted(
                chunk_children,
                key=lambda c: (
                    -node_term_overlap(repo_root, c, highlight_terms or set()),
                    int((_meta(c).get("chunk_index") or 0)),
                ),
            )
            parts: list[str] = []
            used = 0
            for c in ranked[:6]:
                budget = max_tokens - used
                if budget <= 40:
                    break
                piece, tok = read_chunk_span(repo_root, c, max_tokens=budget)
                if not piece:
                    continue
                parts.append(piece)
                used += tok
            if parts:
                out = "\n\n".join(parts)
                return out, est_tokens(out)

    path = _resolve_code_file(repo_root, node)
    if path is None:
        # Documents / extract-only nodes.
        text = _read_node_content(repo_root, node)
        if not text:
            return "", 0
        ref = _meta(node).get("path") or node.name
        body = (
            extract_snippet(text, highlight_terms, max_tokens=max_tokens)
            if highlight_terms
            else _truncate_to_tokens(text, max_tokens)
        )
        rendered = f"// {ref}\n{body}"
        return rendered, est_tokens(rendered)
    text = _read(path)
    if not text:
        return "", 0
    rel = path.relative_to(repo_root)
    body = (
        extract_snippet(text, highlight_terms, max_tokens=max_tokens)
        if highlight_terms
        else _truncate_to_tokens(text, max_tokens)
    )
    rendered = f"// {rel}\n{body}"
    return rendered, est_tokens(rendered)


def read_docs(graph: Graph, node: Node, repo_root: Path | None,
              max_tokens: int, *, highlight_terms: set[str] | None = None) -> tuple[str, int]:
    """Fetch doc/module/chunk text attached via DOCUMENTED_BY or CONTAINS."""
    if repo_root is None or max_tokens <= 0:
        return "", 0
    if node.type == NodeType.CHUNK:
        return read_chunk_span(repo_root, node, max_tokens=max_tokens)

    docs: list[Node] = []
    seen: set[str] = set()
    for et in (EdgeType.DOCUMENTED_BY, EdgeType.CONTAINS):
        for d in _children(graph, node.id, {et}):
            if d.id in seen:
                continue
            if d.type in (NodeType.DOCUMENT, NodeType.MODULE, NodeType.CHUNK):
                docs.append(d)
                seen.add(d.id)
    if node.type == NodeType.DOCUMENT:
        docs = [node] + [d for d in docs if d.id != node.id]
    elif node.type == NodeType.MODULE and node.id not in seen:
        docs = [node] + docs
    # Prefer chunk children when present under a document/module.
    chunks = [d for d in docs if d.type == NodeType.CHUNK]
    if chunks and highlight_terms:
        ranked = sorted(
            chunks,
            key=lambda c: (
                -node_term_overlap(repo_root, c, highlight_terms),
                int((_meta(c).get("chunk_index") or 0)),
            ),
        )
        parts: list[str] = []
        used = 0
        for c in ranked[:8]:
            budget = max_tokens - used
            if budget <= 40:
                break
            piece, tok = read_chunk_span(repo_root, c, max_tokens=min(budget, max_tokens // 2 or budget))
            if piece:
                parts.append(piece)
                used += tok
        if parts:
            out = "\n\n".join(parts)
            return out, est_tokens(out)

    chunks_out: list[str] = []
    used = 0
    for d in docs:
        if d.type == NodeType.CHUNK:
            continue  # already handled above when terms present; skip bulk dump
        ref = _meta(d).get("path") or d.name
        text = _read_node_content(repo_root, d)
        if not text:
            continue
        budget = max_tokens - used
        if budget <= 0:
            break
        body = (
            extract_snippet(text, highlight_terms, max_tokens=min(budget, max_tokens // 2 or budget))
            if highlight_terms
            else _truncate_to_tokens(text, min(budget, max_tokens // 2 or budget))
        )
        chunk = f"[doc: {ref}]\n{body}"
        chunks_out.append(chunk)
        used += est_tokens(chunk)
    out = "\n\n".join(chunks_out)
    return out, est_tokens(out)


# --------------------------------------------------------------------------- #
# Signatures (cheap structural detail, no file reads)
# --------------------------------------------------------------------------- #
def signature(graph: Graph, node: Node) -> str:
    """Structural one-liner(s): endpoints, schema fields, language/path."""
    bits: list[str] = []
    md = _meta(node)
    if md.get("language"):
        bits.append(str(md["language"]))
    ref = _code_ref(node)
    if ref:
        bits.append(str(ref))
    head = f"  ({', '.join(bits)})" if bits else ""

    lines: list[str] = []
    if node.type == NodeType.SERVICE:
        eps = _children(graph, node.id, {EdgeType.IMPLEMENTS, EdgeType.CONTAINS})
        for ep in eps:
            if ep.type == NodeType.ENDPOINT:
                m = ep.metadata or {}
                lines.append(f"    {m.get('method', '')} {m.get('path', ep.name)}".rstrip())
            elif ep.type in (NodeType.DOCUMENT, NodeType.MODULE):
                dt = (ep.metadata or {}).get("doc_type", ep.type.value)
                lines.append(f"    artifact: {ep.name} ({dt})")
        schemas = _children(graph, node.id, {EdgeType.USES_SCHEMA})
        for s in schemas:
            f = (s.metadata or {}).get("fields") or []
            lines.append(f"    uses {s.name}{{{', '.join(f)}}}" if f else f"    uses {s.name}")
    elif node.type == NodeType.SCHEMA:
        f = md.get("fields") or []
        if f:
            lines.append(f"    fields: {', '.join(f)}")
    elif node.type == NodeType.ENDPOINT:
        lines.append(f"    {md.get('method', '')} {md.get('path', '')}".rstrip())
    return head + ("\n" + "\n".join(lines) if lines else "")


# --------------------------------------------------------------------------- #
# The main entry: render a node at a detail level
# --------------------------------------------------------------------------- #
def _first_clause(text: str) -> str:
    if not text:
        return ""
    for sep in (". ", "; ", " — ", ", "):
        if sep in text:
            return text.split(sep, 1)[0].strip()
    return text.strip()


def render(graph: Graph, node: Node, level: Level, *,
           repo_root: Path | None = None, budget: int = 1200,
           highlight_terms: set[str] | None = None) -> tuple[str, int]:
    """Render a node's content at `level`, within a per-node token `budget`.

    Returns (text, tokens). FULL pulls real code + docs; degrades to SUMMARY
    when no source is resolvable.
    """
    name = f"[{node.type.value}] {node.name}"

    if level == Level.LINE:
        line = f"{name}: {_first_clause(node.summary)}".rstrip(": ").rstrip()
        return line, est_tokens(line)

    header = f"{name}  <{node.id}>"
    if node.summary:
        header += f"\n  {node.summary}"
    header += signature(graph, node)
    used = est_tokens(header)

    if level == Level.SUMMARY:
        return header, used

    # FULL: documents fetch via extract cache; code via read_source.
    if node.type == NodeType.CHUNK:
        src_text, src_tok = read_chunk_span(
            repo_root, node, max_tokens=budget,
        ) if repo_root else ("", 0)
        if src_text:
            if node.summary:
                out = f"{header}\n{src_text}"
                return out, est_tokens(out)
            return src_text, src_tok
        return header, used

    if node.type == NodeType.DOCUMENT:
        docs_text, docs_tok = read_docs(
            graph, node, repo_root, max_tokens=budget, highlight_terms=highlight_terms,
        )
        if docs_text:
            return docs_text, docs_tok
        return header, used

    # FULL: add docs, then real source, within remaining budget.
    parts = [header]
    docs_text, docs_tok = read_docs(
        graph, node, repo_root, max_tokens=max(0, (budget - used) // 3),
        highlight_terms=highlight_terms,
    )
    if docs_text:
        parts.append(docs_text)
        used += docs_tok
    src_text, src_tok = read_source(
        graph, node, repo_root, max_tokens=max(0, budget - used),
        highlight_terms=highlight_terms,
    )
    if src_text:
        parts.append(src_text)
        used += src_tok
    return "\n".join(parts), used

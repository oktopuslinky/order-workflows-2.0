"""Split file text into addressable line-range chunks for the knowledge graph.

Chunks are the retrieval unit: each carries start_line/end_line so fetch can
return an exact span (plus NEXT-linked neighbors) instead of a whole file.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextSpan:
    """One addressable span inside a file (1-indexed, inclusive)."""

    start_line: int
    end_line: int
    text: str
    summary: str
    kind: str = "window"  # symbol | paragraph | window | heading
    symbol: str | None = None


# Soft targets — keep chunks small enough for dense BM25 + cheap FULL fetch.
DEFAULT_TARGET_LINES = 60
DEFAULT_MAX_LINES = 120
DEFAULT_OVERLAP_LINES = 8
DEFAULT_MAX_CHUNKS = 40
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _join_lines(lines: list[str], start: int, end: int) -> str:
    """Slice lines with 1-indexed inclusive bounds."""
    if start < 1:
        start = 1
    if end < start:
        return ""
    return "\n".join(lines[start - 1 : end])


def _summary_from(text: str, *, limit: int = 160) -> str:
    for line in text.splitlines():
        s = line.strip()
        if len(s) >= 8 and not s.startswith(("#!", "import ", "from ", "```", "---")):
            return s[:limit]
    compact = " ".join(text.split())
    return compact[:limit] if compact else "chunk"


def _merge_overlaps(spans: list[TextSpan]) -> list[TextSpan]:
    """Drop spans fully contained in a previous span; keep order by start."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s.start_line, s.end_line, s.kind))
    kept: list[TextSpan] = []
    for span in ordered:
        if kept and span.start_line >= kept[-1].start_line and span.end_line <= kept[-1].end_line:
            # Prefer symbol spans over windows that wrap them.
            if span.kind == "symbol" and kept[-1].kind != "symbol":
                kept[-1] = span
            continue
        if kept and span.start_line <= kept[-1].end_line and span.kind == kept[-1].kind:
            # Extend adjacent same-kind windows.
            prev = kept[-1]
            merged_text = prev.text
            if span.end_line > prev.end_line:
                extra = "\n".join(_lines(span.text)[prev.end_line - span.start_line + 1 :])
                if extra:
                    merged_text = f"{prev.text}\n{extra}" if prev.text else extra
            kept[-1] = TextSpan(
                prev.start_line,
                max(prev.end_line, span.end_line),
                merged_text,
                prev.summary if prev.kind == "symbol" else _summary_from(merged_text),
                kind=prev.kind,
                symbol=prev.symbol or span.symbol,
            )
            continue
        kept.append(span)
    return kept


def _window_spans(
    text: str,
    *,
    target_lines: int = DEFAULT_TARGET_LINES,
    overlap: int = DEFAULT_OVERLAP_LINES,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    skip: list[tuple[int, int]] | None = None,
) -> list[TextSpan]:
    """Fixed-size line windows, optionally skipping ranges already covered."""
    lines = _lines(text)
    n = len(lines)
    if n == 0:
        return []
    covered = skip or []
    spans: list[TextSpan] = []
    i = 1
    while i <= n and len(spans) < max_chunks:
        # Jump past fully covered regions.
        jumped = False
        for a, b in covered:
            if a <= i <= b:
                i = b + 1
                jumped = True
                break
        if jumped:
            continue
        end = min(i + target_lines - 1, n)
        # Don't start a tiny leftover if previous window already near end.
        if end - i + 1 < max(12, target_lines // 4) and spans:
            break
        body = _join_lines(lines, i, end)
        if body.strip():
            spans.append(TextSpan(i, end, body, _summary_from(body), kind="window"))
        if end >= n:
            break
        i = max(i + 1, end - overlap + 1)
    return spans


def chunk_python(
    text: str,
    *,
    target_lines: int = DEFAULT_TARGET_LINES,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> list[TextSpan]:
    """Prefer AST symbol spans; fill gaps with line windows."""
    lines = _lines(text)
    symbol_spans: list[TextSpan] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _window_spans(text, target_lines=target_lines, max_chunks=max_chunks)[:max_chunks]

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = int(node.lineno)
        end = int(getattr(node, "end_lineno", None) or start)
        # Include leading decorators.
        if getattr(node, "decorator_list", None):
            start = min(start, min(d.lineno for d in node.decorator_list))
        body = _join_lines(lines, start, end)
        if not body.strip():
            continue
        kind = "Class" if isinstance(node, ast.ClassDef) else "Function"
        doc = (ast.get_docstring(node) or "").splitlines()
        summary = doc[0] if doc else f"{kind.lower()} {node.name}"
        symbol_spans.append(TextSpan(
            start, end, body, summary[:160], kind="symbol", symbol=node.name,
        ))

    covered = [(s.start_line, s.end_line) for s in symbol_spans]
    # Module-level preamble / leftovers between symbols.
    gaps = _window_spans(
        text, target_lines=target_lines, max_chunks=max_chunks, skip=covered,
    )
    merged = _merge_overlaps(symbol_spans + gaps)
    return merged[:max_chunks]


def chunk_document(
    text: str,
    *,
    target_lines: int = DEFAULT_TARGET_LINES,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> list[TextSpan]:
    """Split docs on headings / blank-line paragraphs, then window overflow."""
    if not text.strip():
        return []
    lines = _lines(text)
    n = len(lines)

    # Split on markdown headings when present (even for short docs).
    heading_starts = [m.start() for m in _HEADING_RE.finditer(text)]
    if len(heading_starts) >= 2:
        spans: list[TextSpan] = []
        # Map char offsets to line numbers.
        char_to_line: list[int] = []
        for i, line in enumerate(lines, start=1):
            char_to_line.extend([i] * (len(line) + 1))
        for idx, start_char in enumerate(heading_starts):
            end_char = heading_starts[idx + 1] if idx + 1 < len(heading_starts) else len(text)
            start = char_to_line[min(start_char, len(char_to_line) - 1)] if char_to_line else 1
            end = char_to_line[min(end_char - 1, len(char_to_line) - 1)] if char_to_line else n
            end = max(end, start)
            body = _join_lines(lines, start, end)
            if not body.strip():
                continue
            # Oversized heading sections → sub-windows.
            if end - start + 1 > DEFAULT_MAX_LINES:
                for w in _window_spans(body, target_lines=target_lines, max_chunks=max_chunks):
                    abs_start = start + w.start_line - 1
                    abs_end = start + w.end_line - 1
                    spans.append(TextSpan(
                        abs_start, abs_end, w.text, w.summary, kind="heading",
                    ))
            else:
                spans.append(TextSpan(start, end, body, _summary_from(body), kind="heading"))
            if len(spans) >= max_chunks:
                break
        if spans:
            return spans[:max_chunks]

    if n <= target_lines:
        return [TextSpan(1, n, text, _summary_from(text), kind="paragraph")]

    # Paragraph packing into ~target_lines buckets.
    spans = []
    buf: list[str] = []
    buf_start = 1
    for i, line in enumerate(lines, start=1):
        if not line.strip() and buf and len(buf) >= max(8, target_lines // 3):
            body = "\n".join(buf)
            spans.append(TextSpan(buf_start, i - 1, body, _summary_from(body), kind="paragraph"))
            buf = []
            buf_start = i + 1
            if len(spans) >= max_chunks:
                return spans
            continue
        if not buf:
            buf_start = i
        buf.append(line)
        if len(buf) >= target_lines:
            body = "\n".join(buf)
            spans.append(TextSpan(buf_start, i, body, _summary_from(body), kind="paragraph"))
            buf = []
            buf_start = i + 1
            if len(spans) >= max_chunks:
                return spans
    if buf and len(spans) < max_chunks:
        body = "\n".join(buf)
        spans.append(TextSpan(buf_start, n, body, _summary_from(body), kind="paragraph"))
    return spans[:max_chunks] if spans else _window_spans(
        text, target_lines=target_lines, max_chunks=max_chunks,
    )


def chunk_file(
    path: Path | str,
    text: str,
    *,
    target_lines: int = DEFAULT_TARGET_LINES,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> list[TextSpan]:
    """Dispatch chunking by file type."""
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return chunk_python(text, target_lines=target_lines, max_chunks=max_chunks)
    if suffix in {".md", ".rst", ".txt", ".markdown"} or "doc" in str(path).lower():
        return chunk_document(text, target_lines=target_lines, max_chunks=max_chunks)
    # Other source: windows (regex symbol splitting is approximate elsewhere).
    return _window_spans(text, target_lines=target_lines, max_chunks=max_chunks)

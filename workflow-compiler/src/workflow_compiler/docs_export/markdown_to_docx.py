"""Deterministic converter from *our* artifact markdown to :class:`DocxWriter` calls.

The grammar is the subset ``change/render.py`` emits (and the model's prose
bodies use): ATX headings, paragraphs, ``-``/``*`` bullets (nested by two-space
indent), ``1.`` numbered items, ``- [ ]`` / ``- [x]`` checklists → ☐ / ☑, pipe
tables (``<br>`` = line break, ``\\|`` = literal pipe), fenced code blocks,
``> note`` block quotes, ``**Label:** value`` metadata lines and inline
`` `code` `` / ``**bold**`` / ``*italic*``. Anything else is a paragraph.

Two entry points:

* :func:`render_markdown` — render a body fragment (a TDD section's *Proposed*
  text, a story's notes, …) into an existing writer; headings inside the
  fragment are offset so they nest under the caller's heading.
* :func:`markdown_document` — render a whole artifact when no structured
  layout applies (fallback; the artifact exporters use the parsed docs).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from workflow_compiler.change.parse import parse_table

from .docx_writer import DocxWriter

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_CHECK = re.compile(r"^(\s*)[-*]\s+\[( |x|X)\]\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(?!\[[ xX]\]\s)(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_META = re.compile(r"^\*\*([^*]+?):\*\*\s*(.*)$")
_EMPTY_MARKERS = {"_None._", "_To be determined._", "_No traversal rows._"}


@dataclass
class Block:
    kind: str  # heading | paragraph | bullet | numbered | check | table | code | quote | meta
    text: str = ""
    level: int = 0
    done: bool = False
    number: int = 0
    lines: list[str] = field(default_factory=list)


def _table_lines(lines: Sequence[str], start: int) -> int:
    """Index one past the pipe-table starting at ``start``."""
    end = start
    while end < len(lines) and lines[end].strip().startswith("|"):
        end += 1
    return end


def parse_blocks(markdown: str) -> list[Block]:
    """Tokenise markdown into flat blocks (paragraph lines are joined)."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            text = " ".join(part.strip() for part in para).strip()
            if text and text not in _EMPTY_MARKERS:
                blocks.append(Block("paragraph", text))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            j = i + 1
            code: list[str] = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                code.append(lines[j])
                j += 1
            blocks.append(Block("code", "\n".join(code)))
            i = j + 1
            continue
        if not stripped:
            flush()
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            flush()
            end = _table_lines(lines, i)
            blocks.append(Block("table", lines=list(lines[i:end])))
            i = end
            continue
        if (m := _HEADING.match(line)) is not None:
            flush()
            blocks.append(Block("heading", m.group(2).strip(), level=len(m.group(1))))
        elif (m := _CHECK.match(line)) is not None:
            flush()
            blocks.append(
                Block(
                    "check",
                    m.group(3).strip(),
                    level=len(m.group(1)) // 2,
                    done=m.group(2).lower() == "x",
                )
            )
        elif (m := _BULLET.match(line)) is not None:
            flush()
            blocks.append(Block("bullet", m.group(2).strip(), level=len(m.group(1)) // 2))
        elif (m := _NUMBERED.match(line)) is not None:
            flush()
            blocks.append(Block("numbered", m.group(3).strip(), number=int(m.group(2))))
        elif stripped.startswith(">"):
            flush()
            blocks.append(Block("quote", stripped.lstrip(">").strip()))
        elif (m := _META.match(stripped)) is not None:
            flush()
            blocks.append(Block("meta", m.group(2).strip(), lines=[m.group(1).strip()]))
        elif stripped in ("---", "***", "___"):
            flush()
        elif (
            not para and blocks and blocks[-1].kind in ("bullet", "check") and line.startswith("  ")
        ):
            # continuation line of a list item
            blocks[-1].text += " " + stripped
        else:
            para.append(line)
        i += 1
    flush()
    return blocks


def render_blocks(writer: DocxWriter, blocks: Sequence[Block], *, heading_offset: int = 0) -> None:
    for block in blocks:
        if block.kind == "heading":
            writer.heading(block.text, level=max(1, block.level - 1 + heading_offset))
        elif block.kind == "paragraph":
            writer.paragraph(block.text)
        elif block.kind == "bullet":
            writer.bullet(block.text, level=min(block.level, 2))
        elif block.kind == "numbered":
            writer.numbered(block.text, block.number)
        elif block.kind == "check":
            writer.checklist_item(block.text, block.done)
        elif block.kind == "table":
            columns, rows = parse_table("\n".join(block.lines))
            if columns:
                writer.table(columns, rows)
        elif block.kind == "code":
            writer.code_block(block.text)
        elif block.kind == "quote":
            writer.note(block.text)
        elif block.kind == "meta":
            writer.meta(block.lines[0], block.text)


def render_markdown(writer: DocxWriter, markdown: str, *, heading_offset: int = 0) -> None:
    """Render a markdown fragment into ``writer``.

    ``heading_offset`` shifts heading levels: with ``heading_offset=2`` a ``##``
    inside the fragment becomes *Heading 3* — bodies nested under an artifact
    section never outrank it. Empty markers (``_None._``) render nothing.
    """
    text = markdown.strip()
    if not text or text in _EMPTY_MARKERS:
        return
    render_blocks(writer, parse_blocks(text), heading_offset=heading_offset)


def markdown_document(markdown: str, *, doc_type: str | None = None) -> bytes:
    """Whole-document fallback: ``# Title`` → title (+ ``doc_type`` as the 22 pt
    title when given, the H1 as subtitle), everything else in order."""
    writer = DocxWriter()
    blocks = parse_blocks(markdown)
    first = next((b for b in blocks if b.kind == "heading" and b.level == 1), None)
    if first is not None:
        if doc_type:
            writer.title(doc_type)
            writer.subtitle(first.text)
        else:
            writer.title(first.text)
        blocks = [b for b in blocks if b is not first]
    render_blocks(writer, blocks, heading_offset=0)
    return writer.bytes()

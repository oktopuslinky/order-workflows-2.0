"""Markdown (.md) document parser with lightweight structure extraction."""

from __future__ import annotations

import re
from typing import ClassVar

from workflow_compiler.ingestion.base import (
    BaseDocumentParser,
    ExtractExtras,
    normalize_text,
)
from workflow_compiler.ingestion.content import (
    DocumentFormat,
    DocumentSection,
    SectionType,
)
from workflow_compiler.ingestion.encoding import detect_and_decode

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")

_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC = re.compile(r"(\*|_)(.+?)\1")


def _strip_inline(value: str) -> str:
    """Remove common inline Markdown syntax, leaving readable text."""
    value = _IMAGE.sub(r"\1", value)
    value = _LINK.sub(r"\1", value)
    value = _INLINE_CODE.sub(r"\1", value)
    value = _BOLD.sub(r"\2", value)
    value = _ITALIC.sub(r"\2", value)
    return value.strip()


class MarkdownParser(BaseDocumentParser):
    """Parse Markdown into headings, paragraphs, lists, quotes, and code blocks."""

    document_format: ClassVar[DocumentFormat] = DocumentFormat.MARKDOWN
    extensions: ClassVar[tuple[str, ...]] = (".md", ".markdown", ".mdown", ".mkd")
    content_types: ClassVar[tuple[str, ...]] = ("text/markdown", "text/x-markdown")
    is_binary: ClassVar[bool] = False

    def _extract(
        self, data: bytes, warnings: list[str]
    ) -> tuple[str, list[DocumentSection], ExtractExtras]:
        text, encoding = detect_and_decode(data)

        sections: list[DocumentSection] = []
        plain_lines: list[str] = []
        title: str | None = None

        paragraph: list[str] = []
        code_lines: list[str] = []
        in_code = False

        def flush_paragraph() -> None:
            if paragraph:
                joined = " ".join(line.strip() for line in paragraph).strip()
                if joined:
                    sections.append(
                        DocumentSection(
                            order=len(sections),
                            section_type=SectionType.PARAGRAPH,
                            text=joined,
                        )
                    )
                    plain_lines.append(joined)
                paragraph.clear()

        def flush_code() -> None:
            if code_lines:
                sections.append(
                    DocumentSection(
                        order=len(sections),
                        section_type=SectionType.CODE,
                        text="\n".join(code_lines),
                    )
                )
                code_lines.clear()

        for raw_line in normalize_text(text).split("\n"):
            if _FENCE.match(raw_line):
                if in_code:
                    flush_code()
                    in_code = False
                else:
                    flush_paragraph()
                    in_code = True
                continue

            if in_code:
                code_lines.append(raw_line)
                plain_lines.append(raw_line)
                continue

            heading = _HEADING.match(raw_line)
            if heading:
                flush_paragraph()
                level = len(heading.group(1))
                heading_text = _strip_inline(heading.group(2))
                sections.append(
                    DocumentSection(
                        order=len(sections),
                        section_type=SectionType.HEADING,
                        text=heading_text,
                        level=level,
                    )
                )
                if level == 1 and title is None:
                    title = heading_text
                plain_lines.append(heading_text)
                continue

            list_item = _LIST_ITEM.match(raw_line)
            if list_item:
                flush_paragraph()
                item_text = _strip_inline(list_item.group(1))
                sections.append(
                    DocumentSection(
                        order=len(sections),
                        section_type=SectionType.LIST,
                        text=item_text,
                    )
                )
                plain_lines.append(item_text)
                continue

            quote = _QUOTE.match(raw_line)
            if quote:
                flush_paragraph()
                quote_text = _strip_inline(quote.group(1))
                sections.append(
                    DocumentSection(
                        order=len(sections),
                        section_type=SectionType.QUOTE,
                        text=quote_text,
                    )
                )
                plain_lines.append(quote_text)
                continue

            if raw_line.strip() == "":
                flush_paragraph()
                plain_lines.append("")
                continue

            paragraph.append(_strip_inline(raw_line))

        flush_paragraph()
        if in_code:
            flush_code()

        plain_text = "\n".join(plain_lines)
        return plain_text, sections, {"encoding": encoding, "title": title}

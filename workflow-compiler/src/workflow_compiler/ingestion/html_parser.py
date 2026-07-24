"""HTML document parser built on BeautifulSoup (stdlib ``html.parser``)."""

from __future__ import annotations

import re
from typing import ClassVar

from bs4 import BeautifulSoup
from bs4.element import Tag

from workflow_compiler.ingestion.base import BaseDocumentParser, ExtractExtras
from workflow_compiler.ingestion.content import (
    DocumentFormat,
    DocumentSection,
    SectionType,
)
from workflow_compiler.ingestion.encoding import detect_and_decode

_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote")
_DROP_TAGS = ("script", "style", "noscript", "template")
_AUTHOR_NAME = re.compile(r"author", re.IGNORECASE)


def _section_type_for(tag_name: str) -> tuple[SectionType, int | None]:
    """Map an HTML tag name to a section type and optional heading level."""
    if len(tag_name) == 2 and tag_name[0] == "h" and tag_name[1].isdigit():
        return SectionType.HEADING, int(tag_name[1])
    if tag_name == "li":
        return SectionType.LIST, None
    if tag_name == "pre":
        return SectionType.CODE, None
    if tag_name == "blockquote":
        return SectionType.QUOTE, None
    return SectionType.PARAGRAPH, None


class HtmlParser(BaseDocumentParser):
    """Parse HTML, extracting title/author metadata and block-level structure."""

    document_format: ClassVar[DocumentFormat] = DocumentFormat.HTML
    extensions: ClassVar[tuple[str, ...]] = (".html", ".htm", ".xhtml")
    content_types: ClassVar[tuple[str, ...]] = (
        "text/html",
        "application/xhtml+xml",
    )
    is_binary: ClassVar[bool] = False

    def _extract(
        self, data: bytes, warnings: list[str]
    ) -> tuple[str, list[DocumentSection], ExtractExtras]:
        raw_text, encoding = detect_and_decode(data)
        soup = BeautifulSoup(raw_text, "html.parser")

        title = soup.title.get_text(strip=True) if soup.title else None

        author: str | None = None
        meta = soup.find("meta", attrs={"name": _AUTHOR_NAME})
        if isinstance(meta, Tag):
            content = meta.get("content")
            if isinstance(content, str):
                author = content.strip()

        for tag in soup(_DROP_TAGS):
            tag.decompose()

        root = soup.body if soup.body is not None else soup

        sections: list[DocumentSection] = []
        for element in root.find_all(_BLOCK_TAGS):
            if not isinstance(element, Tag):
                continue
            element_text = element.get_text(" ", strip=True)
            if not element_text:
                continue
            section_type, level = _section_type_for(element.name)
            sections.append(
                DocumentSection(
                    order=len(sections),
                    section_type=section_type,
                    text=element_text,
                    level=level,
                )
            )

        plain_text = root.get_text("\n", strip=True)
        extras: ExtractExtras = {"encoding": encoding, "title": title, "author": author}
        return plain_text, sections, extras

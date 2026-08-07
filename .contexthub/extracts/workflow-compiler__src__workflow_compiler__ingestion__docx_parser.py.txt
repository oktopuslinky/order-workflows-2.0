"""DOCX (Office Open XML) document parser built on python-docx."""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from typing import ClassVar

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from workflow_compiler.exceptions import ParseError
from workflow_compiler.ingestion.base import BaseDocumentParser, ExtractExtras
from workflow_compiler.ingestion.content import (
    DocumentFormat,
    DocumentSection,
    SectionType,
)

_HEADING_LEVEL = re.compile(r"heading\s+(\d+)", re.IGNORECASE)


def _iter_block_items(document: DocumentObject) -> Iterator[Paragraph | Table]:
    """Yield paragraphs and tables in document order."""
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _table_text(table: Table) -> str:
    """Flatten a table into ``cell | cell`` rows separated by newlines."""
    rows: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


class DocxParser(BaseDocumentParser):
    """Parse DOCX documents into headings, paragraphs, and tables."""

    document_format: ClassVar[DocumentFormat] = DocumentFormat.DOCX
    extensions: ClassVar[tuple[str, ...]] = (".docx",)
    content_types: ClassVar[tuple[str, ...]] = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    is_binary: ClassVar[bool] = True

    def _extract(
        self, data: bytes, warnings: list[str]
    ) -> tuple[str, list[DocumentSection], ExtractExtras]:
        try:
            document = Document(io.BytesIO(data))
        except Exception as exc:
            raise ParseError(f"Invalid or corrupt DOCX document: {exc}") from exc

        sections: list[DocumentSection] = []
        text_parts: list[str] = []

        for block in _iter_block_items(document):
            if isinstance(block, Paragraph):
                content = block.text.strip()
                if not content:
                    continue
                style_name = block.style.name if block.style else ""
                heading_match = _HEADING_LEVEL.search(style_name or "")
                if heading_match:
                    sections.append(
                        DocumentSection(
                            order=len(sections),
                            section_type=SectionType.HEADING,
                            text=content,
                            level=int(heading_match.group(1)),
                        )
                    )
                else:
                    sections.append(
                        DocumentSection(
                            order=len(sections),
                            section_type=SectionType.PARAGRAPH,
                            text=content,
                        )
                    )
                text_parts.append(content)
            else:  # Table
                table_text = _table_text(block)
                if table_text:
                    sections.append(
                        DocumentSection(
                            order=len(sections),
                            section_type=SectionType.TABLE,
                            text=table_text,
                        )
                    )
                    text_parts.append(table_text)

        props = document.core_properties
        extras: ExtractExtras = {
            "encoding": None,
            "title": props.title,
            "author": props.author,
            "created_at": props.created,
            "modified_at": props.modified,
        }
        return "\n\n".join(text_parts), sections, extras

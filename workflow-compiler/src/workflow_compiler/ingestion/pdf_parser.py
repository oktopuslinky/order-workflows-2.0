"""PDF document parser built on pypdf."""

from __future__ import annotations

import io
from typing import ClassVar

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from workflow_compiler.exceptions import ParseError
from workflow_compiler.ingestion.base import BaseDocumentParser, ExtractExtras
from workflow_compiler.ingestion.content import (
    DocumentFormat,
    DocumentSection,
    SectionType,
)


class PdfParser(BaseDocumentParser):
    """Parse PDF documents page-by-page, extracting text and document info."""

    document_format: ClassVar[DocumentFormat] = DocumentFormat.PDF
    extensions: ClassVar[tuple[str, ...]] = (".pdf",)
    content_types: ClassVar[tuple[str, ...]] = ("application/pdf",)
    is_binary: ClassVar[bool] = True

    def _extract(
        self, data: bytes, warnings: list[str]
    ) -> tuple[str, list[DocumentSection], ExtractExtras]:
        try:
            reader = PdfReader(io.BytesIO(data))
        except (PdfReadError, OSError, ValueError) as exc:
            raise ParseError(f"Invalid or corrupt PDF document: {exc}") from exc

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                warnings.append("PDF is encrypted; extracted text may be incomplete.")

        sections: list[DocumentSection] = []
        page_texts: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception as exc:
                warnings.append(f"Failed to extract text from page {index}: {exc}")
                page_text = ""
            sections.append(
                DocumentSection(
                    order=index - 1,
                    section_type=SectionType.PAGE,
                    text=page_text,
                    level=index,
                )
            )
            if page_text:
                page_texts.append(page_text)

        extras: ExtractExtras = {"encoding": None, "page_count": len(reader.pages)}
        self._merge_document_info(reader, extras, warnings)
        return "\n\n".join(page_texts), sections, extras

    @staticmethod
    def _merge_document_info(
        reader: PdfReader, extras: ExtractExtras, warnings: list[str]
    ) -> None:
        """Merge pypdf document information into ``extras`` defensively."""
        info = reader.metadata
        if info is None:
            return
        extras["title"] = info.title
        extras["author"] = info.author
        for key, attr in (("created_at", "creation_date"), ("modified_at", "modification_date")):
            try:
                extras[key] = getattr(info, attr)
            except Exception:
                warnings.append(f"Could not parse PDF {attr}.")

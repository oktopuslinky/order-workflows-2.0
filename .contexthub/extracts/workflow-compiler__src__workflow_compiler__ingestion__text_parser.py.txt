"""Plain-text (.txt) document parser."""

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

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


class TextParser(BaseDocumentParser):
    """Parse plain-text documents, splitting on blank lines into paragraphs."""

    document_format: ClassVar[DocumentFormat] = DocumentFormat.TXT
    extensions: ClassVar[tuple[str, ...]] = (".txt", ".text")
    content_types: ClassVar[tuple[str, ...]] = ("text/plain",)
    is_binary: ClassVar[bool] = False

    def _extract(
        self, data: bytes, warnings: list[str]
    ) -> tuple[str, list[DocumentSection], ExtractExtras]:
        text, encoding = detect_and_decode(data)
        normalized = normalize_text(text)

        sections: list[DocumentSection] = []
        for block in _PARAGRAPH_SPLIT.split(normalized):
            cleaned = block.strip()
            if cleaned:
                sections.append(
                    DocumentSection(
                        order=len(sections),
                        section_type=SectionType.PARAGRAPH,
                        text=cleaned,
                    )
                )

        return text, sections, {"encoding": encoding}

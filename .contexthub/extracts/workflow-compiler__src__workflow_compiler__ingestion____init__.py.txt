"""Document ingestion layer.

Parsers accept DOCX, PDF, TXT, Markdown, and HTML sources and produce a
uniform :class:`DocumentContent`. Use :class:`DocumentParserFactory` to select
a parser automatically by format, content type, or file extension.
"""

from __future__ import annotations

from workflow_compiler.ingestion.base import (
    DEFAULT_MAX_SIZE_BYTES,
    BaseDocumentParser,
    normalize_text,
)
from workflow_compiler.ingestion.content import (
    DocumentContent,
    DocumentFormat,
    DocumentMetadata,
    DocumentSection,
    SectionType,
)
from workflow_compiler.ingestion.docx_parser import DocxParser
from workflow_compiler.ingestion.encoding import detect_and_decode
from workflow_compiler.ingestion.factory import DocumentParserFactory
from workflow_compiler.ingestion.html_parser import HtmlParser
from workflow_compiler.ingestion.markdown_parser import MarkdownParser
from workflow_compiler.ingestion.pdf_parser import PdfParser
from workflow_compiler.ingestion.text_parser import TextParser

__all__ = [
    "DEFAULT_MAX_SIZE_BYTES",
    "BaseDocumentParser",
    "DocumentContent",
    "DocumentFormat",
    "DocumentMetadata",
    "DocumentParserFactory",
    "DocumentSection",
    "DocxParser",
    "HtmlParser",
    "MarkdownParser",
    "PdfParser",
    "SectionType",
    "TextParser",
    "detect_and_decode",
    "normalize_text",
]

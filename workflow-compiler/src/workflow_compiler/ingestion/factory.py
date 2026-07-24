"""Factory for selecting and applying the correct document parser."""

from __future__ import annotations

from pathlib import Path

from workflow_compiler.exceptions import UnsupportedFormatError
from workflow_compiler.ingestion.base import DEFAULT_MAX_SIZE_BYTES, BaseDocumentParser
from workflow_compiler.ingestion.content import DocumentContent, DocumentFormat
from workflow_compiler.ingestion.docx_parser import DocxParser
from workflow_compiler.ingestion.html_parser import HtmlParser
from workflow_compiler.ingestion.markdown_parser import MarkdownParser
from workflow_compiler.ingestion.pdf_parser import PdfParser
from workflow_compiler.ingestion.text_parser import TextParser


class DocumentParserFactory:
    """Resolve a :class:`BaseDocumentParser` by format, extension, or content type.

    The factory owns a registry of parser instances keyed by
    :class:`DocumentFormat`, with derived lookup tables for file extensions and
    MIME content types. Custom parsers can be registered to override defaults.
    """

    def __init__(
        self,
        parsers: list[BaseDocumentParser] | None = None,
        *,
        max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    ) -> None:
        """Build a factory, registering default parsers unless ``parsers`` given."""
        self._by_format: dict[DocumentFormat, BaseDocumentParser] = {}
        self._by_extension: dict[str, BaseDocumentParser] = {}
        self._by_content_type: dict[str, BaseDocumentParser] = {}
        for parser in parsers or self._default_parsers(max_size_bytes):
            self.register(parser)

    @staticmethod
    def _default_parsers(max_size_bytes: int) -> list[BaseDocumentParser]:
        """Instantiate the built-in parser set."""
        return [
            TextParser(max_size_bytes=max_size_bytes),
            MarkdownParser(max_size_bytes=max_size_bytes),
            HtmlParser(max_size_bytes=max_size_bytes),
            DocxParser(max_size_bytes=max_size_bytes),
            PdfParser(max_size_bytes=max_size_bytes),
        ]

    # -- registration -------------------------------------------------------

    def register(self, parser: BaseDocumentParser) -> None:
        """Register (or override) a parser and refresh lookup tables."""
        self._by_format[parser.document_format] = parser
        for extension in parser.extensions:
            self._by_extension[extension.lower()] = parser
        for content_type in parser.content_types:
            self._by_content_type[content_type.lower()] = parser

    @property
    def supported_formats(self) -> frozenset[DocumentFormat]:
        """Formats this factory can parse."""
        return frozenset(self._by_format)

    # -- selection ----------------------------------------------------------

    def for_format(self, document_format: DocumentFormat) -> BaseDocumentParser:
        """Return the parser registered for ``document_format``."""
        parser = self._by_format.get(document_format)
        if parser is None:
            raise UnsupportedFormatError(
                f"No parser registered for format '{document_format.value}'."
            )
        return parser

    def for_extension(self, extension: str) -> BaseDocumentParser:
        """Return the parser registered for a file ``extension`` (e.g. '.pdf')."""
        normalized = extension.lower()
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        parser = self._by_extension.get(normalized)
        if parser is None:
            raise UnsupportedFormatError(
                f"No parser registered for extension '{normalized}'."
            )
        return parser

    def for_content_type(self, content_type: str) -> BaseDocumentParser:
        """Return the parser registered for a MIME ``content_type``."""
        base_type = content_type.split(";", 1)[0].strip().lower()
        parser = self._by_content_type.get(base_type)
        if parser is None:
            raise UnsupportedFormatError(
                f"No parser registered for content type '{base_type}'."
            )
        return parser

    def select(
        self,
        *,
        document_format: DocumentFormat | None = None,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> BaseDocumentParser:
        """Select a parser using, in order: explicit format, content type, extension."""
        if document_format is not None:
            return self.for_format(document_format)
        if content_type:
            try:
                return self.for_content_type(content_type)
            except UnsupportedFormatError:
                if not filename:
                    raise
        if filename:
            suffix = Path(filename).suffix
            if suffix:
                return self.for_extension(suffix)
        raise UnsupportedFormatError(
            "Could not determine a parser: provide a document_format, a recognized "
            "content_type, or a filename with a known extension."
        )

    # -- convenience --------------------------------------------------------

    def parse(
        self,
        source: str | bytes | Path,
        *,
        document_format: DocumentFormat | None = None,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> DocumentContent:
        """Select the appropriate parser and parse ``source`` end-to-end."""
        if filename is None and isinstance(source, (str, Path)):
            candidate = Path(source)
            try:
                if candidate.is_file():
                    filename = candidate.name
            except OSError:
                filename = None

        parser = self.select(
            document_format=document_format,
            filename=filename,
            content_type=content_type,
        )
        return parser.parse(source, filename=filename, content_type=content_type)

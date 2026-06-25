"""Abstract base parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from workflow_compiler.models import WorkflowMetadata


class BaseParser(ABC):
    """Turns a raw source document into normalized text and provisional metadata.

    Concrete parsers handle specific input formats (markdown, docx, html, plain
    text, ...). The compiler selects a parser via :meth:`can_parse`.
    """

    #: Short, unique name for the parser implementation.
    name: str = "base"

    @abstractmethod
    def can_parse(self, *, content_type: str | None, filename: str | None) -> bool:
        """Return ``True`` if this parser can handle the given input descriptor."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw: str | bytes) -> str:
        """Normalize a raw document into plain workflow text."""
        raise NotImplementedError

    @abstractmethod
    def extract_metadata(self, document_text: str) -> WorkflowMetadata:
        """Extract provisional metadata from normalized document text."""
        raise NotImplementedError

"""Structured output models for the document ingestion layer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class DocumentFormat(StrEnum):
    """Supported source document formats."""

    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"
    MARKDOWN = "markdown"
    HTML = "html"


class SectionType(StrEnum):
    """Structural kind of a parsed document section."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE = "code"
    QUOTE = "quote"
    PAGE = "page"
    OTHER = "other"


class DocumentSection(WorkflowBaseModel):
    """A single structural unit extracted from a source document."""

    order: int = Field(..., ge=0, description="Zero-based position in reading order.")
    section_type: SectionType = Field(..., description="Structural kind of the section.")
    text: str = Field(..., description="Plain-text content of the section.")
    level: int | None = Field(
        default=None,
        description="Heading level (1-6) or, for PAGE sections, the 1-based page number.",
    )


class DocumentMetadata(WorkflowBaseModel):
    """Metadata describing a parsed source document."""

    filename: str | None = Field(default=None, description="Original file name, if known.")
    content_type: str | None = Field(default=None, description="Declared MIME content type.")
    document_format: DocumentFormat = Field(..., description="Detected/declared document format.")
    size_bytes: int = Field(..., ge=0, description="Raw source size in bytes.")
    encoding: str | None = Field(
        default=None, description="Resolved text encoding (text formats only)."
    )

    title: str | None = Field(default=None, description="Document title, if embedded.")
    author: str | None = Field(default=None, description="Document author, if embedded.")
    created_at: datetime | None = Field(default=None, description="Embedded creation timestamp.")
    modified_at: datetime | None = Field(
        default=None, description="Embedded modification timestamp."
    )

    page_count: int | None = Field(default=None, ge=0, description="Page count (paged formats).")
    word_count: int = Field(default=0, ge=0, description="Whitespace-delimited word count.")
    char_count: int = Field(default=0, ge=0, description="Character count of extracted text.")

    extra: dict[str, str] = Field(
        default_factory=dict, description="Additional format-specific metadata."
    )


class DocumentContent(WorkflowBaseModel):
    """The structured result of parsing a source document.

    This is the single output type of every parser in the ingestion layer and
    the hand-off into the rest of the compilation pipeline.
    """

    text: str = Field(..., description="Normalized plain-text content of the document.")
    document_format: DocumentFormat = Field(..., description="Format the document was parsed as.")
    metadata: DocumentMetadata = Field(..., description="Document metadata.")
    sections: list[DocumentSection] = Field(
        default_factory=list, description="Ordered structural sections."
    )
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal issues encountered during parsing."
    )

    @property
    def is_empty(self) -> bool:
        """Return ``True`` if the extracted text is blank."""
        return not self.text.strip()

    def sections_of_type(self, section_type: SectionType) -> list[DocumentSection]:
        """Return all sections matching ``section_type`` in reading order."""
        return [s for s in self.sections if s.section_type == section_type]

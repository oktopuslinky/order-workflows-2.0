"""Base document parser: orchestration, validation, and metadata assembly."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from workflow_compiler.exceptions import (
    EmptyDocumentError,
    FileValidationError,
    ParseError,
)
from workflow_compiler.ingestion.content import (
    DocumentContent,
    DocumentFormat,
    DocumentMetadata,
    DocumentSection,
)

#: Default maximum accepted source size (25 MiB).
DEFAULT_MAX_SIZE_BYTES = 25 * 1024 * 1024

#: Keys a parser may populate in the ``extras`` mapping returned by ``_extract``.
ExtractExtras = dict[str, Any]


def normalize_text(text: str) -> str:
    """Normalize newlines and whitespace in extracted text."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class BaseDocumentParser(ABC):
    """Abstract base class for all document parsers.

    Concrete parsers implement :meth:`_extract`; the base class handles reading
    the source, validation, text normalization, and metadata assembly so every
    parser returns a consistent :class:`DocumentContent`.
    """

    document_format: ClassVar[DocumentFormat]
    extensions: ClassVar[tuple[str, ...]] = ()
    content_types: ClassVar[tuple[str, ...]] = ()
    #: Binary formats reject raw ``str`` content (they need bytes or a file path).
    is_binary: ClassVar[bool] = False

    def __init__(self, *, max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES) -> None:
        """Configure parser-wide limits."""
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be positive.")
        self.max_size_bytes = max_size_bytes

    @property
    def name(self) -> str:
        """Short, stable name for this parser."""
        return f"{self.document_format.value}-parser"

    # -- public API ---------------------------------------------------------

    def parse(
        self,
        source: str | bytes | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> DocumentContent:
        """Parse ``source`` into a :class:`DocumentContent`.

        ``source`` may be a filesystem path (``Path`` or path-like ``str``),
        raw ``bytes``, or, for text formats, a ``str`` of document content.
        """
        data, resolved_name = self._read_source(source, filename)
        self._validate(data, resolved_name)

        warnings: list[str] = []
        self._check_descriptor(resolved_name, content_type, warnings)

        try:
            text, sections, extras = self._extract(data, warnings)
        except ParseError:
            raise
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise ParseError(
                f"{self.name} failed to parse document "
                f"{resolved_name or '<bytes>'}: {exc}"
            ) from exc

        text = normalize_text(text)
        metadata = self._build_metadata(data, resolved_name, content_type, text, extras)
        return DocumentContent(
            text=text,
            document_format=self.document_format,
            metadata=metadata,
            sections=sections,
            warnings=warnings,
        )

    def parse_file(
        self, path: str | Path, *, content_type: str | None = None
    ) -> DocumentContent:
        """Convenience wrapper to parse a document from a filesystem path."""
        return self.parse(Path(path), content_type=content_type)

    # -- subclass contract --------------------------------------------------

    @abstractmethod
    def _extract(
        self, data: bytes, warnings: list[str]
    ) -> tuple[str, list[DocumentSection], ExtractExtras]:
        """Extract ``(plain_text, sections, extras)`` from raw ``data``.

        Implementations may append non-fatal messages to ``warnings`` and should
        raise :class:`ParseError` (or a subclass) on unrecoverable failures.
        """
        raise NotImplementedError

    # -- helpers ------------------------------------------------------------

    def _read_source(
        self, source: str | bytes | Path, filename: str | None
    ) -> tuple[bytes, str | None]:
        """Resolve ``source`` to ``(bytes, filename)``."""
        if isinstance(source, Path):
            return self._read_path(source)
        if isinstance(source, bytes):
            return source, filename
        if isinstance(source, str):
            if self._looks_like_path(source):
                return self._read_path(Path(source))
            if self.is_binary:
                raise FileValidationError(
                    f"{self.name} requires bytes or a file path, not raw string content."
                )
            return source.encode("utf-8"), filename
        raise TypeError(f"Unsupported source type: {type(source)!r}")

    def _read_path(self, path: Path) -> tuple[bytes, str]:
        """Read and return the bytes of a file path."""
        if not path.exists():
            raise FileValidationError(f"Source file does not exist: {path}")
        if not path.is_file():
            raise FileValidationError(f"Source path is not a file: {path}")
        try:
            return path.read_bytes(), path.name
        except OSError as exc:
            raise FileValidationError(f"Could not read source file {path}: {exc}") from exc

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        """Best-effort check whether a string refers to an existing file."""
        try:
            return Path(value).is_file()
        except OSError:
            return False

    def _validate(self, data: bytes, filename: str | None) -> None:
        """Validate raw source bytes prior to extraction."""
        if len(data) == 0:
            raise EmptyDocumentError(
                f"Document {filename or '<bytes>'} is empty."
            )
        if len(data) > self.max_size_bytes:
            raise FileValidationError(
                f"Document {filename or '<bytes>'} is {len(data)} bytes, "
                f"exceeding the limit of {self.max_size_bytes} bytes."
            )

    def _check_descriptor(
        self, filename: str | None, content_type: str | None, warnings: list[str]
    ) -> None:
        """Warn (do not fail) when filename/content-type mismatch this parser."""
        if filename and self.extensions:
            suffix = Path(filename).suffix.lower()
            if suffix and suffix not in self.extensions:
                warnings.append(
                    f"File extension '{suffix}' is unexpected for {self.name} "
                    f"(expected one of {', '.join(self.extensions)})."
                )
        if content_type and self.content_types:
            base_type = content_type.split(";", 1)[0].strip().lower()
            if base_type and base_type not in self.content_types:
                warnings.append(
                    f"Content type '{base_type}' is unexpected for {self.name}."
                )

    def _build_metadata(
        self,
        data: bytes,
        filename: str | None,
        content_type: str | None,
        text: str,
        extras: ExtractExtras,
    ) -> DocumentMetadata:
        """Assemble a :class:`DocumentMetadata` from common and extra fields."""
        raw_extra = extras.get("extra", {})
        extra = {str(k): str(v) for k, v in raw_extra.items()} if raw_extra else {}
        return DocumentMetadata(
            filename=filename,
            content_type=content_type,
            document_format=self.document_format,
            size_bytes=len(data),
            encoding=extras.get("encoding"),
            title=_clean_str(extras.get("title")),
            author=_clean_str(extras.get("author")),
            created_at=_as_datetime(extras.get("created_at")),
            modified_at=_as_datetime(extras.get("modified_at")),
            page_count=extras.get("page_count"),
            word_count=len(text.split()),
            char_count=len(text),
            extra=extra,
        )


def _clean_str(value: Any) -> str | None:
    """Coerce a metadata value to a non-empty stripped string, or ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_datetime(value: Any) -> datetime | None:
    """Return ``value`` if it is a datetime, otherwise ``None``."""
    return value if isinstance(value, datetime) else None

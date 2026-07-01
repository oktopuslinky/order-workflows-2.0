"""File-backed store persisting DocumentCompilation aggregates as JSON on disk.

Mirrors :class:`~workflow_compiler.storage.file.FileStateStore` but for the outer
multi-workflow :class:`~workflow_compiler.models.compilation.DocumentCompilation`.
Files are written as ``<root>/doc-<document_id>.json`` so they sit alongside the
per-workflow ``<workflow_id>.json`` state files without colliding.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.models import DocumentCompilation
from workflow_compiler.storage.file import DEFAULT_ROOT


class DocumentStore:
    """Persist :class:`DocumentCompilation` objects as ``<root>/doc-<id>.json``.

    Writes are atomic (write-to-temp then ``os.replace``); blocking filesystem
    work runs in a worker thread via :func:`asyncio.to_thread`.
    """

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        """Create the store rooted at ``root``; the directory is created lazily."""
        self._root = Path(root)

    def _path(self, document_id: str) -> Path:
        """Return the on-disk path for ``document_id``."""
        return self._root / f"doc-{document_id}.json"

    def _write(self, doc: DocumentCompilation) -> None:
        """Atomically write ``doc`` to its JSON file (blocking)."""
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(doc.document_id)
        payload = doc.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            tmp.replace(target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _read(self, document_id: str) -> DocumentCompilation:
        """Read and validate the compilation for ``document_id`` (blocking)."""
        path = self._path(document_id)
        if not path.is_file():
            raise StateNotFoundError(f"No document compilation with id {document_id!r}.")
        return DocumentCompilation.model_validate_json(path.read_text(encoding="utf-8"))

    async def save(self, doc: DocumentCompilation) -> None:
        """Persist ``doc`` to disk atomically."""
        await asyncio.to_thread(self._write, doc)

    async def load(self, document_id: str) -> DocumentCompilation:
        """Load a compilation by id, raising ``StateNotFoundError`` if absent."""
        return await asyncio.to_thread(self._read, document_id)

    async def exists(self, document_id: str) -> bool:
        """Return ``True`` if a compilation file exists for ``document_id``."""
        return await asyncio.to_thread(self._path(document_id).is_file)

    async def list_ids(self) -> list[str]:
        """Return the ids of all persisted compilations, sorted for determinism."""

        def _list() -> list[str]:
            if not self._root.is_dir():
                return []
            return sorted(p.stem[len("doc-") :] for p in self._root.glob("doc-*.json"))

        return await asyncio.to_thread(_list)

"""Persistence for :class:`KnowledgeBase` records and their on-disk corpus/graph.

Layout under the state root::

    <root>/knowledge_bases/<kb_id>.json          the record
    <root>/knowledge_bases/<kb_id>/corpus/       the extracted corpus (node ids are
                                                 relative to this directory)
    <root>/knowledge_bases/<kb_id>/.contexthub/  graph.json, manifest.json, extracts/,
                                                 llm_cache/

Every id crossing this boundary is validated against ``[A-Za-z0-9_-]+`` first: a
kb id is used to build filesystem paths, so anything else (``..``, separators,
drive letters) is refused as "not found" rather than resolved.
"""

from __future__ import annotations

import asyncio
import copy
import re
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.kg.models import KnowledgeBase
from workflow_compiler.storage.file import DEFAULT_ROOT

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_kb_id(kb_id: str) -> str:
    """Return ``kb_id`` if it is a safe identifier, else raise ``StateNotFoundError``.

    Raising *not found* (not *bad request*) is deliberate: an id that cannot
    exist is indistinguishable from one that does not, and the check must never
    leak whether path-shaped input would have resolved to something.
    """
    if not kb_id or not _ID_RE.match(kb_id):
        raise StateNotFoundError(f"No knowledge base with id {kb_id!r}.")
    return kb_id


class KnowledgeBaseStore(Protocol):
    """Persistence contract for knowledge bases (record + directory)."""

    def kb_dir(self, kb_id: str) -> Path:
        """Absolute directory that holds ``corpus/`` and ``.contexthub/`` for ``kb_id``."""
        ...

    async def save(self, kb: KnowledgeBase) -> None: ...

    async def load(self, kb_id: str) -> KnowledgeBase: ...

    async def exists(self, kb_id: str) -> bool: ...

    async def list_ids(self) -> list[str]: ...

    async def delete(self, kb_id: str) -> None:
        """Remove the record and the whole directory (corpus + graph). No-op if absent."""
        ...


class FileKnowledgeBaseStore:
    """JSON-file store under ``<root>/knowledge_bases``; writes are atomic."""

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        self._root = Path(root).resolve() / "knowledge_bases"

    @property
    def root(self) -> Path:
        return self._root

    def kb_dir(self, kb_id: str) -> Path:
        return self._root / validate_kb_id(kb_id)

    def _path(self, kb_id: str) -> Path:
        return self._root / f"{validate_kb_id(kb_id)}.json"

    def _write(self, kb: KnowledgeBase) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(kb.kb_id)
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                handle.write(kb.model_dump_json(indent=2))
            tmp.replace(target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _read(self, kb_id: str) -> KnowledgeBase:
        path = self._path(kb_id)
        if not path.is_file():
            raise StateNotFoundError(f"No knowledge base with id {kb_id!r}.")
        return KnowledgeBase.model_validate_json(path.read_text(encoding="utf-8"))

    async def save(self, kb: KnowledgeBase) -> None:
        if not kb.root_dir:
            kb.root_dir = str(self.kb_dir(kb.kb_id))
        await asyncio.to_thread(self._write, kb)

    async def load(self, kb_id: str) -> KnowledgeBase:
        return await asyncio.to_thread(self._read, kb_id)

    async def exists(self, kb_id: str) -> bool:
        return await asyncio.to_thread(self._path(kb_id).is_file)

    async def list_ids(self) -> list[str]:
        def _list() -> list[str]:
            if not self._root.is_dir():
                return []
            return sorted(p.stem for p in self._root.glob("*.json"))

        return await asyncio.to_thread(_list)

    async def delete(self, kb_id: str) -> None:
        def _delete() -> None:
            self._path(kb_id).unlink(missing_ok=True)
            directory = self.kb_dir(kb_id)
            if directory.is_dir():
                shutil.rmtree(directory, ignore_errors=True)

        await asyncio.to_thread(_delete)


class InMemoryKnowledgeBaseStore:
    """Dict-backed records for tests; directories still live under ``root`` (a tmp path)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve() / "knowledge_bases"
        self._items: dict[str, KnowledgeBase] = {}

    def kb_dir(self, kb_id: str) -> Path:
        return self._root / validate_kb_id(kb_id)

    async def save(self, kb: KnowledgeBase) -> None:
        validate_kb_id(kb.kb_id)
        if not kb.root_dir:
            kb.root_dir = str(self.kb_dir(kb.kb_id))
        self._items[kb.kb_id] = copy.deepcopy(kb)

    async def load(self, kb_id: str) -> KnowledgeBase:
        validate_kb_id(kb_id)
        try:
            return copy.deepcopy(self._items[kb_id])
        except KeyError as exc:
            raise StateNotFoundError(f"No knowledge base with id {kb_id!r}.") from exc

    async def exists(self, kb_id: str) -> bool:
        validate_kb_id(kb_id)
        return kb_id in self._items

    async def list_ids(self) -> list[str]:
        return sorted(self._items)

    async def delete(self, kb_id: str) -> None:
        self._items.pop(validate_kb_id(kb_id), None)
        directory = self.kb_dir(kb_id)
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)

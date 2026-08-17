"""Persistence for change requests (``<state-root>/change_requests/<cr_id>.json``).

Mirrors :mod:`workflow_compiler.storage.project_store`: atomic JSON writes, an
in-memory twin for tests, and — like the knowledge-base store — ids are
validated at the boundary so a crafted id can never escape the directory.
"""

from __future__ import annotations

import asyncio
import copy
import re
import tempfile
from pathlib import Path
from typing import Protocol

from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.models.change import ChangeRequest
from workflow_compiler.storage.file import DEFAULT_ROOT

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_cr_id(cr_id: str) -> str:
    """Reject anything that is not a plain token (path traversal guard)."""
    if not cr_id or not _ID_RE.match(cr_id) or len(cr_id) > 128:
        raise StateNotFoundError(f"No change request with id {cr_id!r}.")
    return cr_id


class ChangeRequestStore(Protocol):
    async def save(self, cr: ChangeRequest) -> None: ...

    async def load(self, cr_id: str) -> ChangeRequest: ...

    async def exists(self, cr_id: str) -> bool: ...

    async def list_ids(self) -> list[str]: ...

    async def delete(self, cr_id: str) -> None: ...


class FileChangeRequestStore:
    """Persist :class:`ChangeRequest` aggregates as JSON on disk."""

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        self._root = Path(root) / "change_requests"

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, cr_id: str) -> Path:
        return self._root / f"{validate_cr_id(cr_id)}.json"

    def _write(self, cr: ChangeRequest) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(cr.cr_id)
        payload = cr.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            tmp.replace(target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _read(self, cr_id: str) -> ChangeRequest:
        path = self._path(cr_id)
        if not path.is_file():
            raise StateNotFoundError(f"No change request with id {cr_id!r}.")
        return ChangeRequest.model_validate_json(path.read_text(encoding="utf-8"))

    async def save(self, cr: ChangeRequest) -> None:
        await asyncio.to_thread(self._write, cr)

    async def load(self, cr_id: str) -> ChangeRequest:
        return await asyncio.to_thread(self._read, cr_id)

    async def exists(self, cr_id: str) -> bool:
        return await asyncio.to_thread(self._path(cr_id).is_file)

    async def list_ids(self) -> list[str]:
        def _list() -> list[str]:
            if not self._root.is_dir():
                return []
            return sorted(p.stem for p in self._root.glob("*.json"))

        return await asyncio.to_thread(_list)

    async def delete(self, cr_id: str) -> None:
        def _delete() -> None:
            path = self._path(cr_id)
            if not path.is_file():
                raise StateNotFoundError(f"No change request with id {cr_id!r}.")
            path.unlink()

        await asyncio.to_thread(_delete)


class InMemoryChangeRequestStore:
    """Dict-backed store for tests (deep-copies on save/load)."""

    def __init__(self) -> None:
        self._items: dict[str, ChangeRequest] = {}

    async def save(self, cr: ChangeRequest) -> None:
        self._items[validate_cr_id(cr.cr_id)] = copy.deepcopy(cr)

    async def load(self, cr_id: str) -> ChangeRequest:
        validate_cr_id(cr_id)
        if cr_id not in self._items:
            raise StateNotFoundError(f"No change request with id {cr_id!r}.")
        return copy.deepcopy(self._items[cr_id])

    async def exists(self, cr_id: str) -> bool:
        return cr_id in self._items

    async def list_ids(self) -> list[str]:
        return sorted(self._items)

    async def delete(self, cr_id: str) -> None:
        if cr_id not in self._items:
            raise StateNotFoundError(f"No change request with id {cr_id!r}.")
        del self._items[cr_id]

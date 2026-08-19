"""File-backed state store persisting WorkflowState as JSON on disk."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.interfaces.state_store import StateStore
from workflow_compiler.models import WorkflowState
from workflow_compiler.storage.ids import validate_store_id

#: Default directory (relative to CWD) used when no root is supplied.
DEFAULT_ROOT = ".workflow_state"


class FileStateStore(StateStore):
    """Persist :class:`WorkflowState` objects as ``<root>/<workflow_id>.json``.

    Writes are atomic (write-to-temp then ``os.replace``) so a crash mid-write
    cannot leave a half-written state file. Blocking filesystem work is run in a
    worker thread via :func:`asyncio.to_thread`, keeping the async surface
    non-blocking.
    """

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        """Create the store rooted at ``root``; the directory is created lazily."""
        self._root = Path(root)

    def _path(self, workflow_id: str) -> Path:
        """Return the on-disk path for ``workflow_id``."""
        return self._root / f"{validate_store_id(workflow_id, label='workflow state')}.json"

    def _write(self, state: WorkflowState) -> None:
        """Atomically write ``state`` to its JSON file (blocking)."""
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(state.workflow_id)
        payload = state.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            tmp.replace(target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _read(self, workflow_id: str) -> WorkflowState:
        """Read and validate the state for ``workflow_id`` (blocking)."""
        path = self._path(workflow_id)
        if not path.is_file():
            raise StateNotFoundError(f"No workflow state with id {workflow_id!r}.")
        return WorkflowState.model_validate_json(path.read_text(encoding="utf-8"))

    async def save(self, state: WorkflowState) -> None:
        """Persist ``state`` to disk atomically."""
        await asyncio.to_thread(self._write, state)

    async def load(self, workflow_id: str) -> WorkflowState:
        """Load a state by id, raising ``StateNotFoundError`` if absent."""
        return await asyncio.to_thread(self._read, workflow_id)

    async def exists(self, workflow_id: str) -> bool:
        """Return ``True`` if a state file exists for ``workflow_id``."""
        return await asyncio.to_thread(self._path(workflow_id).is_file)

    async def delete(self, workflow_id: str) -> None:
        """Remove a state file, raising ``StateNotFoundError`` if absent."""

        def _delete() -> None:
            path = self._path(workflow_id)
            if not path.is_file():
                raise StateNotFoundError(f"No workflow state with id {workflow_id!r}.")
            path.unlink()

        await asyncio.to_thread(_delete)

    async def list_ids(self) -> list[str]:
        """Return the ids of all persisted states, sorted for determinism."""

        def _list() -> list[str]:
            if not self._root.is_dir():
                return []
            return sorted(p.stem for p in self._root.glob("*.json"))

        return await asyncio.to_thread(_list)

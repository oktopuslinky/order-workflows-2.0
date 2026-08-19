"""Persistence for CompilationProject aggregates (mirrors the state stores).

Projects are stored under ``<root>/projects/<project_id>.json`` so they never
collide with per-workflow state files in ``<root>``. Writes are atomic, exactly
like :class:`~workflow_compiler.storage.file.FileStateStore`.
"""

from __future__ import annotations

import asyncio
import copy
import tempfile
from pathlib import Path
from typing import Protocol

from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.models import CompilationProject
from workflow_compiler.storage.file import DEFAULT_ROOT
from workflow_compiler.storage.ids import next_version, stored_version, validate_store_id


class ProjectStore(Protocol):
    """Persistence contract for :class:`CompilationProject` aggregates."""

    async def save(
        self, project: CompilationProject, *, expected_version: int | None = None
    ) -> None:
        """Persist ``project``; ``expected_version`` enables compare-and-swap (409 on stale)."""
        ...

    async def load(self, project_id: str) -> CompilationProject:
        """Load a project by id, raising ``StateNotFoundError`` if absent."""
        ...

    async def exists(self, project_id: str) -> bool:
        """Return ``True`` if ``project_id`` is stored."""
        ...

    async def list_ids(self) -> list[str]:
        """Return all stored project ids."""
        ...


class FileProjectStore:
    """Persist :class:`CompilationProject` objects as JSON on disk."""

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        """Create the store; projects live in ``<root>/projects``."""
        self._root = Path(root) / "projects"

    def _path(self, project_id: str) -> Path:
        return self._root / f"{validate_store_id(project_id, label='project')}.json"

    def _write(self, project: CompilationProject, expected_version: int | None) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(project.project_id)
        project.version = next_version(
            stored_version(target), expected_version, label="project", key=project.project_id
        )
        payload = project.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            tmp.replace(target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _read(self, project_id: str) -> CompilationProject:
        path = self._path(project_id)
        if not path.is_file():
            raise StateNotFoundError(f"No project with id {project_id!r}.")
        return CompilationProject.model_validate_json(path.read_text(encoding="utf-8"))

    async def save(
        self, project: CompilationProject, *, expected_version: int | None = None
    ) -> None:
        """Persist ``project`` to disk atomically (CAS when ``expected_version`` is given)."""
        await asyncio.to_thread(self._write, project, expected_version)

    async def load(self, project_id: str) -> CompilationProject:
        """Load a project by id, raising ``StateNotFoundError`` if absent."""
        return await asyncio.to_thread(self._read, project_id)

    async def exists(self, project_id: str) -> bool:
        """Return ``True`` if a project file exists for ``project_id``."""
        return await asyncio.to_thread(self._path(project_id).is_file)

    async def list_ids(self) -> list[str]:
        """Return the ids of all persisted projects, sorted for determinism."""

        def _list() -> list[str]:
            if not self._root.is_dir():
                return []
            return sorted(p.stem for p in self._root.glob("*.json"))

        return await asyncio.to_thread(_list)


class InMemoryProjectStore:
    """Dict-backed project store for tests (deep-copies on save/load)."""

    def __init__(self) -> None:
        self._projects: dict[str, CompilationProject] = {}

    async def save(
        self, project: CompilationProject, *, expected_version: int | None = None
    ) -> None:
        """Store a deep copy of ``project`` (CAS when ``expected_version`` is given)."""
        validate_store_id(project.project_id, label="project")
        current = self._projects.get(project.project_id)
        project.version = next_version(
            current.version if current is not None else None,
            expected_version,
            label="project",
            key=project.project_id,
        )
        self._projects[project.project_id] = copy.deepcopy(project)

    async def load(self, project_id: str) -> CompilationProject:
        """Return a deep copy of the stored project, raising if absent."""
        if project_id not in self._projects:
            raise StateNotFoundError(f"No project with id {project_id!r}.")
        return copy.deepcopy(self._projects[project_id])

    async def exists(self, project_id: str) -> bool:
        """Return ``True`` if ``project_id`` is stored."""
        return project_id in self._projects

    async def list_ids(self) -> list[str]:
        """Return all stored project ids, sorted."""
        return sorted(self._projects)

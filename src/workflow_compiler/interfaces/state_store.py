"""Abstract state store interface for persisting WorkflowState."""

from __future__ import annotations

from abc import ABC, abstractmethod

from workflow_compiler.models import WorkflowState


class StateStore(ABC):
    """Persistence boundary for :class:`WorkflowState` objects.

    Implementations may be in-memory, file-backed, SQLite, or remote. The
    compiler depends only on this surface.
    """

    @abstractmethod
    async def save(self, state: WorkflowState) -> None:
        """Persist (insert or update) a workflow state by its ``workflow_id``."""
        raise NotImplementedError

    @abstractmethod
    async def load(self, workflow_id: str) -> WorkflowState:
        """Load a workflow state by id, raising ``StateNotFoundError`` if absent."""
        raise NotImplementedError

    @abstractmethod
    async def exists(self, workflow_id: str) -> bool:
        """Return ``True`` if a state with the given id is stored."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, workflow_id: str) -> None:
        """Remove a workflow state by id."""
        raise NotImplementedError

    @abstractmethod
    async def list_ids(self) -> list[str]:
        """Return the ids of all stored workflow states."""
        raise NotImplementedError

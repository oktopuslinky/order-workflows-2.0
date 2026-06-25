"""In-memory state store, primarily for tests and ephemeral runs."""

from __future__ import annotations

from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.interfaces.state_store import StateStore
from workflow_compiler.models import WorkflowState


class InMemoryStateStore(StateStore):
    """A process-local :class:`StateStore` backed by a dictionary.

    States are deep-copied on the way in and out so callers cannot mutate
    stored state by holding a reference, mirroring the isolation a persistent
    store provides.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        self._states: dict[str, WorkflowState] = {}

    async def save(self, state: WorkflowState) -> None:
        """Insert or replace ``state`` keyed by its ``workflow_id``."""
        self._states[state.workflow_id] = state.model_copy(deep=True)

    async def load(self, workflow_id: str) -> WorkflowState:
        """Return a copy of the stored state, or raise ``StateNotFoundError``."""
        try:
            state = self._states[workflow_id]
        except KeyError as exc:
            raise StateNotFoundError(f"No workflow state with id {workflow_id!r}.") from exc
        return state.model_copy(deep=True)

    async def exists(self, workflow_id: str) -> bool:
        """Return ``True`` if a state with ``workflow_id`` is stored."""
        return workflow_id in self._states

    async def delete(self, workflow_id: str) -> None:
        """Remove a stored state, raising ``StateNotFoundError`` if absent."""
        try:
            del self._states[workflow_id]
        except KeyError as exc:
            raise StateNotFoundError(f"No workflow state with id {workflow_id!r}.") from exc

    async def list_ids(self) -> list[str]:
        """Return the ids of all stored states, sorted for determinism."""
        return sorted(self._states)

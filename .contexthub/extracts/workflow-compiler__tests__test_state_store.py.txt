"""Tests for the in-memory and file-backed state stores."""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.interfaces.state_store import StateStore
from workflow_compiler.models import WorkflowMetadata, WorkflowState
from workflow_compiler.storage import FileStateStore, InMemoryStateStore


def _state(text: str = "doc") -> WorkflowState:
    state = WorkflowState(document_text=text)
    state.workflow_metadata = WorkflowMetadata(name="Sample")
    return state


@pytest.fixture(params=["memory", "file"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> StateStore:
    if request.param == "memory":
        return InMemoryStateStore()
    return FileStateStore(tmp_path / "states")


async def test_save_and_load_round_trip(store: StateStore) -> None:
    state = _state("round trip")
    await store.save(state)
    loaded = await store.load(state.workflow_id)
    assert loaded.workflow_id == state.workflow_id
    assert loaded.document_text == "round trip"
    assert loaded.workflow_metadata is not None
    assert loaded.workflow_metadata.name == "Sample"


async def test_load_missing_raises(store: StateStore) -> None:
    with pytest.raises(StateNotFoundError):
        await store.load("nonexistent")


async def test_exists(store: StateStore) -> None:
    state = _state()
    assert await store.exists(state.workflow_id) is False
    await store.save(state)
    assert await store.exists(state.workflow_id) is True


async def test_save_overwrites(store: StateStore) -> None:
    state = _state("first")
    await store.save(state)
    state.document_text = "second"
    await store.save(state)
    loaded = await store.load(state.workflow_id)
    assert loaded.document_text == "second"


async def test_delete(store: StateStore) -> None:
    state = _state()
    await store.save(state)
    await store.delete(state.workflow_id)
    assert await store.exists(state.workflow_id) is False
    with pytest.raises(StateNotFoundError):
        await store.delete(state.workflow_id)


async def test_list_ids(store: StateStore) -> None:
    assert await store.list_ids() == []
    a, b = _state("a"), _state("b")
    await store.save(a)
    await store.save(b)
    assert sorted(await store.list_ids()) == sorted([a.workflow_id, b.workflow_id])


async def test_in_memory_store_isolates_mutations() -> None:
    store = InMemoryStateStore()
    state = _state("original")
    await store.save(state)
    # Mutating the original after save must not affect the stored copy.
    state.document_text = "mutated"
    loaded = await store.load(state.workflow_id)
    assert loaded.document_text == "original"


async def test_file_store_writes_json(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path / "states")
    state = _state()
    await store.save(state)
    path = tmp_path / "states" / f"{state.workflow_id}.json"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").lstrip().startswith("{")

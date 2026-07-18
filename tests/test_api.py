"""API tests for the FastAPI surface using a mock-backed compiler."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from workflow_compiler import WorkflowCompiler, __version__
from workflow_compiler.agents import (
    CVPAOutput,
    FactExtraction,
    TemporalDesignOutput,
    WorkflowDiscovery,
)
from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import get_compiler
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.user_store import InMemoryUserStore

# Exact MockProvider queue → run with the default-on review pipeline disabled
# (review behavior is covered in tests/test_review_pipeline.py).
_NO_REVIEW = ReviewConfig(enabled=False)


def _structured() -> list[object]:
    return [
        WorkflowDiscovery(name="Orders", purpose="Fulfill orders.", actors=["Customer"]),
        FactExtraction(activities=["Validate payment", "Process order"], decisions=["Valid?"]),
        CVPAOutput.model_validate({"assignments": []}),
        TemporalDesignOutput.model_validate({"workflow_name": "Orders"}),
    ]


@pytest.fixture
def compiler() -> WorkflowCompiler:
    return WorkflowCompiler(
        llm_provider=MockProvider(structured=_structured()),
        state_store=InMemoryStateStore(),
        review=_NO_REVIEW,
    )


@pytest.fixture
def client(compiler: WorkflowCompiler) -> TestClient:
    app.dependency_overrides[get_compiler] = lambda: compiler
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as test_client:
        # Every workflow endpoint requires a session; register signs the client in.
        test_client.post(
            "/auth/register",
            json={
                "email": "tester@example.com",
                "password": "password123",
                "display_name": "Tester",
            },
        )
        yield test_client
    app.dependency_overrides.clear()


def _seed_workflow(compiler: WorkflowCompiler, text: str) -> str:
    """Compile a document via the library API and return its workflow id."""
    state = asyncio.run(compiler.compile_document(text))
    return state.workflow_id


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_classic_compile_endpoint_removed(client: TestClient) -> None:
    response = client.post("/compile", json={"document_text": "anything"})
    assert response.status_code in (404, 405)


def test_get_workflow(client: TestClient, compiler: WorkflowCompiler) -> None:
    workflow_id = _seed_workflow(compiler, "When an order arrives, validate it.")

    got = client.get(f"/workflow/{workflow_id}")
    assert got.status_code == 200
    state = got.json()["state"]
    assert state["workflow_id"] == workflow_id
    assert state["approval_status"] == "pending"
    assert state["stage"] == "reviewed"


def test_approve_runs_downstream(client: TestClient, compiler: WorkflowCompiler) -> None:
    workflow_id = _seed_workflow(compiler, "validate and process the order")

    approved = client.post("/approve", json={"workflow_id": workflow_id, "reviewer": "alice"})
    assert approved.status_code == 200
    state = approved.json()["state"]
    assert state["approval_status"] == "approved"
    assert state["stage"] == "completed"
    assert state["cvpa_classification"] is not None
    assert state["temporal_design"] is not None


def test_reject(client: TestClient, compiler: WorkflowCompiler) -> None:
    workflow_id = _seed_workflow(compiler, "validate and process the order")

    rejected = client.post(
        "/reject", json={"workflow_id": workflow_id, "reason": "needs a missing branch"}
    )
    assert rejected.status_code == 200
    assert rejected.json()["state"]["approval_status"] == "rejected"


def test_get_unknown_returns_404(client: TestClient) -> None:
    response = client.get("/workflow/does-not-exist")
    assert response.status_code == 404


def test_list_workflows(client: TestClient, compiler: WorkflowCompiler) -> None:
    _seed_workflow(compiler, "validate and process the order")
    response = client.get("/workflows")
    assert response.status_code == 200
    assert len(response.json()["workflow_ids"]) == 1

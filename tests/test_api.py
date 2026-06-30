"""API tests for the FastAPI surface using a mock-backed compiler."""

from __future__ import annotations

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
from workflow_compiler.api.dependencies import get_compiler
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.storage import InMemoryStateStore

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
def client() -> TestClient:
    compiler = WorkflowCompiler(
        llm_provider=MockProvider(structured=_structured()),
        state_store=InMemoryStateStore(),
        review=_NO_REVIEW,
    )
    app.dependency_overrides[get_compiler] = lambda: compiler
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_compile_then_get(client: TestClient) -> None:
    response = client.post(
        "/compile", json={"document_text": "When an order arrives, validate it."}
    )
    assert response.status_code == 200
    state = response.json()["state"]
    assert state["approval_status"] == "pending"
    assert state["stage"] == "reviewed"
    workflow_id = state["workflow_id"]

    got = client.get(f"/workflow/{workflow_id}")
    assert got.status_code == 200
    assert got.json()["state"]["workflow_id"] == workflow_id


def test_compile_then_approve_runs_downstream(client: TestClient) -> None:
    compiled = client.post("/compile", json={"document_text": "validate and process the order"})
    workflow_id = compiled.json()["state"]["workflow_id"]

    approved = client.post("/approve", json={"workflow_id": workflow_id, "reviewer": "alice"})
    assert approved.status_code == 200
    state = approved.json()["state"]
    assert state["approval_status"] == "approved"
    assert state["stage"] == "completed"
    assert state["cvpa_classification"] is not None
    assert state["temporal_design"] is not None


def test_reject(client: TestClient) -> None:
    compiled = client.post("/compile", json={"document_text": "validate and process the order"})
    workflow_id = compiled.json()["state"]["workflow_id"]

    rejected = client.post(
        "/reject", json={"workflow_id": workflow_id, "reason": "needs a missing branch"}
    )
    assert rejected.status_code == 200
    assert rejected.json()["state"]["approval_status"] == "rejected"


def test_get_unknown_returns_404(client: TestClient) -> None:
    response = client.get("/workflow/does-not-exist")
    assert response.status_code == 404


def test_list_workflows(client: TestClient) -> None:
    client.post("/compile", json={"document_text": "validate and process the order"})
    response = client.get("/workflows")
    assert response.status_code == 200
    assert len(response.json()["workflow_ids"]) == 1

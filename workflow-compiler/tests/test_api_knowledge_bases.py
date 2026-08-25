"""HTTP tests for the knowledge-base routes: upload → kb_ingest job → ready → query."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import get_kg_service
from workflow_compiler.kg import InMemoryKnowledgeBaseStore, KgService
from workflow_compiler.kg.ingest import zip_folder
from workflow_compiler.kg.service import INTERRUPTED_ERROR
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.storage.user_store import InMemoryUserStore

from .test_kg_service import EnrichmentMock, build_corpus


@pytest.fixture
def corpus_zip(tmp_path: Path) -> bytes:
    return zip_folder(build_corpus(tmp_path / "kb_mini"))


@pytest.fixture
def factory_calls() -> list[tuple[str | None, str | None]]:
    return []


@pytest.fixture
def client(
    tmp_path: Path, factory_calls: list[tuple[str | None, str | None]]
) -> Iterator[TestClient]:
    provider = EnrichmentMock()

    def factory(name: str | None, model: str | None) -> MockProvider:
        factory_calls.append((name, model))
        return provider

    service = KgService(InMemoryKnowledgeBaseStore(tmp_path / "state"), factory)
    app.dependency_overrides[get_kg_service] = lambda: service
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as test_client:
        test_client.post(
            "/auth/register",
            json={"email": "kb@example.com", "password": "password123", "display_name": "KB"},
        )
        yield test_client
    app.dependency_overrides.clear()


def _poll_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _upload(client: TestClient, data: bytes, **form: object) -> dict:
    response = client.post(
        "/knowledge-bases",
        files={"file": ("kb_mini.zip", data, "application/zip")},
        data={k: str(v) for k, v in form.items()},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_upload_creates_kb_and_runs_ingest_job(client: TestClient, corpus_zip: bytes) -> None:
    body = _upload(client, corpus_zip, name="Mini KB", enrich="false")
    assert body["name"] == "Mini KB"
    assert body["status"] == "ingesting"
    assert body["source"] == {"kind": "zip", "filename": "kb_mini.zip"}
    job = body["job"]
    assert job["kind"] == "kb_ingest"
    assert job["scope_kind"] == "knowledge_base"
    assert job["scope_id"] == body["kb_id"] == job["project_id"]

    done = _poll_job(client, job["job_id"])
    assert done["status"] == "succeeded", done
    assert done["project"] is None  # not a project job
    assert done["progress"]["message"]

    kb = client.get(f"/knowledge-bases/{body['kb_id']}").json()
    assert kb["status"] == "ready"
    assert kb["llm_enriched"] is False
    assert kb["stats"]["by_type"]["Module"] == 3
    assert "US-001" in kb["catalog"]["stories"]
    assert kb["job"] is None  # nothing running any more

    listed = client.get("/knowledge-bases").json()["knowledge_bases"]
    assert [k["kb_id"] for k in listed] == [body["kb_id"]]

    # The JobManager lives on the shared app instance, so other test modules'
    # jobs may still be visible here; assert on scope filtering, not emptiness.
    kb_jobs = client.get("/jobs", params={"scope_kind": "knowledge_base"}).json()
    assert job["job_id"] in [j["job_id"] for j in kb_jobs]
    assert all(j["scope_kind"] == "knowledge_base" for j in kb_jobs)
    project_jobs = client.get("/jobs", params={"scope_kind": "project"}).json()
    assert job["job_id"] not in [j["job_id"] for j in project_jobs]


def test_ingesting_kb_without_a_job_is_reported_as_interrupted(
    client: TestClient, corpus_zip: bytes
) -> None:
    """A record stuck at ``ingesting`` with no live job (server restarted mid-index,
    e.g. a ``uvicorn --reload`` triggered by the corpus's own ``*.py`` files) must not
    show "indexing" forever: the routes mark it failed with a reindex hint."""
    service = app.dependency_overrides[get_kg_service]()
    kb = asyncio.run(service.create_from_zip("Orphan", corpus_zip, filename="kb_mini.zip"))
    assert kb.status == "ingesting"

    listed = {k["kb_id"]: k for k in client.get("/knowledge-bases").json()["knowledge_bases"]}
    assert listed[kb.kb_id]["status"] == "failed"
    assert listed[kb.kb_id]["error"] == INTERRUPTED_ERROR
    assert listed[kb.kb_id]["job"] is None

    body = client.get(f"/knowledge-bases/{kb.kb_id}").json()
    assert body["status"] == "failed" and body["error"] == INTERRUPTED_ERROR

    # Reindex is the advertised way out, and the live job keeps "ingesting" honest.
    body = client.post(f"/knowledge-bases/{kb.kb_id}/reindex", json={"enrich": False}).json()
    assert body["job"]["kind"] == "kb_ingest"
    assert _poll_job(client, body["job"]["job_id"])["status"] == "succeeded"
    body = client.get(f"/knowledge-bases/{kb.kb_id}").json()
    assert body["status"] == "ready" and body["error"] is None


def test_upload_with_enrichment_uses_selected_provider(
    client: TestClient, corpus_zip: bytes, factory_calls: list[tuple[str | None, str | None]]
) -> None:
    body = _upload(client, corpus_zip, enrich="true", provider="nemotron")
    done = _poll_job(client, body["job"]["job_id"])
    assert done["status"] == "succeeded", done
    assert factory_calls == [("nemotron", None)]
    kb = client.get(f"/knowledge-bases/{body['kb_id']}").json()
    assert kb["llm_enriched"] is True and kb["provider_used"] == "mock"
    assert kb["stats"]["by_type"].get("DataArtifact", 0) >= 2


def test_upload_rejects_bad_provider_and_bad_zip(client: TestClient) -> None:
    response = client.post(
        "/knowledge-bases",
        files={"file": ("x.zip", b"not a zip", "application/zip")},
        data={"provider": "nope"},
    )
    assert response.status_code == 422
    response = client.post(
        "/knowledge-bases", files={"file": ("x.zip", b"not a zip", "application/zip")}
    )
    assert response.status_code == 400
    assert "not a valid zip" in response.json()["detail"]
    assert client.get("/knowledge-bases").json()["knowledge_bases"] == []


def test_query_routes(client: TestClient, corpus_zip: bytes) -> None:
    body = _upload(client, corpus_zip, enrich="false")
    kb_id = body["kb_id"]
    assert _poll_job(client, body["job"]["job_id"])["status"] == "succeeded"

    retrieved = client.post(
        f"/knowledge-bases/{kb_id}/retrieve",
        json={"prompt": "how does dispatch compensate provisioning", "budget": 1500},
    )
    assert retrieved.status_code == 200, retrieved.text
    packet = retrieved.json()["packet"]
    assert packet["rendered"] and packet["sections"] and packet["files"]

    impact = client.get(
        f"/knowledge-bases/{kb_id}/impact",
        params=[("seed", "mod:src/orders/activities.py"), ("max_hops", "1")],
    ).json()
    assert impact["rows"][0]["hops"] == 0
    assert any(r["node_id"] == "mod:src/orders/workflow.py" for r in impact["rows"])

    search = client.get(f"/knowledge-bases/{kb_id}/search", params={"q": "release_provisioning"})
    assert search.status_code == 200 and search.json()["hits"]

    files = client.get(f"/knowledge-bases/{kb_id}/files").json()
    assert "src/orders/workflow.py" in files["files"]
    one = client.get(
        f"/knowledge-bases/{kb_id}/files", params={"path": "src/orders/workflow.py"}
    ).json()
    assert "class OrderWorkflow" in one["text"]
    assert client.get(
        f"/knowledge-bases/{kb_id}/files", params={"path": "../../etc/passwd"}
    ).status_code == 404

    summary = client.get(f"/knowledge-bases/{kb_id}/graph/summary").json()["summary"]
    assert summary["nodes"] > 0 and summary["top_nodes"]

    # reindex is a job too; a second reindex while one runs is refused
    re1 = client.post(f"/knowledge-bases/{kb_id}/reindex", json={"enrich": False})
    assert re1.status_code == 202
    assert re1.json()["job"]["kind"] == "kb_ingest"
    assert _poll_job(client, re1.json()["job"]["job_id"])["status"] == "succeeded"

    deleted = client.delete(f"/knowledge-bases/{kb_id}")
    assert deleted.status_code == 200
    assert client.get(f"/knowledge-bases/{kb_id}").status_code == 404


def test_retrieve_before_ready_is_400_and_missing_is_404(
    client: TestClient, corpus_zip: bytes
) -> None:
    assert client.get("/knowledge-bases/nope").status_code == 404
    assert client.get("/knowledge-bases/../etc").status_code == 404
    body = _upload(client, corpus_zip, enrich="false")
    # The job may already be running/done; retrieving on a KB with no graph is a
    # clean 400 rather than a 500 — assert on the KB we deleted the graph of.
    _poll_job(client, body["job"]["job_id"])
    response = client.post(
        f"/knowledge-bases/{body['kb_id']}/retrieve", json={"prompt": ""}
    )
    assert response.status_code == 422  # min_length on prompt


def test_owner_isolation_when_not_shared(
    client: TestClient, corpus_zip: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workflow_compiler.config import get_settings

    body = _upload(client, corpus_zip, enrich="false")
    _poll_job(client, body["job"]["job_id"])
    monkeypatch.setattr(get_settings(), "projects_shared", False)
    try:
        # a second account cannot see the first account's knowledge base
        client.post("/auth/logout")
        client.post(
            "/auth/register",
            json={"email": "other@example.com", "password": "password123", "display_name": "O"},
        )
        assert client.get("/knowledge-bases").json()["knowledge_bases"] == []
        assert client.get(f"/knowledge-bases/{body['kb_id']}").status_code == 404
    finally:
        monkeypatch.setattr(get_settings(), "projects_shared", True)

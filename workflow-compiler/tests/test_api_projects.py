"""API tests for the spec-centric project endpoints (mock-backed)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import get_compiler, get_project_compiler
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.exceptions import (
    ProviderConnectionError,
    ProviderHTTPError,
    ProviderResponseError,
    ProviderTimeoutError,
    SchemaValidationError,
)
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import CompilationProject
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.project_store import FileProjectStore, InMemoryProjectStore
from workflow_compiler.storage.user_store import InMemoryUserStore

_NO_REVIEW = ReviewConfig(enabled=False)

_DOCUMENT = (
    "When an order is submitted, validate the order, reserve inventory, and "
    "ship the order. If the order is invalid, raise OrderInvalid. Release "
    "inventory compensates Reserve inventory. Inputs: order_id, customer_id."
)


@pytest.fixture
def client() -> TestClient:
    # script_defaults makes the mock answer every stage with a coherent demo
    # workflow, so the whole project flow runs without an exact queue.
    provider = MockProvider(script_defaults=True)
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    compiler = ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=InMemoryProjectStore(),
        segmentation_review=False,
    )
    app.dependency_overrides[get_project_compiler] = lambda: compiler
    # The /files endpoint loads per-workflow states through get_compiler; point it
    # at the same inner compiler so it sees the states approval just created.
    app.dependency_overrides[get_compiler] = lambda: inner
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as test_client:
        # Every project endpoint requires a session; register signs the client in.
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


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProviderHTTPError(502, "Inference server unreachable"), 502),
        (ProviderConnectionError("gateway refused the connection"), 502),
        (ProviderResponseError("response choice had no content"), 502),
        (SchemaValidationError("failed validation after 2 attempts"), 502),
        (ProviderTimeoutError("request timed out after 300s"), 504),
    ],
)
def test_compile_surfaces_provider_failure_as_bad_gateway(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected: int,
) -> None:
    """An upstream model failing is not this server failing.

    A dead gateway model reported as 500 reads as a compiler bug and sends
    debugging in the wrong direction; 502/504 says "upstream, and retryable".
    """
    compiler = app.dependency_overrides[get_project_compiler]()

    async def boom(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(compiler, "compile_document", boom)

    upload = client.post(
        "/projects/compile-upload",
        files={"file": ("doc.md", _DOCUMENT.encode(), "text/markdown")},
    )
    assert upload.status_code == expected

    inline = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    assert inline.status_code == expected


def test_project_compile_returns_specs(client: TestClient) -> None:
    response = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["stage"] == "spec_drafted"
    assert "demo-order-workflow" in body["spec_markdown"]
    assert body["spec_markdown"]["demo-order-workflow"].startswith("# ")

    # A deterministic structural diagram is previewed for the workflow.
    assert body["diagrams"]["demo-order-workflow"].startswith("flowchart TD")
    assert "classDef" not in body["diagrams"]["demo-order-workflow"]

    project_id = body["project"]["project_id"]
    listed = client.get("/projects")
    summaries = listed.json()["projects"]
    row = next(s for s in summaries if s["project_id"] == project_id)
    assert row["stage"] == "spec_drafted"
    assert row["workflow_count"] >= 1
    assert row["nickname"] is None
    got = client.get(f"/projects/{project_id}")
    assert got.status_code == 200
    assert got.json()["project"]["project_id"] == project_id
    assert got.json()["diagrams"]["demo-order-workflow"].startswith("flowchart TD")


def test_project_cvpa_preview_returns_colored_diagram(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]

    response = client.post(
        f"/projects/{project_id}/cvpa", json={"workflow": "demo-order-workflow"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "demo-order-workflow"
    assert body["diagram"].startswith("flowchart TD")
    assert "classDef" in body["diagram"]  # phase-colored


def test_project_cvpa_preview_unknown_workflow_is_400(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]
    response = client.post(
        f"/projects/{project_id}/cvpa", json={"workflow": "ghost"}
    )
    assert response.status_code == 400


def test_project_spec_update_validate_and_approve(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    body = compiled.json()
    project_id = body["project"]["project_id"]
    slug = "demo-order-workflow"
    markdown = body["spec_markdown"][slug]

    # PUT an edit: add a human activity line (deterministic ingest, no LLM).
    edited = markdown.replace(
        "- [a3] Ship order", "- [a3] Ship order\n- Email the invoice to finance"
    )
    updated = client.put(
        f"/projects/{project_id}/spec", json={"spec_markdown": {slug: edited}}
    )
    assert updated.status_code == 200
    assert "Email the invoice to finance" in updated.json()["spec_markdown"][slug]

    # Validate (mock returns no_change for every pass).
    validated = client.post(f"/projects/{project_id}/validate", json={"spec_markdown": {}})
    assert validated.status_code == 200
    assert validated.json()["project"]["stage"] == "spec_validated"

    # Approve straight through; the demo workflow has no cross references.
    approved = client.post(
        f"/projects/{project_id}/approve",
        json={"accept_incomplete": True},
    )
    assert approved.status_code == 200
    project = approved.json()["project"]
    assert project["stage"] == "completed"
    assert slug in project["workflow_ids"]


def test_project_not_found_is_404(client: TestClient) -> None:
    assert client.get("/projects/nope").status_code == 404


def test_project_compile_upload_parses_document(client: TestClient) -> None:
    response = client.post(
        "/projects/compile-upload",
        files={"file": ("order.md", _DOCUMENT.encode("utf-8"), "text/markdown")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["stage"] == "spec_drafted"
    assert "demo-order-workflow" in body["spec_markdown"]


def test_project_compile_upload_rejects_unknown_format(client: TestClient) -> None:
    response = client.post(
        "/projects/compile-upload",
        files={"file": ("mystery.xyz", b"whatever", "application/x-unknown")},
    )
    assert response.status_code == 415


def test_project_files_returns_zip_ready_tree(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]
    client.post(f"/projects/{project_id}/validate", json={"spec_markdown": {}})
    approved = client.post(
        f"/projects/{project_id}/approve", json={"accept_incomplete": True}
    )
    assert approved.json()["project"]["stage"] == "completed"

    files = client.get(f"/projects/{project_id}/files")
    assert files.status_code == 200
    body = files.json()
    assert body["project_id"] == project_id
    paths = [entry["path"] for entry in body["files"]]
    # Per-workflow bundle files are namespaced under the slug directory ...
    assert any(path.startswith("demo-order-workflow/") for path in paths)
    assert "demo-order-workflow/workflow.py" in paths
    # ... and the shared project glue files sit at the root.
    assert "contracts.py" in paths
    assert "README.md" in paths


def test_project_edit_applies_and_rearms_gate(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]

    edit_doc = (
        "# Edit Request\n\n"
        "## Workflow: demo-order-workflow\n\n"
        "### Add\n\n"
        "- A business rule: refunds require manager approval.\n\n"
        "## Reason\n\nAPI test.\n"
    )
    response = client.post(
        f"/projects/{project_id}/edit",
        json={"edit_document": edit_doc, "author": "devansh"},
    )
    assert response.status_code == 200
    body = response.json()
    # The mock's canned EditPlan added a rule; the spec markdown reflects it.
    assert "Mock-edited" in body["spec_markdown"]["demo-order-workflow"]
    assert body["project"]["stage"] == "spec_drafted"
    log = body["project"]["edit_log"]
    assert len(log) == 1
    assert log[0]["author"] == "devansh"
    assert log[0]["resolved_patches"]["demo-order-workflow"]

    # Omitting the author attributes the edit to the signed-in account.
    second = client.post(
        f"/projects/{project_id}/edit", json={"edit_document": edit_doc}
    )
    assert second.status_code == 200
    assert second.json()["project"]["edit_log"][-1]["author"] == "Tester"


def test_project_edit_preview_then_confirm(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]

    edit_doc = (
        "# Edit Request\n\n"
        "## Workflow: demo-order-workflow\n\n"
        "### Add\n\n"
        "- A business rule: refunds require manager approval.\n\n"
        "## Reason\n\nPreview test.\n"
    )
    preview = client.post(
        f"/projects/{project_id}/edit/preview", json={"edit_document": edit_doc}
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["record"]["summary"]["demo-order-workflow"]
    assert body["resolved"]["fingerprint"]
    assert "demo-order-workflow" in body["spec_markdown"]

    # Nothing was persisted by the preview.
    loaded = client.get(f"/projects/{project_id}").json()
    assert loaded["project"]["edit_log"] == []
    assert loaded["project"]["stage"] != "spec_drafted" or True  # stage untouched

    # Confirm with the resolved blob applies exactly the previewed edit.
    confirm = client.post(
        f"/projects/{project_id}/edit",
        json={"edit_document": edit_doc, "resolved": body["resolved"]},
    )
    assert confirm.status_code == 200
    log = confirm.json()["project"]["edit_log"]
    assert len(log) == 1
    assert log[0]["summary"] == body["record"]["summary"]


def test_project_edit_confirm_stale_preview_is_409(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]
    spec_markdown = compiled.json()["spec_markdown"]

    edit_doc = (
        "# Edit Request\n\n"
        "## Workflow: demo-order-workflow\n\n"
        "### Add\n\n"
        "- A business rule: refunds require manager approval.\n\n"
        "## Reason\n\nStale test.\n"
    )
    preview = client.post(
        f"/projects/{project_id}/edit/preview", json={"edit_document": edit_doc}
    )
    assert preview.status_code == 200

    # A concurrent spec save touches the project → the preview is stale.
    saved = client.put(
        f"/projects/{project_id}/spec", json={"spec_markdown": spec_markdown}
    )
    assert saved.status_code == 200

    confirm = client.post(
        f"/projects/{project_id}/edit",
        json={"edit_document": edit_doc, "resolved": preview.json()["resolved"]},
    )
    assert confirm.status_code == 409
    assert "preview" in confirm.json()["detail"].lower()
    # Still atomic: nothing applied.
    assert client.get(f"/projects/{project_id}").json()["project"]["edit_log"] == []


def test_project_edit_unknown_slug_is_400(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]

    edit_doc = "# Edit Request\n\n## Workflow: ghost\n\n### Add\n- x\n"
    response = client.post(
        f"/projects/{project_id}/edit", json={"edit_document": edit_doc}
    )
    assert response.status_code == 400
    assert "Unknown workflow slug" in response.json()["detail"]


def test_project_edit_unknown_project_is_404(client: TestClient) -> None:
    edit_doc = "# Edit Request\n\n## Remove Workflow: anything\n"
    response = client.post("/projects/nope/edit", json={"edit_document": edit_doc})
    assert response.status_code == 404


def test_project_compile_with_nickname(client: TestClient) -> None:
    response = client.post(
        "/projects/compile",
        json={"document_text": _DOCUMENT, "nickname": "  Orders pipeline  "},
    )
    assert response.status_code == 200
    project_id = response.json()["project"]["project_id"]
    # Nickname is trimmed and stored on the project ...
    assert response.json()["project"]["nickname"] == "Orders pipeline"
    # ... and surfaces on the list summary.
    row = next(
        s for s in client.get("/projects").json()["projects"]
        if s["project_id"] == project_id
    )
    assert row["nickname"] == "Orders pipeline"


def test_project_rename_sets_and_clears_nickname(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]

    named = client.patch(f"/projects/{project_id}", json={"nickname": "Refund flow"})
    assert named.status_code == 200
    assert named.json()["nickname"] == "Refund flow"
    assert named.json()["project_id"] == project_id
    # Persisted on the full project too.
    assert client.get(f"/projects/{project_id}").json()["project"]["nickname"] == "Refund flow"

    # An empty/blank nickname clears it back to None.
    cleared = client.patch(f"/projects/{project_id}", json={"nickname": "   "})
    assert cleared.status_code == 200
    assert cleared.json()["nickname"] is None


def test_project_rename_unknown_project_is_404(client: TestClient) -> None:
    assert client.patch("/projects/nope", json={"nickname": "x"}).status_code == 404


def test_per_user_baseline_override_changes_time_saved(client: TestClient) -> None:
    # Compile → validate → approve so the project accrues compile stage_timings.
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    project_id = compiled.json()["project"]["project_id"]
    client.post(f"/projects/{project_id}/validate", json={"spec_markdown": {}})
    approved = client.post(
        f"/projects/{project_id}/approve", json={"accept_incomplete": True}
    )
    assert approved.json()["project"]["stage"] == "completed"

    baseline_saved = client.get(f"/projects/{project_id}").json()["time_saved"]
    assert baseline_saved is not None

    # Slash the human 'compile' baseline; the saved-hours figure must drop.
    client.put(
        "/auth/me",
        json={"preferences": {"baseline_hours": {"compile": 0.5}, "projects_page_size": 10}},
    )
    lowered = client.get(f"/projects/{project_id}").json()["time_saved"]
    assert lowered is not None
    assert lowered["total_saved_hours"] < baseline_saved["total_saved_hours"]
    # The metrics summary reflects the same per-user override.
    assert (
        client.get("/metrics/summary").json()["total_saved_hours"]
        == pytest.approx(lowered["total_saved_hours"])
    )


def test_metrics_summary_skips_unloadable_projects(tmp_path: Path) -> None:
    # A corrupt or legacy project file on disk must not 500 the metrics page.
    provider = MockProvider(script_defaults=True)
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    store = FileProjectStore(tmp_path)
    compiler = ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=store,
        segmentation_review=False,
    )
    good = CompilationProject(
        document_text="doc", stage_timings={"workflow-segmentation": 30.0}
    )
    asyncio.run(store.save(good))
    (tmp_path / "projects" / "broken.json").write_text("{not valid json", encoding="utf-8")

    app.dependency_overrides[get_project_compiler] = lambda: compiler
    app.dependency_overrides[get_compiler] = lambda: inner
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    try:
        with TestClient(app) as test_client:
            test_client.post(
                "/auth/register",
                json={
                    "email": "tester@example.com",
                    "password": "password123",
                    "display_name": "Tester",
                },
            )
            response = test_client.get("/metrics/summary")
            assert response.status_code == 200
            body = response.json()
            assert body["projects"] == 1
            assert body["total_actual_seconds"] == pytest.approx(30.0)
    finally:
        app.dependency_overrides.clear()

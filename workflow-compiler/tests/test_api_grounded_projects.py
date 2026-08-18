"""HTTP + CLI tests for knowledge-graph-grounded projects (Phase 3).

``POST /projects/compile-upload`` / ``/projects/compile`` with ``kb_id`` /
``change_request_id``, ``POST /change-requests/{id}/send-to-workflow``,
``changes.md`` through ``PUT /projects/{id}/spec`` and the validate job, and
``workflow-compiler compile --kb / --change-request``.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rich.console import Console
from typer.testing import CliRunner

from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import (
    get_change_service,
    get_compiler,
    get_compiler_selector,
    get_kg_service,
    get_project_compiler,
)
from workflow_compiler.change.service import ChangeRequestService
from workflow_compiler.cli import cr as cr_cli
from workflow_compiler.cli import kb as kb_cli
from workflow_compiler.cli import main as main_cli
from workflow_compiler.cli.main import app as cli_app
from workflow_compiler.compiler import ReviewConfig, WorkflowCompiler
from workflow_compiler.config import get_settings
from workflow_compiler.kg import InMemoryKnowledgeBaseStore, KgService
from workflow_compiler.kg.ingest import zip_folder
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import CHANGES_SLUG
from workflow_compiler.project_compiler import ProjectCompiler
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.change_store import InMemoryChangeRequestStore
from workflow_compiler.storage.project_store import InMemoryProjectStore
from workflow_compiler.storage.user_store import InMemoryUserStore

from .test_change_spec import TDD_TEXT
from .test_change_wizard import BCR_TEXT, ScriptedAnalyst
from .test_kg_service import build_corpus

FIXTURES = Path(__file__).parent / "fixtures" / "change_artifacts"
_NO_REVIEW = ReviewConfig(enabled=False)


@pytest.fixture
def analyst() -> ScriptedAnalyst:
    return ScriptedAnalyst()


@pytest.fixture
def client(
    tmp_path: Path, analyst: ScriptedAnalyst
) -> Iterator[tuple[TestClient, str, ChangeRequestService]]:
    kg = KgService(InMemoryKnowledgeBaseStore(tmp_path / "state"), lambda n, m: analyst)
    changes = ChangeRequestService(InMemoryChangeRequestStore(), kg, lambda n, m: analyst)
    provider = MockProvider(script_defaults=True)
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    compiler = ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=InMemoryProjectStore(),
        segmentation_review=False,
        kg_service=kg,
    )
    app.dependency_overrides[get_kg_service] = lambda: kg
    app.dependency_overrides[get_change_service] = lambda: changes
    app.dependency_overrides[get_project_compiler] = lambda: compiler
    # send-to-workflow always names a provider (cloud Nemotron by default): route
    # every explicit selection to the same mock compiler.
    app.dependency_overrides[get_compiler_selector] = lambda: (lambda p, m: compiler)
    app.dependency_overrides[get_compiler] = lambda: inner
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as test_client:
        test_client.post(
            "/auth/register",
            json={"email": "g@example.com", "password": "password123", "display_name": "G"},
        )
        upload = test_client.post(
            "/knowledge-bases",
            files={"file": ("kb.zip", zip_folder(build_corpus(tmp_path / "kb_mini")),
                            "application/zip")},
            data={"name": "Mini KB", "enrich": "false"},
        )
        assert upload.status_code == 202, upload.text
        _poll_job(test_client, upload.json()["job"]["job_id"])
        yield test_client, upload.json()["kb_id"], changes
    app.dependency_overrides.clear()


def _poll_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _create_cr(client: TestClient, kb_id: str) -> str:
    response = client.post(
        "/change-requests",
        files={"file": ("BCR-001.md", BCR_TEXT.encode("utf-8"), "text/markdown")},
        data={"kb_id": kb_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["change_request"]["cr_id"]


async def _approve_tdd(changes: ChangeRequestService, cr_id: str) -> None:
    """Short-cut the wizard: install the fixture TDD as approved (the API allows edits)."""
    cr = await changes.get(cr_id)
    cr.artifacts.tdd.markdown = (FIXTURES / "TDD-ORD-002.md").read_text(encoding="utf-8")
    cr.artifacts.tdd.status = "approved"
    cr.artifacts.impact.markdown = (FIXTURES / "BCR-001-impact-analysis.md").read_text(
        encoding="utf-8"
    )
    cr.artifacts.impact.status = "approved"
    await changes._save(cr)


# ------------------------------------------------------------------ upload with kb_id


def test_upload_with_kb_id_grounds_and_adds_changes_md(
    client: tuple[TestClient, str, ChangeRequestService],
) -> None:
    c, kb_id, _ = client
    response = c.post(
        "/projects/compile-upload",
        files={"file": ("TDD.md", TDD_TEXT.encode("utf-8"), "text/markdown")},
        data={"kb_id": kb_id, "nickname": "grounded"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    project = body["project"]
    assert project["kb_id"] == kb_id
    assert project["change_request_id"] is None
    assert project["grounding"]["kb_name"] == "Mini KB"
    assert project["grounding"]["sources"]
    assert project["change_spec"]["components"]
    assert CHANGES_SLUG in body["spec_markdown"]
    changes_md = body["spec_markdown"][CHANGES_SLUG]
    assert changes_md.startswith("# Change Spec") and "- knowledge base: Mini KB" in changes_md
    assert body["spec_markdown"][CHANGES_SLUG] not in body["diagrams"]

    # PUT /spec accepts changes.md (deterministic fold-in)
    pid = project["project_id"]
    edited = changes_md.replace(
        "Fan out provisioning and dispatch per shipment group.",
        "Fan out provisioning and dispatch per shipment group. Emit a per-group event.",
    )
    assert edited != changes_md
    saved = c.put(f"/projects/{pid}/spec", json={"spec_markdown": {CHANGES_SLUG: edited}})
    assert saved.status_code == 200, saved.text
    workflow = next(
        comp for comp in saved.json()["project"]["change_spec"]["components"]
        if comp["name"] == "src/orders/workflow.py"
    )
    assert "Emit a per-group event." in workflow["proposed"]
    assert workflow["provenance"] == "human_provided"

    # the validate job carries changes.md and reports its findings under __changes__
    blanked = saved.json()["spec_markdown"][CHANGES_SLUG].replace(
        "#### Proposed\nAccept a shipment group id and dispatch that group only.",
        "#### Proposed\n<!-- none -->",
    )
    started = c.post(
        f"/projects/{pid}/jobs",
        json={"kind": "validate", "spec_markdown": {CHANGES_SLUG: blanked}},
    )
    assert started.status_code == 202, started.text
    done = _poll_job(c, started.json()["job_id"])
    assert done["status"] == "succeeded", done
    findings = done["project"]["project"]["validation_findings"][CHANGES_SLUG]
    assert any(f["severity"] == "blocking" and "dispatch_order" in f["message"] for f in findings)
    # GET returns the same file set
    got = c.get(f"/projects/{pid}").json()
    assert CHANGES_SLUG in got["spec_markdown"]

    # ungrounded compiles are unchanged
    plain = c.post("/projects/compile", json={"document_text": TDD_TEXT})
    assert plain.status_code == 200
    assert plain.json()["project"]["kb_id"] is None
    assert CHANGES_SLUG not in plain.json()["spec_markdown"]


def test_upload_kb_errors(client: tuple[TestClient, str, ChangeRequestService]) -> None:
    c, kb_id, _ = client
    missing = c.post("/projects/compile", json={"document_text": TDD_TEXT, "kb_id": "nope"})
    assert missing.status_code == 404
    bad_cr = c.post(
        "/projects/compile", json={"document_text": TDD_TEXT, "change_request_id": "nope"}
    )
    assert bad_cr.status_code == 404
    cr_id = _create_cr(c, kb_id)
    # a CR implies its own KB; a different explicit kb_id is rejected
    other = c.post(
        "/knowledge-bases",
        files={"file": ("kb.zip", b"", "application/zip")},
        data={"name": "x", "enrich": "false"},
    )
    assert other.status_code in (400, 422)  # empty zip — just proving the check below
    mismatch = c.post(
        "/projects/compile",
        json={"document_text": TDD_TEXT, "kb_id": "another-kb", "change_request_id": cr_id},
    )
    assert mismatch.status_code == 422


# ------------------------------------------------------------------ send-to-workflow


def test_send_to_workflow_links_ids(
    client: tuple[TestClient, str, ChangeRequestService],
) -> None:
    c, kb_id, changes = client
    cr_id = _create_cr(c, kb_id)
    # not approved yet → 409
    refused = c.post(f"/change-requests/{cr_id}/send-to-workflow", json={})
    assert refused.status_code == 409, refused.text
    # run on the app's event loop (the in-memory store's locks are bound to it)
    c.portal.call(_approve_tdd, changes, cr_id)

    response = c.post(f"/change-requests/{cr_id}/send-to-workflow", json={})
    assert response.status_code == 201, response.text
    body = response.json()
    project = body["project"]
    assert project["kb_id"] == kb_id
    assert project["change_request_id"] == cr_id
    assert project["grounding"]["kb_name"] == "Mini KB"
    assert project["grounding"]["change_request_title"]
    assert project["grounding"]["requirement_ids"] == ["BCR-01-01", "BCR-01-02", "BCR-01-03"]
    assert project["nickname"].startswith("TDD-ORD-002 — ") or project["nickname"]
    assert CHANGES_SLUG in body["spec_markdown"]
    assert "- change request:" in body["spec_markdown"][CHANGES_SLUG]
    # the change request now points at the project
    cr = c.get(f"/change-requests/{cr_id}").json()["change_request"]
    assert cr["project_ids"] == [project["project_id"]]
    # unknown provider → 422
    bad = c.post(f"/change-requests/{cr_id}/send-to-workflow", json={"provider": "nope"})
    assert bad.status_code == 422


# ------------------------------------------------------------------ CLI


runner = CliRunner()


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "state"
    monkeypatch.setattr(get_settings(), "state_store_path", str(root))
    monkeypatch.setattr(kb_cli, "console", Console(width=300))
    monkeypatch.setattr(cr_cli, "console", Console(width=300))
    monkeypatch.setattr(main_cli, "console", Console(width=300))
    return root


def test_cli_compile_with_kb_writes_changes_md(tmp_path: Path, state_root: Path) -> None:
    corpus = build_corpus(tmp_path / "kb_mini")
    result = runner.invoke(
        cli_app, ["kb", "init", str(corpus), "--no-enrich", "--id", "mini"]
    )
    assert result.exit_code == 0, result.output
    tdd = tmp_path / "TDD.md"
    tdd.write_text(TDD_TEXT, encoding="utf-8")
    spec_dir = tmp_path / "specs"
    result = runner.invoke(
        cli_app,
        ["compile", str(tdd), "--provider", "mock", "--no-review", "--spec-dir",
         str(spec_dir), "--kb", "mini"],
    )
    assert result.exit_code == 0, result.output
    assert "Grounding" in result.output and "changes.md" in result.output
    changes = spec_dir / "changes.md"
    assert changes.is_file()
    text = changes.read_text(encoding="utf-8")
    assert text.startswith("# Change Spec") and "### src/orders/workflow.py" in text
    project_id = next(
        line for line in result.output.splitlines() if "project_id" in line
    ).split(":")[-1].strip()
    # validate reads changes.md back and reports its findings
    changes.write_text(
        text.replace(
            "#### Proposed\nAccept a shipment group id and dispatch that group only.",
            "#### Proposed\n<!-- none -->",
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        cli_app, ["validate", project_id, "--provider", "mock", "--spec-dir", str(spec_dir)]
    )
    assert result.exit_code == 1, result.output  # blocking finding
    assert "__changes__" in result.output and "dispatch_order" in result.output

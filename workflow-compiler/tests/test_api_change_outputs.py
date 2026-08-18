"""HTTP + CLI tests for the post-approval change outputs (Phase 4).

``POST /projects/{id}/jobs`` (approve) chains a ``change_outputs`` job for a
grounded project; ``GET /projects/{id}/change-outputs``, ``POST
…/change-outputs/regenerate`` (per stage, resumable), ``GET
…/change-outputs/export.zip``; ``workflow-compiler change-outputs``.
"""
# ruff: noqa: E501  (long route / assertion lines)

from __future__ import annotations

import io
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
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
from workflow_compiler.cli import main as main_cli
from workflow_compiler.cli.main import app as cli_app
from workflow_compiler.compiler import ReviewConfig, WorkflowCompiler
from workflow_compiler.kg import InMemoryKnowledgeBaseStore, KgService
from workflow_compiler.kg.ingest import zip_folder
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.project_compiler import ProjectCompiler
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.change_store import InMemoryChangeRequestStore
from workflow_compiler.storage.project_store import InMemoryProjectStore
from workflow_compiler.storage.user_store import InMemoryUserStore

from .test_change_outputs import NEW_TYPES, _completions, _spec, _write_corpus
from .test_change_spec import TDD_TEXT

_NO_REVIEW = ReviewConfig(enabled=False)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, str, ProjectCompiler, MockProvider]]:
    kg = KgService(InMemoryKnowledgeBaseStore(tmp_path / "state"))
    changes = ChangeRequestService(InMemoryChangeRequestStore(), kg, lambda n, m: MockProvider())
    provider = MockProvider(script_defaults=True, completions=_completions())
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
    app.dependency_overrides[get_compiler_selector] = lambda: (lambda p, m: compiler)
    app.dependency_overrides[get_compiler] = lambda: inner
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as test_client:
        test_client.post(
            "/auth/register",
            json={"email": "o@example.com", "password": "password123", "display_name": "O"},
        )
        corpus = _write_corpus(tmp_path / "corpus")
        upload = test_client.post(
            "/knowledge-bases",
            files={"file": ("kb.zip", zip_folder(corpus), "application/zip")},
            data={"name": "Orders KB", "enrich": "false"},
        )
        assert upload.status_code == 202, upload.text
        _poll_job(test_client, upload.json()["job"]["job_id"])
        yield test_client, upload.json()["kb_id"], compiler, provider
    app.dependency_overrides.clear()


def _poll_job(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _wait_for_kind(client: TestClient, project_id: str, kind: str, timeout: float = 60.0) -> dict:
    """The newest job of ``kind`` for the project once it is no longer running."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = [j for j in client.get(f"/jobs?project_id={project_id}").json() if j["kind"] == kind]
        if jobs and jobs[0]["status"] != "running":
            return jobs[0]
        time.sleep(0.05)
    raise AssertionError(f"no finished {kind} job")


async def _install_spec(
    compiler: ProjectCompiler, project_id: str, spec_dir: Path | None = None
) -> None:
    """Install the fixture change spec (and, for the CLI, rewrite the spec files)."""
    project = await compiler.load_project(project_id)
    project.change_spec = _spec()
    assert project.grounding is not None
    project.grounding.change_request_title = "BCR-001 — Partial shipments"
    await compiler.save_project(project)
    if spec_dir is not None:
        compiler.write_spec_files(project, spec_dir)


def test_approve_job_chains_change_outputs_and_routes(
    client: tuple[TestClient, str, ProjectCompiler, MockProvider],
) -> None:
    c, kb_id, compiler, _provider = client
    # before anything: 404 for a missing project
    assert c.get("/projects/nope/change-outputs").status_code == 404

    response = c.post(
        "/projects/compile-upload",
        files={"file": ("TDD.md", TDD_TEXT.encode("utf-8"), "text/markdown")},
        data={"kb_id": kb_id, "nickname": "grounded"},
    )
    assert response.status_code == 200, response.text
    pid = response.json()["project"]["project_id"]
    c.portal.call(_install_spec, compiler, pid)  # type: ignore[attr-defined]

    # nothing yet: available (grounded) but not generated; export is 404; regenerate 409
    got = c.get(f"/projects/{pid}/change-outputs").json()
    assert got["outputs"] is None and got["available"] is False  # no compiled workflow yet
    assert c.get(f"/projects/{pid}/change-outputs/export.zip").status_code == 404
    assert c.post(f"/projects/{pid}/change-outputs/regenerate", json={"stage": "all"}).status_code == 409

    # approve job → chained change_outputs job
    started = c.post(f"/projects/{pid}/jobs", json={"kind": "approve", "accept_incomplete": True})
    assert started.status_code == 202, started.text
    done = _poll_job(c, started.json()["job_id"])
    assert done["status"] == "succeeded", done
    assert done["project"]["project"]["stage"] == "completed"
    chained = _wait_for_kind(c, pid, "change_outputs")
    assert chained["status"] == "succeeded", chained
    assert chained["progress"]["total"] == 3 and chained["progress"]["done"] == 3

    got = c.get(f"/projects/{pid}/change-outputs").json()
    assert got["available"] is True and got["job"] is None
    outputs = got["outputs"]
    assert [s for s in ("diagrams", "code", "tests_doc") if outputs["stages"][s]["status"] == "done"] == [
        "diagrams", "code", "tests_doc",
    ]
    files = {f["path"]: f for f in outputs["code"]["files"]}
    assert files["existing_Codebase/shared/types.py"]["status"] == "modified"
    assert files["existing_Codebase/shared/types.py"]["updated"] == NEW_TYPES
    assert outputs["tests_doc"]["new_ids"] == ["TC-18"]
    assert any(d["name"] == "order-state-machine-partial-shipment.mmd" for d in outputs["diagrams"])
    # the project response carries them too
    project = c.get(f"/projects/{pid}").json()["project"]
    assert project["change_outputs"]["tests_doc"]["changed_ids"] == ["TC-06"]

    # export zip
    exported = c.get(f"/projects/{pid}/change-outputs/export.zip")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/zip")
    assert exported.headers["content-disposition"].endswith('-change-outputs.zip"')
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        names = archive.namelist()
        assert "src/shared/types.py" in names and "CHANGES.md" in names
        assert "docs/test-cases/TC-order-workflow.xlsx" in names

    # single rendered documents
    xlsx = c.get(f"/projects/{pid}/change-outputs/files/test-cases.xlsx")
    assert xlsx.status_code == 200 and xlsx.headers["content-disposition"].endswith('TC-order-workflow.xlsx"')
    from workflow_compiler.docs_export.xlsx_writer import read_test_case_rows

    assert read_test_case_rows(xlsx.content)[-1].tc_id == "TC-18"
    assert c.get(f"/projects/{pid}/change-outputs/files/test-plan-addendum.docx").status_code == 200
    assert c.get(f"/projects/{pid}/change-outputs/files/test-plan-addendum.md").text.startswith("# TP-ORD-001")
    assert "## 1. Order State Machine" in c.get(f"/projects/{pid}/change-outputs/files/system-flow-diagram.md").text
    assert c.get(f"/projects/{pid}/change-outputs/files/changes.patch").text.startswith("--- a/")
    assert c.get(f"/projects/{pid}/change-outputs/files/nope.txt").status_code == 404

    # regenerate one stage (resumable): the mock's diagrams again; other stages kept
    assert c.post(f"/projects/{pid}/change-outputs/regenerate", json={"stage": "bogus"}).status_code == 422
    again = c.post(f"/projects/{pid}/change-outputs/regenerate", json={"stage": "diagrams"})
    assert again.status_code == 202, again.text
    assert again.json()["kind"] == "change_outputs"
    running = c.get(f"/projects/{pid}/change-outputs").json()
    assert running["job"] is None or running["job"]["kind"] == "change_outputs"
    finished = _poll_job(c, again.json()["job_id"])
    assert finished["status"] == "succeeded", finished
    outputs = c.get(f"/projects/{pid}/change-outputs").json()["outputs"]
    assert outputs["stages"]["diagrams"]["status"] == "done"
    assert outputs["stages"]["code"]["status"] == "done"  # kept from the first run
    assert outputs["tests_doc"]["new_ids"] == ["TC-18"]

    # a second regenerate while one runs → 409 (one run per project)
    first = c.post(f"/projects/{pid}/change-outputs/regenerate", json={"stage": "tests_doc"})
    assert first.status_code == 202
    second = c.post(f"/projects/{pid}/change-outputs/regenerate", json={"stage": "tests_doc"})
    assert second.status_code == 409
    _poll_job(c, first.json()["job_id"])

    # ungrounded project: no chaining, regenerate refused
    plain = c.post("/projects/compile", json={"document_text": TDD_TEXT})
    plain_id = plain.json()["project"]["project_id"]
    assert c.get(f"/projects/{plain_id}/change-outputs").json()["available"] is False
    assert c.post(f"/projects/{plain_id}/change-outputs/regenerate", json={"stage": "all"}).status_code == 409


# ------------------------------------------------------------------ CLI


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "state"
    monkeypatch.setenv("WORKFLOW_COMPILER_STATE_STORE_PATH", str(root))
    from workflow_compiler.config import get_settings

    get_settings.cache_clear()
    yield root  # type: ignore[misc]
    get_settings.cache_clear()


def test_cli_change_outputs(tmp_path: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    corpus = _write_corpus(tmp_path / "corpus")
    kb_result = runner.invoke(
        cli_app, ["kb", "init", str(corpus), "--name", "orders", "--no-enrich", "--id", "orders"]
    )
    assert kb_result.exit_code == 0, kb_result.output
    kb_id = "orders"
    doc = tmp_path / "tdd.md"
    doc.write_text(TDD_TEXT, encoding="utf-8")
    spec_dir = tmp_path / "specs"
    provider = MockProvider(script_defaults=True, completions=_completions())
    monkeypatch.setattr(main_cli, "_build_provider", lambda *a, **k: provider)
    monkeypatch.setattr(main_cli, "_review_config", lambda enabled: _NO_REVIEW)
    compiled = runner.invoke(
        cli_app,
        ["compile", str(doc), "--spec-dir", str(spec_dir), "--kb", kb_id, "--provider", "mock",
         "--no-review"],
    )
    assert compiled.exit_code == 0, compiled.output
    pid = next(
        line for line in compiled.output.splitlines() if "project_id" in line
    ).split(":")[-1].strip()
    # install the fixture change spec so the rewrite set matches the corpus
    import asyncio

    compiler = main_cli._project_compiler(provider, review=False)
    asyncio.run(_install_spec(compiler, pid, spec_dir))
    out_dir = tmp_path / "generated"
    approved = runner.invoke(
        cli_app,
        ["approve-spec", pid, "--spec-dir", str(spec_dir), "--accept-incomplete", "--provider", "mock",
         "--out-dir", str(out_dir), "--change-outputs"],
    )
    assert approved.exit_code == 0, approved.output
    bundle = out_dir / pid / "change-outputs"
    assert (bundle / "src" / "shared" / "types.py").read_text(encoding="utf-8") == NEW_TYPES, approved.output
    assert (bundle / "CHANGES.md").is_file()
    assert (bundle / "docs" / "test-cases" / "TC-order-workflow.xlsx").is_file()
    # the standalone command re-runs one stage
    provider2 = MockProvider(script_defaults=True)
    monkeypatch.setattr(main_cli, "_build_provider", lambda *a, **k: provider2)
    rerun = runner.invoke(cli_app, ["change-outputs", pid, "--stage", "diagrams", "--out-dir", str(out_dir)])
    assert rerun.exit_code == 0, rerun.output
    assert "diagrams   done" in rerun.output

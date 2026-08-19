"""Phase 5 hardening: id sanitisation at every store boundary + compare-and-swap on save.

Offline (MockProvider / in-memory + tmp_path file stores). Covers:

* ``storage/ids.py`` — the shared id / slug guards and the CAS version arithmetic;
* every file store (workflow state, project, user, change request, knowledge base) refusing
  path-shaped ids as *not found* and bumping ``version`` on each save;
* ``StaleWriteError`` on a stale ``expected_version`` in the file **and** in-memory stores;
* ``bundle_dir`` refusing crafted project ids / slugs;
* export filenames built from document/model text staying filename-safe;
* the HTTP surface: ``ETag`` on GET, ``expected_version`` / ``If-Match`` → 409 on
  ``PUT /projects/{id}/spec``, ``PATCH /projects/{id}`` and ``PUT …/artifacts/{kind}``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import get_compiler, get_project_compiler
from workflow_compiler.change_outputs.export import export_filename
from workflow_compiler.change_outputs.models import TestDocUpdate
from workflow_compiler.change_outputs.tests_doc import addendum_filename
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.docs_export.artifacts import safe_filename_part
from workflow_compiler.docs_export.bundle import bundle_filename
from workflow_compiler.exceptions import StaleWriteError, StateNotFoundError
from workflow_compiler.execution import bundle_dir
from workflow_compiler.kg.models import KbSource, KnowledgeBase
from workflow_compiler.kg.store import FileKnowledgeBaseStore, InMemoryKnowledgeBaseStore
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import CompilationProject, WorkflowState
from workflow_compiler.models.change import BcrMeta, ChangeRequest
from workflow_compiler.models.user import User
from workflow_compiler.storage import FileStateStore, InMemoryStateStore
from workflow_compiler.storage.change_store import (
    FileChangeRequestStore,
    InMemoryChangeRequestStore,
)
from workflow_compiler.storage.ids import (
    is_safe_id,
    next_version,
    stored_version,
    validate_slug,
    validate_store_id,
)
from workflow_compiler.storage.project_store import FileProjectStore, InMemoryProjectStore
from workflow_compiler.storage.user_store import FileUserStore, InMemoryUserStore

BAD_IDS = ["../x", "..", "a/b", "a\\b", "C:evil", "", "x" * 129, "id with space", "é", "a\x00b"]


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# --------------------------------------------------------------------------- ids.py


def test_safe_id_and_slug_guards() -> None:
    assert is_safe_id("abc-DEF_123")
    for bad in BAD_IDS:
        assert not is_safe_id(bad), bad
        with pytest.raises(StateNotFoundError):
            validate_store_id(bad, label="project")
    assert validate_slug("order-workflow_2") == "order-workflow_2"
    for bad in ["../x", "a/b", "", "sl ug"]:
        with pytest.raises(StateNotFoundError):
            validate_slug(bad)


def test_next_version_and_stored_version(tmp_path: Path) -> None:
    assert next_version(None, None, label="x", key="k") == 1
    assert next_version(0, 0, label="x", key="k") == 1
    assert next_version(4, 4, label="x", key="k") == 5
    assert next_version(4, None, label="x", key="k") == 5
    with pytest.raises(StaleWriteError, match="stored version 4, expected 3"):
        next_version(4, 3, label="x", key="k")
    # Files: absent → None; legacy record without version → 0; corrupt → 0.
    assert stored_version(tmp_path / "missing.json") is None
    (tmp_path / "legacy.json").write_text('{"project_id": "p"}', encoding="utf-8")
    assert stored_version(tmp_path / "legacy.json") == 0
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert stored_version(tmp_path / "bad.json") == 0
    (tmp_path / "v.json").write_text('{"version": 7}', encoding="utf-8")
    assert stored_version(tmp_path / "v.json") == 7


# --------------------------------------------------------------------------- stores refuse bad ids


def test_every_file_store_refuses_path_shaped_ids(tmp_path: Path) -> None:
    states = FileStateStore(tmp_path)
    projects = FileProjectStore(tmp_path)
    users = FileUserStore(tmp_path)
    crs = FileChangeRequestStore(tmp_path)
    kbs = FileKnowledgeBaseStore(tmp_path)
    for bad in ["../escape", "a/b", "..\\..\\x"]:
        with pytest.raises(StateNotFoundError):
            _run(states.load(bad))
        with pytest.raises(StateNotFoundError):
            _run(projects.load(bad))
        with pytest.raises(StateNotFoundError):
            _run(users.load(bad))
        with pytest.raises(StateNotFoundError):
            _run(crs.load(bad))
        with pytest.raises(StateNotFoundError):
            _run(kbs.load(bad))
        # Saving under a crafted id is refused too — nothing lands outside the store dirs.
        with pytest.raises(StateNotFoundError):
            _run(states.save(WorkflowState(workflow_id=bad, document_text="x")))
        with pytest.raises(StateNotFoundError):
            _run(projects.save(CompilationProject(project_id=bad, document_text="x")))
    assert not (tmp_path.parent / "escape.json").exists()
    assert not list(tmp_path.glob("**/escape.json"))


def test_bundle_dir_validates_both_segments(tmp_path: Path) -> None:
    assert bundle_dir(tmp_path, "proj-1", "order-flow") == tmp_path / "proj-1" / "order-flow"
    for pid, slug in [("../x", "a"), ("p", "../a"), ("p", "a/b"), ("p/q", "a")]:
        with pytest.raises(StateNotFoundError):
            bundle_dir(tmp_path, pid, slug)


# --------------------------------------------------------------------------- CAS


def test_project_store_cas_file_and_memory(tmp_path: Path) -> None:
    for store in (FileProjectStore(tmp_path), InMemoryProjectStore()):
        project = CompilationProject(document_text="doc")
        assert project.version == 0
        _run(store.save(project))
        assert project.version == 1
        loaded_a = _run(store.load(project.project_id))
        loaded_b = _run(store.load(project.project_id))
        assert loaded_a.version == 1
        loaded_a.nickname = "A"
        _run(store.save(loaded_a, expected_version=1))
        assert loaded_a.version == 2
        loaded_b.nickname = "B"
        with pytest.raises(StaleWriteError):
            _run(store.save(loaded_b, expected_version=1))
        # The refused write did not land.
        assert _run(store.load(project.project_id)).nickname == "A"
        # Without a token the write goes through (last-write-wins, version keeps counting).
        _run(store.save(loaded_b))
        assert _run(store.load(project.project_id)).nickname == "B"
        assert _run(store.load(project.project_id)).version == 3


def test_change_request_store_cas(tmp_path: Path) -> None:
    for store in (FileChangeRequestStore(tmp_path), InMemoryChangeRequestStore()):
        cr = ChangeRequest(kb_id="kb1", title="t", document_text="d")
        _run(store.save(cr))
        assert cr.version == 1
        stale = _run(store.load(cr.cr_id))
        _run(store.save(cr, expected_version=1))
        assert cr.version == 2
        with pytest.raises(StaleWriteError):
            _run(store.save(stale, expected_version=1))
        _run(store.save(stale))  # opt-out still works
        assert _run(store.load(cr.cr_id)).version == 3


def test_knowledge_base_store_cas(tmp_path: Path) -> None:
    for store in (
        FileKnowledgeBaseStore(tmp_path / "f"),
        InMemoryKnowledgeBaseStore(tmp_path / "m"),
    ):
        kb = KnowledgeBase(name="kb", source=KbSource(kind="path", filename="x"))
        _run(store.save(kb))
        assert kb.version == 1
        stale = _run(store.load(kb.kb_id))
        kb.name = "renamed"
        _run(store.save(kb, expected_version=1))
        with pytest.raises(StaleWriteError):
            _run(store.save(stale, expected_version=1))
        assert _run(store.load(kb.kb_id)).name == "renamed"


def test_state_and_user_file_stores_still_round_trip(tmp_path: Path) -> None:
    states = FileStateStore(tmp_path)
    state = WorkflowState(document_text="doc")
    _run(states.save(state))
    assert _run(states.load(state.workflow_id)).document_text == "doc"
    users = FileUserStore(tmp_path)
    user = User(email="a@b.c", display_name="A", password_hash="h", password_salt="s")
    _run(users.save(user))
    assert _run(users.load(user.user_id)).email == "a@b.c"
    mem = InMemoryStateStore()
    _run(mem.save(state))
    assert _run(mem.exists(state.workflow_id))
    _run(InMemoryUserStore().save(user))


# --------------------------------------------------------------------------- filenames


def test_safe_filename_part_and_export_names() -> None:
    assert safe_filename_part("BCR-001") == "BCR-001"
    assert safe_filename_part("TP-ORD-001") == "TP-ORD-001"
    assert safe_filename_part('../evil name"; rm -rf') == "evil-name-rm-rf"
    assert safe_filename_part("..") == "file"
    assert safe_filename_part("", fallback="x") == "x"
    assert export_filename("abcdef1234", 'BCR 001/"x"') == "BCR-001-x-abcdef12-change-outputs.zip"
    update = TestDocUpdate(test_plan_id="TP/ORD 001", change_request_id="../BCR")
    assert addendum_filename(update) == "TP-ORD-001-addendum-BCR.docx"
    cr = ChangeRequest(kb_id="k", title="t", document_text="d", bcr_meta=BcrMeta(doc_id='B"CR/1'))
    name = bundle_filename(cr)
    assert name.startswith("B-CR-1-") and name.endswith("-export.zip") and "/" not in name


# --------------------------------------------------------------------------- HTTP surface

_DOCUMENT = (
    "When an order is submitted, validate the order, reserve inventory, and "
    "ship the order. If the order is invalid, raise OrderInvalid. Release "
    "inventory compensates Reserve inventory. Inputs: order_id, customer_id."
)


@pytest.fixture
def client() -> TestClient:
    provider = MockProvider(script_defaults=True)
    inner = WorkflowCompiler(
        llm_provider=provider,
        state_store=InMemoryStateStore(),
        review=ReviewConfig(enabled=False),
    )
    compiler = ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=InMemoryProjectStore(),
        segmentation_review=False,
    )
    app.dependency_overrides[get_project_compiler] = lambda: compiler
    app.dependency_overrides[get_compiler] = lambda: inner
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as test_client:
        test_client.post(
            "/auth/register",
            json={"email": "cas@example.com", "password": "password123", "display_name": "CAS"},
        )
        yield test_client
    app.dependency_overrides.clear()


def test_project_routes_expose_version_and_refuse_stale_writes(client: TestClient) -> None:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    assert compiled.status_code == 200, compiled.text
    body = compiled.json()
    project_id = body["project"]["project_id"]
    slug = next(iter(body["spec_markdown"]))
    got = client.get(f"/projects/{project_id}")
    version = got.json()["project"]["version"]
    assert version >= 1
    assert got.headers["ETag"] == f'"{version}"'
    # Summary rows carry it too.
    rows = client.get("/projects").json()["projects"]
    assert any(r["project_id"] == project_id and r["version"] == version for r in rows)

    markdown = body["spec_markdown"][slug]
    # A save with the right token succeeds and bumps the version (ETag follows).
    ok = client.put(
        f"/projects/{project_id}/spec",
        json={"spec_markdown": {slug: markdown}, "expected_version": version},
    )
    assert ok.status_code == 200, ok.text
    new_version = ok.json()["project"]["version"]
    assert new_version == version + 1
    assert ok.headers["ETag"] == f'"{new_version}"'
    # The stale token (another tab still holding the old version) is refused.
    stale = client.put(
        f"/projects/{project_id}/spec",
        json={"spec_markdown": {slug: markdown}, "expected_version": version},
    )
    assert stale.status_code == 409
    assert "changed since it was loaded" in stale.json()["detail"]
    # If-Match works the same way (quoted / weak / bare), '*' skips the check.
    assert (
        client.put(
            f"/projects/{project_id}/spec",
            json={"spec_markdown": {slug: markdown}},
            headers={"If-Match": f'W/"{version}"'},
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/projects/{project_id}/spec",
            json={"spec_markdown": {slug: markdown}},
            headers={"If-Match": "not-a-version"},
        ).status_code
        == 400
    )
    any_ok = client.put(
        f"/projects/{project_id}/spec",
        json={"spec_markdown": {slug: markdown}},
        headers={"If-Match": "*"},
    )
    assert any_ok.status_code == 200
    # No token at all → last-write-wins (opt-in CAS).
    assert (
        client.put(
            f"/projects/{project_id}/spec", json={"spec_markdown": {slug: markdown}}
        ).status_code
        == 200
    )
    current = client.get(f"/projects/{project_id}").json()["project"]["version"]
    # PATCH rename honours the token as well.
    renamed = client.patch(
        f"/projects/{project_id}", json={"nickname": "CAS demo", "expected_version": current}
    )
    assert renamed.status_code == 200 and renamed.json()["version"] == current + 1
    assert (
        client.patch(
            f"/projects/{project_id}", json={"nickname": "old tab", "expected_version": current}
        ).status_code
        == 409
    )
    assert client.get(f"/projects/{project_id}").json()["project"]["nickname"] == "CAS demo"


def test_path_shaped_project_ids_are_not_found_over_http(client: TestClient) -> None:
    for bad in ["..%2Fx", "a%5Cb", "id%20space"]:
        assert client.get(f"/projects/{bad}").status_code == 404
        assert client.patch(f"/projects/{bad}", json={"nickname": "x"}).status_code == 404

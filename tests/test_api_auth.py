"""Auth + project-ownership tests for the HTTP API (mock-backed)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import get_compiler, get_project_compiler
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.config import get_settings
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.project_store import InMemoryProjectStore
from workflow_compiler.storage.user_store import InMemoryUserStore

_NO_REVIEW = ReviewConfig(enabled=False)

_DOCUMENT = (
    "When an order is submitted, validate the order, reserve inventory, and "
    "ship the order. Inputs: order_id, customer_id."
)


@pytest.fixture
def compiler() -> Iterator[ProjectCompiler]:
    provider = MockProvider(script_defaults=True)
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    project_compiler = ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=InMemoryProjectStore(),
        segmentation_review=False,
    )
    users = InMemoryUserStore()
    app.dependency_overrides[get_project_compiler] = lambda: project_compiler
    app.dependency_overrides[get_compiler] = lambda: inner
    app.dependency_overrides[get_user_store] = lambda: users
    yield project_compiler
    app.dependency_overrides.clear()


def _register(client: TestClient, email: str, name: str) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "display_name": name},
    )
    assert response.status_code == 200
    payload: dict[str, str] = response.json()
    return payload


def _project_ids(client: TestClient) -> list[str]:
    """The visible project ids from the summary-shaped ``GET /projects`` payload."""
    response = client.get("/projects")
    assert response.status_code == 200
    return [summary["project_id"] for summary in response.json()["projects"]]


def test_register_login_me_logout_roundtrip(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        registered = _register(client, "Alice@Example.com", "Alice")
        assert registered["email"] == "alice@example.com"  # lowercased
        assert registered["display_name"] == "Alice"

        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["user_id"] == registered["user_id"]

        client.post("/auth/logout")
        assert client.get("/auth/me").status_code == 401

        login = client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "password123"},
        )
        assert login.status_code == 200
        assert client.get("/auth/me").status_code == 200


def test_login_failures_are_generic(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        _register(client, "alice@example.com", "Alice")
        client.post("/auth/logout")
        wrong_password = client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "wrong-password"},
        )
        unknown_email = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "password123"},
        )
        assert wrong_password.status_code == 401
        assert unknown_email.status_code == 401
        # Same message for both failure modes — don't reveal which part failed.
        assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_duplicate_email_is_409(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        _register(client, "alice@example.com", "Alice")
        response = client.post(
            "/auth/register",
            json={"email": "ALICE@example.com", "password": "password123"},
        )
        assert response.status_code == 409


def test_unauthenticated_requests_are_401(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        assert client.get("/projects").status_code == 401
        assert (
            client.post("/projects/compile", json={"document_text": _DOCUMENT}).status_code
            == 401
        )
        assert client.get("/workflows").status_code == 401
        # Liveness stays open.
        assert client.get("/health").status_code == 200


def test_projects_are_scoped_to_their_owner(
    compiler: ProjectCompiler, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Opt out of the default shared-visibility to exercise per-owner isolation.
    monkeypatch.setattr(get_settings(), "projects_shared", False)
    with TestClient(app) as alice, TestClient(app) as bob:
        _register(alice, "alice@example.com", "Alice")
        _register(bob, "bob@example.com", "Bob")

        compiled = alice.post("/projects/compile", json={"document_text": _DOCUMENT})
        assert compiled.status_code == 200
        project_id = compiled.json()["project"]["project_id"]
        assert compiled.json()["project"]["owner_id"] is not None

        assert project_id in _project_ids(alice)
        assert project_id not in _project_ids(bob)
        # Another account's project answers 404, indistinguishable from absent.
        assert bob.get(f"/projects/{project_id}").status_code == 404
        assert alice.get(f"/projects/{project_id}").status_code == 200


def test_projects_shared_visible_across_users(compiler: ProjectCompiler) -> None:
    # Default (projects_shared=True): every signed-in user sees every project,
    # while owner_id is still recorded for attribution.
    with TestClient(app) as alice, TestClient(app) as bob:
        _register(alice, "alice@example.com", "Alice")
        _register(bob, "bob@example.com", "Bob")

        compiled = alice.post("/projects/compile", json={"document_text": _DOCUMENT})
        project_id = compiled.json()["project"]["project_id"]
        assert compiled.json()["project"]["owner_id"] is not None

        assert project_id in _project_ids(bob)
        assert bob.get(f"/projects/{project_id}").status_code == 200


def test_legacy_unowned_projects_stay_visible(compiler: ProjectCompiler) -> None:
    with TestClient(app) as alice, TestClient(app) as bob:
        _register(alice, "alice@example.com", "Alice")
        _register(bob, "bob@example.com", "Bob")

        compiled = alice.post("/projects/compile", json={"document_text": _DOCUMENT})
        project_id = compiled.json()["project"]["project_id"]
        # Simulate a CLI-created / pre-auth project: strip the owner in the store.
        project = asyncio.run(compiler.load_project(project_id))
        project.owner_id = None
        asyncio.run(compiler.save_project(project))

        assert project_id in _project_ids(bob)
        assert bob.get(f"/projects/{project_id}").status_code == 200


def test_me_exposes_default_preferences(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        _register(client, "alice@example.com", "Alice")
        prefs = client.get("/auth/me").json()["preferences"]
        assert prefs["projects_page_size"] == 10
        assert prefs["baseline_hours"] == {}


def test_update_profile_persists_name_and_preferences(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        _register(client, "alice@example.com", "Alice")
        updated = client.put(
            "/auth/me",
            json={
                "display_name": "Alice R.",
                "preferences": {
                    "baseline_hours": {"compile": 10.0},
                    "projects_page_size": 25,
                },
            },
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["display_name"] == "Alice R."
        assert body["preferences"]["projects_page_size"] == 25
        assert body["preferences"]["baseline_hours"] == {"compile": 10.0}
        # Survives a fresh read (persisted to the user store).
        me = client.get("/auth/me").json()
        assert me["display_name"] == "Alice R."
        assert me["preferences"]["baseline_hours"] == {"compile": 10.0}


def test_update_profile_partial_leaves_other_fields(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        _register(client, "alice@example.com", "Alice")
        client.put("/auth/me", json={"preferences": {"projects_page_size": 50}})
        # Name omitted → unchanged; preferences applied.
        me = client.get("/auth/me").json()
        assert me["display_name"] == "Alice"
        assert me["preferences"]["projects_page_size"] == 50


def test_settings_defaults_returns_config_baselines(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        _register(client, "alice@example.com", "Alice")
        defaults = client.get("/settings/defaults")
        assert defaults.status_code == 200
        body = defaults.json()
        # Mirrors config.py Settings.baseline_hours categories.
        assert set(body["baseline_hours"]) >= {
            "discovery",
            "spec",
            "validate",
            "compile",
            "edit",
        }
        assert body["projects_page_size"] == 10


def test_settings_defaults_requires_auth(compiler: ProjectCompiler) -> None:
    with TestClient(app) as client:
        assert client.get("/settings/defaults").status_code == 401

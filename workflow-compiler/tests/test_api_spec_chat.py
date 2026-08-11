"""API tests for the free-form spec chat endpoints (mock-backed).

Same harness shape as ``test_api_dialogue.py``. What these check is the HTTP
contract rather than the engine's logic (that is ``test_spec_chat.py``): that
POST opens a session implicitly, that an applied change is visible in the
returned ``spec_markdown`` without a second request, and that an unknown slug is
rejected rather than silently redirected.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import get_compiler, get_project_compiler
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import InstructionPlan, Patch, PatchAction
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.project_store import InMemoryProjectStore
from workflow_compiler.storage.user_store import InMemoryUserStore

_NO_REVIEW = ReviewConfig(enabled=False)

_DOCUMENT = (
    "When an order is submitted, validate the order, reserve inventory, and "
    "ship the order. If the order is invalid, raise OrderInvalid. Release "
    "inventory compensates Reserve inventory. Inputs: order_id, customer_id."
)


class _Harness:
    """The pieces a spec-chat API test needs to drive and inspect a run."""

    def __init__(
        self, client: TestClient, compiler: ProjectCompiler, provider: MockProvider
    ) -> None:
        self.client = client
        self.compiler = compiler
        self.provider = provider

    def queue(self, *responses: object) -> None:
        """Append exact structured responses for the chat calls to consume."""
        self.provider._structured.extend(responses)


@pytest.fixture
def harness() -> _Harness:
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
    app.dependency_overrides[get_compiler] = lambda: inner
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={
                "email": "tester@example.com",
                "password": "password123",
                "display_name": "Tester",
            },
        )
        yield _Harness(client, compiler, provider)
    app.dependency_overrides.clear()


def _compile(harness: _Harness) -> str:
    response = harness.client.post("/projects/compile", json={"document_text": _DOCUMENT})
    assert response.status_code == 200
    return str(response.json()["project"]["project_id"])


def _plan(**kwargs: object) -> InstructionPlan:
    return InstructionPlan(**kwargs)  # type: ignore[arg-type]


def test_get_chat_is_empty_before_anything_is_said(harness: _Harness) -> None:
    project_id = _compile(harness)

    body = harness.client.get(f"/projects/{project_id}/chat").json()

    assert body["session"] is None
    assert body["reply"] is None
    assert body["spec_markdown"]


def test_post_opens_a_session_implicitly_and_applies(harness: _Harness) -> None:
    """No validate and no explicit start — posting a message is the whole flow."""
    project_id = _compile(harness)
    harness.queue(
        _plan(
            patches=[
                Patch(action=PatchAction.ADD, target="actors", payload={"value": "Warehouse"})
            ],
            reply="Added Warehouse as an actor.",
        )
    )

    response = harness.client.post(
        f"/projects/{project_id}/chat", json={"message": "warehouse should be an actor"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "applied"
    assert body["reply"] == "Added Warehouse as an actor."
    assert body["applied"] == 1
    assert body["session"] is not None
    # The change is in the returned Markdown — no second request needed. This is
    # what lets the client adopt it straight into the editor buffers.
    assert "Warehouse" in "".join(body["spec_markdown"].values())


def test_a_clarifying_question_changes_nothing_yet(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.queue(
        _plan(needs_clarification=True, clarifying_question="Which step is missing?")
    )

    body = harness.client.post(
        f"/projects/{project_id}/chat", json={"message": "make it better"}
    ).json()

    assert body["status"] == "clarifying"
    assert body["reply"] == "Which step is missing?"
    assert body["awaiting_clarification"] is True
    assert body["changes"] == []


def test_an_unknown_slug_is_a_client_error(harness: _Harness) -> None:
    project_id = _compile(harness)

    response = harness.client.post(
        f"/projects/{project_id}/chat",
        json={"message": "add an actor", "slug": "no-such-workflow"},
    )

    assert response.status_code == 400
    assert "no-such-workflow" in response.json()["detail"]


def test_an_empty_message_is_rejected_by_validation(harness: _Harness) -> None:
    project_id = _compile(harness)

    response = harness.client.post(f"/projects/{project_id}/chat", json={"message": ""})

    assert response.status_code == 422


def test_the_transcript_survives_a_reload(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.queue(_plan(park_note="Ownership is undecided.", reply="Recorded."))
    harness.client.post(f"/projects/{project_id}/chat", json={"message": "who owns this?"})

    body = harness.client.get(f"/projects/{project_id}/chat").json()

    assert [t["role"] for t in body["session"]["turns"]] == ["user", "assistant"]
    assert body["session"]["turns"][0]["text"] == "who owns this?"


def test_delete_closes_the_chat_but_keeps_the_change(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.queue(
        _plan(
            patches=[
                Patch(action=PatchAction.ADD, target="actors", payload={"value": "Warehouse"})
            ]
        )
    )
    harness.client.post(f"/projects/{project_id}/chat", json={"message": "add warehouse"})

    body = harness.client.delete(f"/projects/{project_id}/chat").json()

    assert body["session"] is None
    assert "Warehouse" in "".join(body["spec_markdown"].values())

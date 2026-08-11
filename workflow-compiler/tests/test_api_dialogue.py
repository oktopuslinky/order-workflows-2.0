"""API tests for the conversational spec-resolution endpoints (mock-backed).

The project is compiled with the mock's scripted defaults, then findings are
seeded onto the stored project so there is something to ask about. The dialogue
responses themselves are queued exactly, because what these tests check is the
HTTP contract — status codes, the reported prompt, and that an applied answer is
visible in the returned spec Markdown without a second request.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import get_compiler, get_project_compiler
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    AnswerPlan,
    DraftedQuestion,
    DraftedQuestions,
    Patch,
    PatchAction,
    Severity,
    SpecFinding,
)
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
    """The pieces a dialogue API test needs to drive and inspect a run."""

    def __init__(
        self, client: TestClient, compiler: ProjectCompiler, provider: MockProvider
    ) -> None:
        self.client = client
        self.compiler = compiler
        self.provider = provider

    def queue(self, *responses: object) -> None:
        """Append exact structured responses for the dialogue calls to consume.

        The compile stages ran earlier against an empty queue, so they used the
        mock's scripted defaults; anything queued now is read by the next
        structured call, which is the dialogue's.
        """
        self.provider._structured.extend(responses)

    def seed_findings(self, project_id: str, *findings: SpecFinding) -> str:
        """Attach findings to the project's first spec and persist. Returns its slug."""

        async def _seed() -> str:
            project = await self.compiler.load_project(project_id)
            slug = str(project.specs[0].slug)
            project.validation_findings = {slug: list(findings)}
            await self.compiler.save_project(project)
            return slug

        return asyncio.run(_seed())

    def clear_open_items(self, project_id: str) -> None:
        """Strip every finding and open question, so there is genuinely nothing to ask."""

        async def _clear() -> None:
            project = await self.compiler.load_project(project_id)
            project.validation_findings = {}
            for spec in project.specs:
                spec.open_questions = []
            await self.compiler.save_project(project)

        asyncio.run(_clear())


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


def _agenda(question: str) -> DraftedQuestions:
    return DraftedQuestions(
        questions=[
            DraftedQuestion(slug="demo-order-workflow", question=question, section="Outputs")
        ]
    )


def test_start_dialogue_returns_the_first_question(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.seed_findings(project_id, SpecFinding(message="Outputs are unconsumed."))
    harness.queue(_agenda("Where do the outputs go?"))

    response = harness.client.post(f"/projects/{project_id}/dialogue")

    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] == "Where do the outputs go?"
    assert body["question"]["text"] == "Where do the outputs go?"
    assert body["total"] == 1
    assert body["remaining"] == 1
    assert body["answered"] == 0


def test_start_dialogue_400s_when_nothing_to_resolve(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.clear_open_items(project_id)

    response = harness.client.post(f"/projects/{project_id}/dialogue")

    assert response.status_code == 400
    assert "Nothing to resolve" in response.json()["detail"]


def test_a_freshly_compiled_project_has_something_to_resolve(harness: _Harness) -> None:
    """The spec gate's own open questions are enough to start — no validate needed."""
    project_id = _compile(harness)

    response = harness.client.post(f"/projects/{project_id}/dialogue")

    assert response.status_code == 200
    assert response.json()["prompt"]


def test_answer_applies_and_reports_the_change(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.seed_findings(project_id, SpecFinding(message="No shipping step."))
    harness.queue(
        _agenda("What happens after payment?"),
        AnswerPlan(
            patches=[
                Patch(
                    action=PatchAction.ADD,
                    target="activity",
                    payload={"name": "Pack and ship order"},
                )
            ]
        ),
    )
    harness.client.post(f"/projects/{project_id}/dialogue")

    response = harness.client.post(
        f"/projects/{project_id}/dialogue/answer",
        json={"answer": "we pack it and ship it out"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changes"], "an applied answer must report what it changed"
    assert body["answered"] == 1
    assert body["parked_as"] is None
    # The updated spec rides the same response — no second fetch needed.
    assert "Pack and ship order" in body["spec_markdown"]["demo-order-workflow"]
    assert body["project"]["stage"] == "spec_drafted"


def test_answer_can_ask_a_followup_without_advancing(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.seed_findings(project_id, SpecFinding(message="Declined path undefined."))
    harness.queue(
        _agenda("What happens when payment is declined?"),
        AnswerPlan(needs_followup=True, followup_question="Which customers get retried?"),
    )
    harness.client.post(f"/projects/{project_id}/dialogue")

    response = harness.client.post(
        f"/projects/{project_id}/dialogue/answer", json={"answer": "depends"}
    )

    body = response.json()
    assert body["prompt"] == "Which customers get retried?"
    assert body["remaining"] == 1, "a follow-up must not consume the question"
    assert body["answered"] == 0


def test_unmappable_answer_is_reported_as_parked(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.seed_findings(project_id, SpecFinding(message="Declined path undefined."))
    harness.queue(
        _agenda("What happens when payment is declined?"),
        AnswerPlan(park_note="Ops owns the declined path; not decided yet."),
    )
    harness.client.post(f"/projects/{project_id}/dialogue")

    response = harness.client.post(
        f"/projects/{project_id}/dialogue/answer", json={"answer": "ops owns that"}
    )

    body = response.json()
    assert body["parked_as"] == "Ops owns the declined path; not decided yet."
    assert body["changes"] == []
    assert "Ops owns the declined path" in body["spec_markdown"]["demo-order-workflow"]


def test_empty_answer_is_rejected_by_validation(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.seed_findings(project_id, SpecFinding(message="Something."))
    harness.queue(_agenda("A question?"))
    harness.client.post(f"/projects/{project_id}/dialogue")

    response = harness.client.post(
        f"/projects/{project_id}/dialogue/answer", json={"answer": ""}
    )

    assert response.status_code == 422


def test_answer_without_an_open_session_400s(harness: _Harness) -> None:
    project_id = _compile(harness)

    response = harness.client.post(
        f"/projects/{project_id}/dialogue/answer", json={"answer": "hello"}
    )

    assert response.status_code == 400
    assert "No dialogue session is open" in response.json()["detail"]


def test_skip_advances_without_changing_the_spec(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.seed_findings(project_id, SpecFinding(message="Something."))
    harness.queue(_agenda("A question?"))
    before = harness.client.post(f"/projects/{project_id}/dialogue").json()

    response = harness.client.post(f"/projects/{project_id}/dialogue/skip")

    body = response.json()
    assert body["remaining"] == 0
    assert body["answered"] == 0
    assert (
        body["spec_markdown"]["demo-order-workflow"]
        == before["spec_markdown"]["demo-order-workflow"]
    )


def test_get_dialogue_reports_no_open_session(harness: _Harness) -> None:
    project_id = _compile(harness)

    body = harness.client.get(f"/projects/{project_id}/dialogue").json()

    assert body["session"] is None
    assert body["question"] is None
    assert body["total"] == 0


def test_end_dialogue_closes_the_session_and_keeps_changes(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.seed_findings(project_id, SpecFinding(message="No shipping step."))
    harness.queue(
        _agenda("What next?"),
        AnswerPlan(
            patches=[
                Patch(action=PatchAction.ADD, target="activity", payload={"name": "Ship it"})
            ]
        ),
    )
    harness.client.post(f"/projects/{project_id}/dialogue")
    harness.client.post(
        f"/projects/{project_id}/dialogue/answer", json={"answer": "we ship it"}
    )

    response = harness.client.delete(f"/projects/{project_id}/dialogue")

    assert response.status_code == 200
    body = response.json()
    assert body["session"] is None
    # The applied answer survives closing the session.
    assert "Ship it" in body["spec_markdown"]["demo-order-workflow"]
    assert harness.client.get(f"/projects/{project_id}/dialogue").json()["session"] is None


def test_dialogue_endpoints_require_authentication(harness: _Harness) -> None:
    project_id = _compile(harness)
    harness.client.cookies.clear()

    assert harness.client.post(f"/projects/{project_id}/dialogue").status_code == 401
    assert harness.client.get(f"/projects/{project_id}/dialogue").status_code == 401


def test_severity_is_carried_onto_the_question(harness: _Harness) -> None:
    project_id = _compile(harness)
    blocking = SpecFinding(severity=Severity.BLOCKING, message="Blocking problem.")
    harness.seed_findings(project_id, blocking)
    harness.queue(
        DraftedQuestions(
            questions=[
                DraftedQuestion(
                    slug="demo-order-workflow",
                    question="Fix the blocking thing?",
                    covers=[blocking.as_string()],
                )
            ]
        )
    )

    body = harness.client.post(f"/projects/{project_id}/dialogue").json()

    assert body["question"]["severity"] == "blocking"

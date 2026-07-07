"""End-to-end tests for the spec-centric ProjectCompiler pipeline.

Drive the full front-end (segmentation → per-workflow extraction → specs),
simulate a human editing the spec files, validate, approve, and check that each
workflow independently produces graph/CVPA/Temporal/code artifacts — all against
an exact MockProvider queue (review pipelines disabled, as in test_integration).
"""

from __future__ import annotations

import re

import pytest

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.agents import FactExtraction, WorkflowDiscovery
from workflow_compiler.agents.segmentation import (
    DiscoveredDependency,
    DiscoveredWorkflow,
    WorkflowsDiscovery,
)
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.exceptions import ApprovalError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    ApprovalStatus,
    CompilationStage,
    ProjectStage,
    ReviewResult,
)
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.project_store import InMemoryProjectStore

_NO_REVIEW = ReviewConfig(enabled=False)

_DOCUMENT = """\
# Customer Lifecycle

## Onboarding Purpose

The onboarding workflow registers a new customer when an application is
submitted. It validates the application and creates the customer record,
returning a customer_record_id.

## Onboarding Process

1. Validate the application.
2. Create the customer record.

## Provisioning Purpose

The provisioning workflow activates an account for a registered customer when
an account.provision request arrives. It requires the customer_record_id.

## Provisioning Process

1. Reserve an account number.
2. Activate the account.
"""


def _segmentation() -> WorkflowsDiscovery:
    return WorkflowsDiscovery(
        workflows=[
            DiscoveredWorkflow(
                name="Customer Onboarding",
                purpose="Register a new customer.",
                section_titles=["Onboarding Purpose", "Onboarding Process"],
            ),
            DiscoveredWorkflow(
                name="Account Provisioning",
                purpose="Activate an account.",
                section_titles=["Provisioning Purpose", "Provisioning Process"],
            ),
        ],
        dependencies=[
            DiscoveredDependency(
                source_workflow="Customer Onboarding",
                output_field="customer_record_id",
                target_workflow="Account Provisioning",
                input_field="customer_record_id",
            )
        ],
        confidence=0.9,
    )


def _discovery(name: str, trigger: str) -> WorkflowDiscovery:
    return WorkflowDiscovery(
        name=name,
        purpose=f"{name} purpose.",
        actors=["Customer"],
        systems=["Customer Service"],
        trigger_events=[trigger],
        end_states=["done"],
        confidence=0.9,
    )


def _facts(activities: list[str]) -> FactExtraction:
    return FactExtraction(activities=activities, confidence=0.85)


def _cvpa() -> dict[str, object]:
    return {"assignments": [{"node_id": "start", "phase": "capture", "confidence": 0.9}]}


def _temporal(name: str) -> dict[str, object]:
    return {
        "workflow_name": name,
        "task_queue": "default",
        "activities": [{"name": "do work"}],
        "confidence": 0.9,
    }


def _compiler(provider: MockProvider) -> ProjectCompiler:
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    return ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=InMemoryProjectStore(),
        segmentation_review=False,
        graph_health_threshold=0.9,
    )


def _front_end_queue() -> list[object]:
    return [
        _segmentation(),
        _discovery("Customer Onboarding", "application submitted"),
        _facts(["Validate the application", "Create the customer record"]),
        _discovery("Account Provisioning", "account.provision request"),
        _facts(["Reserve an account number", "Activate the account"]),
    ]


def _answer_question(markdown: str, ref: str, answer: str) -> str:
    """Fill the ``Answer:`` line that follows the open question with ``ref``."""
    pattern = re.compile(rf"(\(({re.escape(ref)})\)[^\n]*\n  Answer:)[^\n]*")
    result, count = pattern.subn(rf"\1 {answer}", markdown)
    assert count == 1, f"question {ref} not found in spec file"
    return result


async def test_compile_document_stops_at_spec_gate(tmp_path) -> None:
    provider = MockProvider(structured=_front_end_queue())
    compiler = _compiler(provider)

    project = await compiler.compile_document(_DOCUMENT)
    assert project.stage is ProjectStage.SPEC_DRAFTED
    assert project.spec_approval_status is ApprovalStatus.PENDING
    assert [s.slug for s in project.specs] == ["customer-onboarding", "account-provisioning"]

    # Segments carry only their own workflow's text.
    onboarding = project.segment_for("customer-onboarding")
    provisioning = project.segment_for("account-provisioning")
    assert onboarding is not None and "Reserve an account number" not in onboarding.text
    assert provisioning is not None and "Validate the application" not in provisioning.text

    # The discovered output→input dependency became a typed cross-reference.
    assert len(project.cross_references) == 1
    ref = project.cross_references[0]
    assert (ref.source_workflow, ref.target_workflow) == (
        "customer-onboarding",
        "account-provisioning",
    )
    assert not ref.user_confirmed

    # The checklist was absorbed into open questions (e.g. missing inputs).
    spec = project.spec_for("customer-onboarding")
    assert spec is not None
    assert any(q.ref == "R2-inputs" for q in spec.open_questions)

    # Spec files are written to disk, one per workflow plus the overview.
    paths = compiler.write_spec_files(project, tmp_path)
    names = sorted(p.name for p in paths)
    assert names == ["account-provisioning.md", "customer-onboarding.md", "overview.md"]
    assert "How to proceed" in (tmp_path / "overview.md").read_text(encoding="utf-8")


async def test_validate_approve_and_compile_each_workflow(tmp_path) -> None:
    queue: list[object] = _front_end_queue()
    # validate_specs: three no_change validator passes per spec.
    queue += [ReviewResult(patches=[]) for _ in range(6)]
    # approve: CVPA + Temporal design per workflow (codegen is deterministic).
    queue += [_cvpa(), _temporal("CustomerOnboarding"), _cvpa(), _temporal("AccountProvisioning")]
    provider = MockProvider(structured=queue)
    compiler = _compiler(provider)

    project = await compiler.compile_document(_DOCUMENT)
    compiler.write_spec_files(project, tmp_path)

    # Simulate the human review: answer the required questions and confirm the
    # cross-workflow dependency in both files.
    edited: dict[str, str] = {}
    for spec in project.specs:
        markdown = (tmp_path / f"{spec.slug}.md").read_text(encoding="utf-8")
        if any(q.ref == "R2-inputs" for q in spec.open_questions):
            markdown = _answer_question(markdown, "R2-inputs", "customer_record_id, plan_code")
        markdown = markdown.replace("- [ ] uses output", "- [x] uses output")
        markdown = markdown.replace("- [ ] provides output", "- [x] provides output")
        edited[spec.slug] = markdown

    project = await compiler.validate_specs(
        project.project_id, markdown_by_slug=edited
    )
    assert project.stage is ProjectStage.SPEC_VALIDATED
    assert project.cross_references[0].user_confirmed
    onboarding = project.spec_for("customer-onboarding")
    assert onboarding is not None
    answered = next(q for q in onboarding.open_questions if q.ref == "R2-inputs")
    assert answered.answer == "customer_record_id, plan_code"

    project = await compiler.approve_spec(project.project_id, reviewer="alice")
    assert project.stage is ProjectStage.COMPLETED
    assert project.spec_approval_status is ApprovalStatus.APPROVED
    assert set(project.workflow_ids) == {"customer-onboarding", "account-provisioning"}

    # Each workflow independently reached COMPLETED with all artifacts.
    for slug, workflow_id in project.workflow_ids.items():
        state = await compiler.workflow_compiler.load_state(workflow_id)
        assert state.stage is CompilationStage.COMPLETED, slug
        assert state.project_id == project.project_id
        assert state.workflow_graph is not None
        assert state.cvpa_classification is not None
        assert state.temporal_design is not None
        assert state.temporal_code is not None
        # The back-end compiled from the rendered spec, not the raw document.
        assert state.document_text.startswith("# ")
        assert "workflow-compiler specification" in state.document_text


async def test_approve_requires_confirmed_cross_references() -> None:
    provider = MockProvider(structured=_front_end_queue())
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    with pytest.raises(ApprovalError, match="Unconfirmed cross-workflow"):
        await compiler.approve_spec(project.project_id)


async def test_approve_blocks_on_unanswered_required_questions() -> None:
    queue: list[object] = _front_end_queue()
    provider = MockProvider(structured=queue)
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    project = await compiler.approve_spec(
        project.project_id, allow_unconfirmed_references=True
    )
    assert project.stage is ProjectStage.NEEDS_ATTENTION
    # Neither workflow compiled; findings explain the block.
    assert project.workflow_ids == {}
    for slug in ("customer-onboarding", "account-provisioning"):
        findings = project.validation_findings.get(slug, [])
        assert any("unmet required checklist items" in f for f in findings), slug


async def test_compile_prepared_threshold_gate() -> None:
    """Below the health threshold the workflow stays at the human gate."""
    queue: list[object] = [
        _discovery("Solo Workflow", "request received"),
        _facts(["Do the work"]),
    ]
    provider = MockProvider(structured=queue)
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    state = await inner.extract_facts("Do the work when a request is received.")
    state.stage = CompilationStage.FACTS_EXTRACTED

    # An impossible threshold: the graph is reviewed but never auto-approved.
    result = await inner.compile_prepared(
        state, persist=False, auto_approve_threshold=1.01
    )
    assert result.stage is CompilationStage.REVIEWED
    assert result.approval_status is ApprovalStatus.PENDING
    assert result.cvpa_classification is None

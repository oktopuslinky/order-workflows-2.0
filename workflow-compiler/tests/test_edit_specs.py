"""Integration tests for ProjectCompiler.edit_specs (the edit-request flow).

All tests drive the real orchestration against an exact MockProvider queue
(review pipelines disabled). The mock returns the EditPlans the interpreter
would produce; everything after the LLM call is the production code path.
"""

from __future__ import annotations

import asyncio

import pytest

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.agents import FactExtraction, WorkflowDiscovery
from workflow_compiler.agents.segmentation import (
    DiscoveredDependency,
    DiscoveredWorkflow,
    WorkflowsDiscovery,
)
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.exceptions import CompilationError, EditPreviewStaleError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    ApprovalStatus,
    EditPlan,
    Patch,
    PatchAction,
    ProjectStage,
    Provenance,
    ReviewResult,
    TriggerMode,
    TriggerOp,
    WiringAction,
    WorkflowTrigger,
    XrefOp,
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

_EDIT_DOC = """\
# Edit Request

## Workflow: customer-onboarding

### Add

- A business rule: refunds over $500 require manager approval.
- An activity: Notify the auditor.

## Reason

Test edit.
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


def _front_end_queue() -> list[object]:
    return [
        _segmentation(),
        _discovery("Customer Onboarding", "application submitted"),
        _facts(["Validate the application", "Create the customer record"]),
        _discovery("Account Provisioning", "account.provision request"),
        _facts(["Reserve an account number", "Activate the account"]),
    ]


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


def _happy_plan() -> EditPlan:
    return EditPlan(
        patches=[
            Patch(
                action=PatchAction.ADD,
                target="rule",
                payload={"value": "Refunds over $500 require manager approval"},
            ),
            Patch(
                action=PatchAction.ADD,
                target="activity",
                payload={"name": "Notify the auditor"},
            ),
        ]
    )


async def test_edit_specs_happy_path() -> None:
    provider = MockProvider(structured=[*_front_end_queue(), _happy_plan()])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    project = await compiler.edit_specs(
        project.project_id, _EDIT_DOC, author="devansh"
    )

    spec = project.spec_for("customer-onboarding")
    assert spec is not None
    rule_key = "rule:refunds over $500 require manager approval"
    assert any(
        f.statement == "Refunds over $500 require manager approval"
        for f in spec.facts.facts
    )
    assert spec.provenance_of(rule_key) is Provenance.HUMAN_PROVIDED
    # The compiled spec has no relational structure, so the activity add lands
    # as a flat fact — and the pre-existing flat facts must survive the edit.
    assert spec.facts.structure is None
    assert any(
        f.category.value == "activity" and f.statement == "Notify the auditor"
        for f in spec.facts.facts
    )
    assert spec.provenance_of("activity:notify the auditor") is Provenance.HUMAN_PROVIDED
    for name in ("Validate the application", "Create the customer record"):
        assert any(f.statement == name for f in spec.facts.facts)

    # Version bumped, edit log appended, re-gate armed.
    assert spec.metadata.version == "0.1.1"
    assert len(project.edit_log) == 1
    record = project.edit_log[0]
    assert record.author == "devansh"
    # EditRecord (a strict domain model) strips surrounding whitespace.
    assert record.document == _EDIT_DOC.strip()
    assert record.resolved_patches["customer-onboarding"]
    assert record.summary["customer-onboarding"]
    assert project.stage is ProjectStage.SPEC_DRAFTED
    assert project.spec_approval_status is ApprovalStatus.PENDING
    assert project.validation_findings == {}

    # The untouched workflow keeps its version.
    other = project.spec_for("account-provisioning")
    assert other is not None and other.metadata.version == "0.1.0"


async def test_edit_specs_atomic_on_unresolved() -> None:
    edit_doc = _EDIT_DOC + "\n## Workflow: account-provisioning\n\n### Modify\n- make it better\n"
    plans = [
        _happy_plan(),
        EditPlan(unresolved=["make it better"]),
    ]
    provider = MockProvider(structured=[*_front_end_queue(), *plans])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)
    before = project.model_dump(mode="json")

    with pytest.raises(CompilationError, match="make it better"):
        await compiler.edit_specs(project.project_id, edit_doc)

    stored = await compiler.load_project(project.project_id)
    assert stored.model_dump(mode="json") == before  # nothing was applied


async def test_edit_specs_rejects_unknown_patch_target() -> None:
    plan = EditPlan(
        patches=[Patch(action=PatchAction.REMOVE, target="activity:zz99")]
    )
    provider = MockProvider(structured=[*_front_end_queue(), plan])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    with pytest.raises(CompilationError, match="could not be applied"):
        await compiler.edit_specs(project.project_id, _EDIT_DOC)


async def test_edit_specs_trigger_ops() -> None:
    trigger_doc = """\
# Edit Request

## Workflow: customer-onboarding

### Triggers

- Onboarding starts provisioning when the record is created.
"""
    # compile_document already derived onboarding → provisioning from the
    # discovered dependency, so exercise MODIFY on it plus ADD of the reverse.
    plan = EditPlan(
        trigger_ops=[
            TriggerOp(
                action=WiringAction.MODIFY,
                source_workflow="customer-onboarding",
                target_workflow="account-provisioning",
                trigger=WorkflowTrigger(
                    source_workflow="customer-onboarding",
                    target_workflow="account-provisioning",
                    mode=TriggerMode.BLOCKING,
                    condition="record created",
                    result_binding="provisioning_result",
                ),
            ),
            TriggerOp(
                action=WiringAction.ADD,
                source_workflow="account-provisioning",
                target_workflow="customer-onboarding",
                trigger=WorkflowTrigger(
                    source_workflow="account-provisioning",
                    target_workflow="customer-onboarding",
                    mode=TriggerMode.FIRE_AND_FORGET,
                ),
            ),
        ]
    )
    provider = MockProvider(structured=[*_front_end_queue(), plan])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)
    assert len(project.triggers) == 1 and not project.triggers[0].user_confirmed

    project = await compiler.edit_specs(project.project_id, trigger_doc)
    assert len(project.triggers) == 2
    modified = next(t for t in project.triggers
                    if t.target_workflow == "account-provisioning")
    assert modified.mode is TriggerMode.BLOCKING
    assert modified.condition == "record created"
    assert modified.user_confirmed  # human-authored wiring needs no checkbox round-trip
    added = next(t for t in project.triggers
                 if t.target_workflow == "customer-onboarding")
    assert added.user_confirmed
    assert len(project.edit_log[0].trigger_ops) == 2


async def test_edit_specs_trigger_remove_requires_existing() -> None:
    # The reverse direction was never wired — removing it must fail.
    plan = EditPlan(
        trigger_ops=[
            TriggerOp(
                action=WiringAction.REMOVE,
                source_workflow="account-provisioning",
                target_workflow="customer-onboarding",
            )
        ]
    )
    provider = MockProvider(structured=[*_front_end_queue(), plan])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    doc = (
        "# Edit Request\n\n## Workflow: customer-onboarding\n\n"
        "### Triggers\n- Remove the trigger.\n"
    )
    with pytest.raises(CompilationError, match="No trigger"):
        await compiler.edit_specs(project.project_id, doc)


async def test_edit_specs_xref_ops_add_and_remove() -> None:
    doc = (
        "# Edit Request\n\n## Workflow: customer-onboarding\n\n"
        "### Dependencies\n- Provisioning also needs the plan code.\n"
    )
    from workflow_compiler.models import CrossReference

    plan = EditPlan(
        xref_ops=[
            XrefOp(
                action=WiringAction.ADD,
                reference=CrossReference(
                    source_workflow="customer-onboarding",
                    output_field="plan_code",
                    target_workflow="account-provisioning",
                    input_field="plan_code",
                ),
            )
        ]
    )
    provider = MockProvider(structured=[*_front_end_queue(), plan])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    project = await compiler.edit_specs(project.project_id, doc)
    assert len(project.cross_references) == 2
    added = next(r for r in project.cross_references if r.output_field == "plan_code")
    assert added.user_confirmed


async def test_edit_specs_add_and_remove_workflow() -> None:
    doc = """\
# Edit Request

## Add Workflow: billing

# Billing Workflow

## Purpose

Bill the customer monthly.

## Process

1. Compute the invoice.
2. Charge the customer.

## Remove Workflow: account-provisioning

## Reason

Restructure.
"""
    queue: list[object] = [
        *_front_end_queue(),
        # add-workflow runs discovery + facts on the new body
        _discovery("Billing", "monthly cycle"),
        _facts(["Compute the invoice", "Charge the customer"]),
    ]
    provider = MockProvider(structured=queue)
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)
    assert len(project.cross_references) == 1  # onboarding → provisioning

    project = await compiler.edit_specs(project.project_id, doc)

    assert {s.slug for s in project.specs} == {"customer-onboarding", "billing"}
    assert project.segment_for("billing") is not None
    assert "added workflow billing" in project.document_text
    # The dependency touching the removed workflow was dropped.
    assert project.cross_references == []
    record = project.edit_log[0]
    assert record.workflows_added == ["billing"]
    assert record.workflows_removed == ["account-provisioning"]
    assert any("dropped dependency" in line for line in record.summary["account-provisioning"])


async def test_edit_specs_workflow_filter_enforced() -> None:
    provider = MockProvider(structured=_front_end_queue())
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    with pytest.raises(CompilationError, match="outside the --workflow filter"):
        await compiler.edit_specs(
            project.project_id, _EDIT_DOC, workflows=["account-provisioning"]
        )


async def test_edit_then_validate_then_approve_regate() -> None:
    """The full re-gate: compile → edit → validate → approve runs cleanly."""
    queue: list[object] = [*_front_end_queue(), _happy_plan()]
    # validate after the edit: three no_change passes per spec (2 specs).
    queue += [ReviewResult(patches=[]) for _ in range(6)]
    # approve: CVPA + Temporal design per workflow.
    cvpa = {"assignments": [{"node_id": "start", "phase": "capture", "confidence": 0.9}]}

    def temporal(name: str) -> dict[str, object]:
        return {
            "workflow_name": name,
            "task_queue": "default",
            "activities": [{"name": "do work"}],
            "confidence": 0.9,
        }

    queue += [cvpa, temporal("CustomerOnboarding"), cvpa, temporal("AccountProvisioning")]
    provider = MockProvider(structured=queue)
    compiler = _compiler(provider)

    project = await compiler.compile_document(_DOCUMENT)
    project = await compiler.edit_specs(project.project_id, _EDIT_DOC)
    assert project.stage is ProjectStage.SPEC_DRAFTED

    # Answer the open questions so the gate clears, confirm the dependency.
    for spec in project.specs:
        for question in spec.open_questions:
            question.resolved = True
            question.answer = "customer_record_id"
    for ref in project.cross_references:
        ref.user_confirmed = True
    await compiler.save_project(project)

    project = await compiler.validate_specs(project.project_id)
    assert project.stage is ProjectStage.SPEC_VALIDATED
    # The human-provided rule survived the validator's grounding pass.
    spec = project.spec_for("customer-onboarding")
    assert spec is not None
    assert any("manager approval" in f.statement for f in spec.facts.facts)

    project = await compiler.approve_spec(project.project_id, reviewer="alice")
    assert project.stage is ProjectStage.COMPLETED
    assert project.spec_approval_status is ApprovalStatus.APPROVED


async def test_edit_specs_skips_satisfied_add() -> None:
    """An ADD whose value is already in the spec is skipped loudly, not fatal."""
    plan = EditPlan(
        patches=[
            # Already present in the compiled facts → benign, skipped.
            Patch(
                action=PatchAction.ADD,
                target="activity",
                payload={"name": "Validate the application"},
            ),
            # Genuinely new → applied.
            Patch(
                action=PatchAction.ADD,
                target="rule",
                payload={"value": "Refunds over $500 require manager approval"},
            ),
        ]
    )
    provider = MockProvider(structured=[*_front_end_queue(), plan])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    project = await compiler.edit_specs(project.project_id, _EDIT_DOC)

    spec = project.spec_for("customer-onboarding")
    assert spec is not None
    # The rule landed; the duplicate activity did not double up.
    assert any(
        f.statement == "Refunds over $500 require manager approval"
        for f in spec.facts.facts
    )
    statements = [f.statement for f in spec.facts.facts]
    assert statements.count("Validate the application") == 1
    assert "Create the customer record" in statements
    # The skip is recorded in the edit summary — never silent.
    summary = project.edit_log[0].summary["customer-onboarding"]
    assert any("skipped (already present)" in line for line in summary)
    assert spec.metadata.version == "0.1.1"


async def test_edit_specs_names_dropped_operations() -> None:
    """A fatal drop lists the offending operation in the error message."""
    plan = EditPlan(
        patches=[Patch(action=PatchAction.REMOVE, target="activity:zz99")]
    )
    provider = MockProvider(structured=[*_front_end_queue(), plan])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)
    before = project.model_dump(mode="json")

    with pytest.raises(CompilationError, match=r"activity:zz99"):
        await compiler.edit_specs(project.project_id, _EDIT_DOC)

    stored = await compiler.load_project(project.project_id)
    assert stored.model_dump(mode="json") == before  # atomic: nothing applied


async def test_write_spec_files_clears_removed_workflow_file(tmp_path) -> None:
    """A removed workflow's stale spec file is deleted on re-render."""
    remove_doc = (
        "# Edit Request\n\n## Remove Workflow: account-provisioning\n\n"
        "## Reason\n\nRetired.\n"
    )
    provider = MockProvider(structured=_front_end_queue())
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)
    compiler.write_spec_files(project, tmp_path)
    assert (tmp_path / "account-provisioning.md").exists()

    project = await compiler.edit_specs(project.project_id, remove_doc)
    compiler.write_spec_files(project, tmp_path)

    assert not (tmp_path / "account-provisioning.md").exists()
    assert (tmp_path / "customer-onboarding.md").exists()


# ---------------------------------------------------------------------------
# Preview → confirm (dry-run + LLM-free replay)
# ---------------------------------------------------------------------------


async def test_preview_edit_does_not_persist() -> None:
    provider = MockProvider(structured=[*_front_end_queue(), _happy_plan()])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)
    before = project.model_dump(mode="json")

    preview = await compiler.preview_edit(
        project.project_id, _EDIT_DOC, author="devansh"
    )

    # The preview shows the would-be result...
    assert preview.record.resolved_patches["customer-onboarding"]
    assert preview.record.summary["customer-onboarding"]
    assert preview.resolved.fingerprint
    assert set(preview.resolved.plans) == {"customer-onboarding"}
    spec = preview.project.spec_for("customer-onboarding")
    assert spec is not None and spec.metadata.version == "0.1.1"
    # ...but the stored project is untouched.
    stored = await compiler.load_project(project.project_id)
    assert stored.model_dump(mode="json") == before
    assert stored.edit_log == []


async def test_preview_then_confirm_applies_without_llm() -> None:
    # The queue holds exactly one EditPlan: the preview consumes it, so a
    # confirm that re-interpreted would fail on the exhausted queue. Confirm
    # must replay the stored plan instead.
    provider = MockProvider(structured=[*_front_end_queue(), _happy_plan()])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    preview = await compiler.preview_edit(project.project_id, _EDIT_DOC)
    confirmed = await compiler.edit_specs(
        project.project_id, _EDIT_DOC, resolved=preview.resolved
    )

    assert len(confirmed.edit_log) == 1
    assert confirmed.edit_log[0].summary == preview.record.summary
    assert confirmed.edit_log[0].resolved_patches == preview.record.resolved_patches
    spec = confirmed.spec_for("customer-onboarding")
    assert spec is not None and spec.metadata.version == "0.1.1"
    # The audit trail has exactly the previewed edit, applied once.
    stored = await compiler.load_project(project.project_id)
    assert len(stored.edit_log) == 1


async def test_confirm_with_stale_fingerprint_raises() -> None:
    provider = MockProvider(structured=[*_front_end_queue(), _happy_plan()])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)

    preview = await compiler.preview_edit(project.project_id, _EDIT_DOC)
    # Any project change after the preview invalidates it. (Windows' clock ticks
    # every ~15 ms, so a touch in the same tick as the preview would not move
    # ``updated_at``; wait one tick so the test exercises staleness, not the clock.)
    await asyncio.sleep(0.03)
    stored = await compiler.load_project(project.project_id)
    stored.touch()
    await compiler.save_project(stored)
    before = (await compiler.load_project(project.project_id)).model_dump(mode="json")

    with pytest.raises(EditPreviewStaleError):
        await compiler.edit_specs(
            project.project_id, _EDIT_DOC, resolved=preview.resolved
        )
    unchanged = await compiler.load_project(project.project_id)
    assert unchanged.model_dump(mode="json") == before


async def test_confirm_with_mismatched_sections_raises() -> None:
    provider = MockProvider(structured=[*_front_end_queue(), _happy_plan()])
    compiler = _compiler(provider)
    project = await compiler.compile_document(_DOCUMENT)
    preview = await compiler.preview_edit(project.project_id, _EDIT_DOC)

    # Same fingerprint, but the plan set no longer matches the document.
    tampered = preview.resolved.model_copy(update={"plans": {}})
    with pytest.raises(EditPreviewStaleError):
        await compiler.edit_specs(project.project_id, _EDIT_DOC, resolved=tampered)
    stored = await compiler.load_project(project.project_id)
    assert stored.edit_log == []

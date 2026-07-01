"""Tests for the deterministic ideal-format renderer + master assemble/split."""

from __future__ import annotations

from workflow_compiler.authoring import assemble_master, render_ideal_section, split_master
from workflow_compiler.authoring.split import slugify
from workflow_compiler.models import (
    ChecklistItem,
    ChecklistSeverity,
    ChecklistStatus,
    FactCategory,
    WorkflowChecklist,
    WorkflowFact,
    WorkflowFacts,
    WorkflowMetadata,
    WorkflowSegment,
    WorkflowState,
)
from workflow_compiler.models.structure import (
    ActivityNode,
    CompensationNode,
    DecisionNode,
    ExceptionNode,
    WorkflowStructure,
)


def _state() -> WorkflowState:
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate order"),
            ActivityNode(id="a2", name="Reserve inventory"),
            ActivityNode(id="a3", name="Notify customer", parallel_group="g1"),
            ActivityNode(id="a4", name="Record event", parallel_group="g1"),
        ],
        decisions=[
            DecisionNode(
                id="d1", question="Is the order settleable?", after="a1",
                yes_target="a2", no_target="x1",
            )
        ],
        exceptions=[ExceptionNode(id="x1", reason="OrderNotSettleable", raised_by="a1")],
        compensations=[CompensationNode(id="c1", name="Release inventory", compensates="a2")],
    )
    facts = WorkflowFacts(
        facts=[
            WorkflowFact(id="f1", statement="order_id — the order", category=FactCategory.INPUT),
            WorkflowFact(id="f2", statement="settlement_id", category=FactCategory.OUTPUT),
            WorkflowFact(id="f3", statement="Reserve within 5s", category=FactCategory.TIMER),
            WorkflowFact(id="f4", statement="Retry reserve 3x", category=FactCategory.RETRY),
            WorkflowFact(id="f5", statement="BR-1: only confirmed", category=FactCategory.RULE),
            WorkflowFact(id="f6", statement="POST /inventory/reserve", category=FactCategory.API),
        ],
        structure=structure,
    )
    md = WorkflowMetadata(
        name="Order Settlement",
        purpose="Settle a confirmed order.",
        actors=["Customer"],
        systems=["Payment Gateway"],
        trigger_events=["order.settle received"],
        domain="Commerce",
    )
    return WorkflowState(document_text="doc", workflow_metadata=md, workflow_facts=facts)


def test_render_has_all_sections_and_reuses_names() -> None:
    md = render_ideal_section(_state(), invokes=["Refund Settlement"])
    for heading in [
        "# Order Settlement",
        "## Metadata",
        "## Purpose",
        "## Trigger",
        "## Actors",
        "## Systems",
        "## Inputs and Outputs",
        "## Process",
        "## Business Rules",
        "## Timers and SLAs",
        "## API Interfaces",
        "## Exceptions and Error Handling",
        "## Retries",
        "## Compensation and Rollback",
    ]:
        assert heading in md, heading
    # Activity name reused verbatim across Process + Compensation.
    assert "**Reserve inventory**" in md
    assert "**Release inventory** compensates **Reserve inventory**." in md
    # Decision states both branches: no -> named exception.
    assert "raises **OrderNotSettleable** and ends" in md
    # Parallel activities folded into one step.
    assert "In parallel, **Notify customer**, **Record event**" in md
    # Invokes emits a child-workflow line.
    assert "invokes `Refund Settlement` as a child workflow" in md


def test_assemble_and_split_roundtrip() -> None:
    state = _state()
    seg = WorkflowSegment(id="w1", name="Order Settlement", invokes=["Refund Settlement"],
                          questions=["What currency?"])
    checklist = WorkflowChecklist(
        items=[
            ChecklistItem(
                id="R2-inputs", requirement="Declare inputs", category="io",
                severity=ChecklistSeverity.REQUIRED, status=ChecklistStatus.MISSING,
                question="What are the inputs?",
            )
        ]
    )
    section = render_ideal_section(state, invokes=seg.invokes)
    master = assemble_master(
        segments=[seg],
        sections={"w1": section},
        checklists={"w1": checklist},
        clarifications=["Which region?"],
    )
    # Master carries index + helper blocks.
    assert "## Workflows detected" in master
    assert "### Open questions" in master
    assert "### Readiness gaps" in master
    assert "R2-inputs" in master

    parts = split_master(master)
    assert len(parts) == 1
    slug, doc = parts[0]
    assert slug == "order_settlement"
    # Helper blocks stripped; ideal sections retained.
    assert "### Open questions" not in doc
    assert "### Readiness gaps" not in doc
    assert "## Workflows detected" not in doc
    assert doc.startswith("# Order Settlement")
    assert "## Compensation and Rollback" in doc


def test_slugify() -> None:
    assert slugify("Order Settlement") == "order_settlement"
    assert slugify("A/B  Test!") == "a_b_test"


def test_split_two_workflows() -> None:
    master = "preamble\n\n# One\n\n## Purpose\n\na\n\n# Two\n\n## Purpose\n\nb\n"
    parts = split_master(master)
    assert [slug for slug, _ in parts] == ["one", "two"]

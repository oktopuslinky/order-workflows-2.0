"""Unit tests for the spec projection layer and its guards.

Covers the load-bearing invariants: render→ingest round-trip identity,
provenance-aware ingestion of human edits, the validator's human-provenance
guard, referential integrity after ingestion, and the segmentation applier.
"""

from __future__ import annotations

from workflow_compiler.agents.review_pipeline import rebuild_facts
from workflow_compiler.agents.segmentation import (
    DiscoveredDependency,
    DiscoveredWorkflow,
    SegmentationPatchApplier,
    WorkflowsDiscovery,
    WorkflowSegmentationAgent,
    slugify,
)
from workflow_compiler.models import (
    ActivityNode,
    CompensationNode,
    CrossReference,
    DecisionNode,
    EventNode,
    ExceptionNode,
    FactCategory,
    Patch,
    PatchAction,
    Provenance,
    SpecItem,
    TransitionEdge,
    WorkflowFact,
    WorkflowMetadata,
    WorkflowSpec,
    WorkflowStructure,
)
from workflow_compiler.spec import ingest_spec_markdown, render_spec
from workflow_compiler.spec.validator import SpecPatchApplier

_DOC = (
    "Validate the order. Reserve inventory. Notify customer. Is the order settleable? "
    "OrderNotSettleable. Release inventory. order.settle received. order_id. "
    "Inventory must be reserved before payment. confirmed becomes settled when finalised."
)


def _full_spec() -> WorkflowSpec:
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate the order"),
            ActivityNode(id="a2", name="Reserve inventory"),
            ActivityNode(id="a3", name="Notify customer", parallel_group="g1"),
        ],
        decisions=[
            DecisionNode(
                id="d1", question="Is the order settleable?",
                after="a1", yes_target="a2", no_target="e1",
            )
        ],
        exceptions=[ExceptionNode(id="e1", reason="OrderNotSettleable", raised_by="a1")],
        compensations=[CompensationNode(id="c1", name="Release inventory", compensates="a2")],
        events=[EventNode(id="v1", name="order.settle received", emitted_by="a1")],
        transitions=[TransitionEdge(source="confirmed", target="settled", trigger="finalised")],
    )
    scalar = [
        WorkflowFact(id="input-1", statement="order_id",
                     category=FactCategory.INPUT, confidence=0.6),
        WorkflowFact(id="rule-1", statement="Inventory must be reserved before payment",
                     category=FactCategory.RULE, confidence=0.6),
    ]
    return WorkflowSpec(
        slug="order-settlement",
        metadata=WorkflowMetadata(
            name="Order Settlement",
            purpose="Settle a confirmed order",
            actors=["Customer"],
            systems=["Payment Gateway"],
            trigger_events=["order confirmed"],
            end_states=["settled"],
        ),
        facts=rebuild_facts(structure, scalar),
        assumptions=[SpecItem(text="Currency is always USD",
                              provenance=Provenance.LLM_INFERRED)],
        open_questions=[SpecItem(text="What are the workflow inputs?", ref="R2-inputs")],
    )


def _refs() -> list[CrossReference]:
    return [
        CrossReference(
            source_workflow="order-settlement",
            output_field="settlement_id",
            target_workflow="reporting",
            input_field="settlement_id",
        )
    ]


class TestRoundTrip:
    def test_render_then_ingest_is_identity(self) -> None:
        spec, refs = _full_spec(), _refs()
        markdown = render_spec(spec, refs)
        result = ingest_spec_markdown(spec, markdown, _DOC, refs)
        assert result.spec == spec
        assert result.cross_references == refs
        assert result.changes == []
        assert result.warnings == []

    def test_round_trip_preserves_unrendered_fields(self) -> None:
        spec, refs = _full_spec(), _refs()
        original_confidences = [f.confidence for f in spec.facts.facts]
        result = ingest_spec_markdown(spec, render_spec(spec, refs), _DOC, refs)
        assert [f.confidence for f in result.spec.facts.facts] == original_confidences


class TestHumanEdits:
    def test_new_ungrounded_entity_is_human_provided(self) -> None:
        spec, refs = _full_spec(), _refs()
        markdown = render_spec(spec, refs).replace(
            "- [a3] Notify customer",
            "- [a3] Notify customer\n- Send quarterly compliance report",
        )
        result = ingest_spec_markdown(spec, markdown, _DOC, refs)
        added = next(
            a for a in result.spec.facts.structure.activities
            if a.name == "Send quarterly compliance report"
        )
        assert result.spec.provenance_of(f"activity:{added.id}") is Provenance.HUMAN_PROVIDED

    def test_new_grounded_entity_is_document_grounded(self) -> None:
        spec, refs = _full_spec(), _refs()
        markdown = render_spec(spec, refs).replace(
            "- [a3] Notify customer",
            "- [a3] Notify customer\n- Reserve inventory before payment",
        )
        result = ingest_spec_markdown(spec, markdown, _DOC, refs)
        added = next(
            a for a in result.spec.facts.structure.activities
            if a.name == "Reserve inventory before payment"
        )
        assert result.spec.provenance_of(f"activity:{added.id}") is Provenance.DOCUMENT_GROUNDED

    def test_dangling_relation_in_edit_is_dropped(self) -> None:
        spec, refs = _full_spec(), _refs()
        markdown = render_spec(spec, refs).replace(
            "- [e1] OrderNotSettleable — raised by: a1",
            "- [e1] OrderNotSettleable — raised by: a99",
        )
        result = ingest_spec_markdown(spec, markdown, _DOC, refs)
        exception = result.spec.facts.structure.exceptions[0]
        assert exception.raised_by is None  # referential integrity re-enforced
        assert any("a99" in w for w in result.warnings)

    def test_answering_question_marks_resolved(self) -> None:
        spec, refs = _full_spec(), _refs()
        markdown = render_spec(spec, refs).replace(
            "  Answer: ", "  Answer: order_id and customer_id", 1
        )
        result = ingest_spec_markdown(spec, markdown, _DOC, refs)
        question = result.spec.open_questions[0]
        assert question.resolved and question.answer == "order_id and customer_id"

    def test_removing_entity_line_removes_it(self) -> None:
        spec, refs = _full_spec(), _refs()
        markdown = render_spec(spec, refs).replace(
            "- [c1] Release inventory — compensates: a2\n", ""
        )
        result = ingest_spec_markdown(spec, markdown, _DOC, refs)
        assert result.spec.facts.structure.compensations == []
        assert any("removed compensation c1" in c for c in result.changes)


class TestValidatorApplier:
    def test_remove_of_human_element_becomes_finding(self) -> None:
        structure = WorkflowStructure(
            activities=[
                ActivityNode(id="a1", name="Validate order"),
                ActivityNode(id="a2", name="Send gift basket"),
            ]
        )
        spec = WorkflowSpec(
            slug="s",
            metadata=WorkflowMetadata(name="X"),
            facts=rebuild_facts(structure, []),
            provenance={"activity:a2": Provenance.HUMAN_PROVIDED},
        )
        applier = SpecPatchApplier()
        patches = [
            Patch(action=PatchAction.REMOVE, target="activity:a2"),
            Patch(action=PatchAction.REMOVE, target="activity:a1"),
        ]
        new_spec, findings, _summary = applier.apply(spec, patches, "irrelevant")
        remaining = [a.id for a in new_spec.facts.structure.activities]
        assert remaining == ["a2"]  # human element survives; machine one removed
        assert any("human-provided" in f for f in findings)

    def test_question_add_deduplicates(self) -> None:
        spec = WorkflowSpec(slug="s", metadata=WorkflowMetadata(name="X"))
        applier = SpecPatchApplier()
        patch = Patch(
            action=PatchAction.ADD, target="question", payload={"text": "What triggers it?"}
        )
        spec, _, _ = applier.apply(spec, [patch, patch], "doc")
        assert len(spec.open_questions) == 1


class TestSegmentation:
    def test_slugify(self) -> None:
        assert slugify("Customer On-boarding!") == "customer-on-boarding"
        assert slugify("  ") == "workflow"

    def test_applier_merge_repoints_dependencies(self) -> None:
        discovery = WorkflowsDiscovery(
            workflows=[
                DiscoveredWorkflow(name="Onboarding", section_titles=["A"]),
                DiscoveredWorkflow(name="Customer Onboarding", section_titles=["B"]),
                DiscoveredWorkflow(name="Provisioning"),
            ],
            dependencies=[
                DiscoveredDependency(
                    source_workflow="Customer Onboarding",
                    output_field="id",
                    target_workflow="Provisioning",
                    input_field="id",
                )
            ],
        )
        applier = SegmentationPatchApplier()
        merged, _ = applier.apply(
            discovery,
            [Patch(action=PatchAction.MERGE, target="workflow:Onboarding+Customer Onboarding")],
            "Onboarding Provisioning",
        )
        assert [w.name for w in merged.workflows] == ["Onboarding", "Provisioning"]
        assert merged.workflows[0].section_titles == ["A", "B"]
        assert merged.dependencies[0].source_workflow == "Onboarding"

    def test_applier_drops_ungrounded_add(self) -> None:
        discovery = WorkflowsDiscovery(workflows=[DiscoveredWorkflow(name="Onboarding")])
        applier = SegmentationPatchApplier()
        result, summary = applier.apply(
            discovery,
            [Patch(action=PatchAction.ADD, target="workflow",
                   payload={"name": "Imaginary Flow"})],
            "This document only describes onboarding.",
        )
        assert [w.name for w in result.workflows] == ["Onboarding"]
        assert "1 dropped" in summary

    def test_single_workflow_gets_full_document(self) -> None:
        agent = WorkflowSegmentationAgent(llm=None)
        discovery = WorkflowsDiscovery(workflows=[DiscoveredWorkflow(name="Only One")])
        segments, refs, warnings = agent.assemble(discovery, "full document text")
        assert len(segments) == 1
        assert segments[0].text == "full document text"
        assert refs == [] and warnings == []

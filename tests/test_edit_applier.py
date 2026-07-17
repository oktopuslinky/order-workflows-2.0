"""Tests for the human-authority edit applier (spec/edit_applier.py).

The edit path applies human-authored patches without document grounding and
honors removals the review path refuses; the review path's behavior must stay
byte-identical (regression tests at the bottom).
"""

from __future__ import annotations

from workflow_compiler.agents.review_pipeline import rebuild_facts
from workflow_compiler.models import (
    ActivityNode,
    CompensationNode,
    DecisionNode,
    Evidence,
    ExceptionNode,
    FactCategory,
    Patch,
    PatchAction,
    Provenance,
    WorkflowFact,
    WorkflowMetadata,
    WorkflowSpec,
    WorkflowStructure,
)
from workflow_compiler.spec import EditPatchApplier
from workflow_compiler.spec.validator import SpecPatchApplier

_DOC = (
    "Validate the order. Reserve inventory. Is the order settleable? "
    "OrderNotSettleable. Release inventory. order_id. "
    "Inventory must be reserved before payment."
)


def _spec() -> WorkflowSpec:
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate the order"),
            ActivityNode(id="a2", name="Reserve inventory"),
        ],
        decisions=[
            DecisionNode(
                id="d1", question="Is the order settleable?",
                after="a1", yes_target="a2", no_target="e1",
            )
        ],
        exceptions=[ExceptionNode(id="e1", reason="OrderNotSettleable", raised_by="a1")],
        compensations=[CompensationNode(id="c1", name="Release inventory", compensates="a2")],
    )
    scalar = [
        WorkflowFact(id="input-1", statement="order_id",
                     category=FactCategory.INPUT, confidence=0.6),
        WorkflowFact(id="rule-1", statement="Inventory must be reserved before payment",
                     category=FactCategory.RULE, confidence=0.6),
    ]
    return WorkflowSpec(
        slug="order",
        metadata=WorkflowMetadata(name="Order", purpose="Settle an order"),
        facts=rebuild_facts(structure, scalar),
    )


class TestEditPatchApplier:
    def test_ungrounded_add_applies_and_is_human_provided(self) -> None:
        spec = _spec()
        patch = Patch(
            action=PatchAction.ADD,
            target="activity",
            payload={"name": "Send SMS alert to fraud team"},
            evidence=Evidence(quote="Add an SMS alert activity"),
        )
        new_spec, summary, warnings = EditPatchApplier().apply(spec, [patch], _DOC)

        structure = new_spec.facts.structure
        assert structure is not None
        added = next(a for a in structure.activities
                     if a.name == "Send SMS alert to fraud team")
        assert new_spec.provenance_of(f"activity:{added.id}") is Provenance.HUMAN_PROVIDED
        assert not warnings
        assert any("add activity" in line for line in summary)
        # Purity: the input spec is untouched.
        assert all(a.name != "Send SMS alert to fraud team"
                   for a in (spec.facts.structure.activities if spec.facts.structure else []))

    def test_remove_of_human_provided_element_applies(self) -> None:
        spec = _spec()
        spec.provenance["rule:inventory must be reserved before payment"] = (
            Provenance.HUMAN_PROVIDED
        )
        patch = Patch(
            action=PatchAction.REMOVE,
            target="rule",
            payload={"value": "Inventory must be reserved before payment"},
        )
        new_spec, _summary, warnings = EditPatchApplier().apply(spec, [patch], _DOC)

        assert all(f.category is not FactCategory.RULE for f in new_spec.facts.facts)
        assert "rule:inventory must be reserved before payment" not in new_spec.provenance
        assert not warnings

    def test_remove_of_referenced_activity_applies_with_warning(self) -> None:
        spec = _spec()
        # a2 is referenced by d1.yes_target and c1.compensates.
        patch = Patch(action=PatchAction.REMOVE, target="activity:a2")
        new_spec, _summary, warnings = EditPatchApplier().apply(spec, [patch], _DOC)

        structure = new_spec.facts.structure
        assert structure is not None
        assert all(a.id != "a2" for a in structure.activities)
        # Dangling references were pruned by the integrity guard.
        assert structure.decisions[0].yes_target != "a2"
        assert all(c.compensates != "a2" for c in structure.compensations)
        assert any("pruned" in w for w in warnings)

    def test_scalar_modify_marks_new_statement_human(self) -> None:
        spec = _spec()
        patch = Patch(
            action=PatchAction.MODIFY,
            target="rule",
            payload={"old": "Inventory must be reserved before payment",
                     "new": "Inventory must be reserved before any payment attempt"},
        )
        new_spec, _summary, _warnings = EditPatchApplier().apply(spec, [patch], _DOC)
        key = "rule:inventory must be reserved before any payment attempt"
        assert new_spec.provenance_of(key) is Provenance.HUMAN_PROVIDED

    def test_metadata_add_without_grounding(self) -> None:
        spec = _spec()
        patch = Patch(
            action=PatchAction.ADD, target="actors", payload={"value": "Fraud Analyst"}
        )
        new_spec, _summary, _warnings = EditPatchApplier().apply(spec, [patch], _DOC)
        assert "Fraud Analyst" in new_spec.metadata.actors
        assert new_spec.provenance_of("actors:Fraud Analyst") is Provenance.HUMAN_PROVIDED


class TestReviewModeRegression:
    """The default (review) applier must be unaffected by the edit mode."""

    def test_default_applier_drops_ungrounded_add(self) -> None:
        spec = _spec()
        patch = Patch(
            action=PatchAction.ADD,
            target="activity",
            payload={"name": "Completely unsupported hallucination"},
        )
        new_spec, findings, _note = SpecPatchApplier().apply(spec, [patch], _DOC)
        structure = new_spec.facts.structure
        assert structure is not None
        assert all("hallucination" not in a.name.lower() for a in structure.activities)
        assert not findings  # a dropped add is silent, exactly as before

    def test_default_applier_refuses_human_remove(self) -> None:
        spec = _spec()
        spec.provenance["activity:a1"] = Provenance.HUMAN_PROVIDED
        patch = Patch(action=PatchAction.REMOVE, target="activity:a1")
        new_spec, findings, _note = SpecPatchApplier().apply(spec, [patch], _DOC)
        structure = new_spec.facts.structure
        assert structure is not None
        assert any(a.id == "a1" for a in structure.activities)
        assert any("human-provided" in f for f in findings)

    def test_default_applier_refuses_referenced_remove(self) -> None:
        spec = _spec()
        patch = Patch(action=PatchAction.REMOVE, target="activity:a2")
        new_spec, findings, _note = SpecPatchApplier().apply(spec, [patch], _DOC)
        structure = new_spec.facts.structure
        assert structure is not None
        assert any(a.id == "a2" for a in structure.activities)
        assert any("referenced by other elements" in f for f in findings)

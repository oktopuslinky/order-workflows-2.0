"""Tests for the domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from workflow_compiler.models import (
    ApprovalStatus,
    CompilationProject,
    CompilationStage,
    CVPAPhase,
    Severity,
    SpecFinding,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    WorkflowState,
)
from workflow_compiler.models.user import User, UserPreferences


def test_workflow_state_defaults(fresh_state: WorkflowState) -> None:
    assert fresh_state.document_text
    assert fresh_state.workflow_id
    assert fresh_state.approval_status is ApprovalStatus.PENDING
    assert fresh_state.stage is CompilationStage.INGESTED
    # All artifact fields start empty.
    assert fresh_state.workflow_metadata is None
    assert fresh_state.workflow_facts is None
    assert fresh_state.workflow_graph is None
    assert fresh_state.review_report is None
    assert fresh_state.cvpa_classification is None
    assert fresh_state.temporal_design is None
    assert fresh_state.mermaid_diagram is None
    assert fresh_state.confidence_scores is None


def test_workflow_state_requires_document_text() -> None:
    with pytest.raises(ValidationError):
        WorkflowState()  # type: ignore[call-arg]


def test_workflow_state_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        WorkflowState(document_text="x", bogus="nope")  # type: ignore[call-arg]


def test_touch_updates_timestamp(fresh_state: WorkflowState) -> None:
    before = fresh_state.updated_at
    fresh_state.touch()
    assert fresh_state.updated_at >= before


def test_graph_unique_node_ids() -> None:
    nodes = [
        WorkflowNode(id="a", label="A"),
        WorkflowNode(id="a", label="A duplicate"),
    ]
    with pytest.raises(ValidationError):
        WorkflowGraph(nodes=nodes)


def test_graph_node_ids_property() -> None:
    graph = WorkflowGraph(
        nodes=[WorkflowNode(id="a", label="A"), WorkflowNode(id="b", label="B")],
        edges=[WorkflowEdge(id="e1", source="a", target="b")],
    )
    assert graph.node_ids == {"a", "b"}


def test_node_default_cvpa_phase_unclassified() -> None:
    node = WorkflowNode(id="n", label="N")
    assert node.cvpa_phase is CVPAPhase.UNCLASSIFIED


def test_state_round_trip_serialization(fresh_state: WorkflowState) -> None:
    dumped = fresh_state.model_dump_json()
    restored = WorkflowState.model_validate_json(dumped)
    assert restored.workflow_id == fresh_state.workflow_id
    assert restored.document_text == fresh_state.document_text


def test_spec_finding_coerces_legacy_string() -> None:
    # Projects saved before SpecFinding existed stored findings as flat strings.
    finding = SpecFinding.model_validate("grounding: actors: Customer is not listed")
    assert finding.severity is Severity.WARNING
    assert finding.message == "grounding: actors: Customer is not listed"
    assert finding.section is None


def test_spec_finding_legacy_severity_mapping() -> None:
    blocked = SpecFinding.model_validate(
        "blocked: unmet required checklist items ['R5-compensations']"
    )
    assert blocked.severity is Severity.BLOCKING
    health = SpecFinding.model_validate(
        "graph health 0.65 below threshold 0.90 — left pending for manual review"
    )
    assert health.severity is Severity.BLOCKING
    ingest = SpecFinding.model_validate("ingest: added event v1 '[ev1] checkout.submitted'")
    assert ingest.severity is Severity.INFO


def test_project_loads_legacy_string_findings() -> None:
    project = CompilationProject.model_validate(
        {
            "document_text": "doc",
            "validation_findings": {
                "demo-order-workflow": [
                    "consistency: metadata:version: 1.0",
                    "blocked: unmet required checklist items ['R5-compensations']",
                ]
            },
        }
    )
    findings = project.validation_findings["demo-order-workflow"]
    assert all(isinstance(f, SpecFinding) for f in findings)
    assert project.has_blocking_findings()
    assert project.findings_as_strings()["demo-order-workflow"][0].startswith("[WARN]")
    # Re-serialising writes structured objects: the migration is one-way.
    restored = CompilationProject.model_validate_json(project.model_dump_json())
    assert restored.validation_findings["demo-order-workflow"][1].severity is Severity.BLOCKING


def test_project_nickname_defaults_none_and_round_trips() -> None:
    project = CompilationProject(document_text="doc")
    assert project.nickname is None
    project.nickname = "Orders pipeline"
    restored = CompilationProject.model_validate_json(project.model_dump_json())
    assert restored.nickname == "Orders pipeline"
    # Legacy project JSON without the field still loads (defaults to None).
    legacy = CompilationProject.model_validate({"document_text": "doc"})
    assert legacy.nickname is None


def test_user_preferences_defaults_and_bounds() -> None:
    user = User(
        email="a@example.com",
        display_name="A",
        password_hash="h",
        password_salt="s",
    )
    # Defaults: no overrides, page size 10.
    assert user.preferences.baseline_hours == {}
    assert user.preferences.projects_page_size == 10
    # Page size is bounded.
    with pytest.raises(ValidationError):
        UserPreferences(projects_page_size=0)
    # Legacy user JSON without preferences still loads.
    legacy = User.model_validate(
        {"email": "b@example.com", "display_name": "B", "password_hash": "h", "password_salt": "s"}
    )
    assert legacy.preferences.projects_page_size == 10

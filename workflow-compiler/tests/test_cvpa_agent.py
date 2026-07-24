"""Unit tests for CVPAClassifierAgent."""

from __future__ import annotations

import pytest

from workflow_compiler.agents import CVPAClassifierAgent, CVPAOutput
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    CompilationStage,
    CVPAPhase,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    WorkflowState,
)


def _graph() -> WorkflowGraph:
    return WorkflowGraph(
        nodes=[
            WorkflowNode(id="start", label="Start", node_type=NodeType.START),
            WorkflowNode(id="check", label="Valid?", node_type=NodeType.DECISION),
            WorkflowNode(id="work", label="Process order", node_type=NodeType.TASK),
            WorkflowNode(id="end", label="Done", node_type=NodeType.END),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="check"),
            WorkflowEdge(id="e2", source="check", target="work"),
            WorkflowEdge(id="e3", source="work", target="end"),
        ],
    )


def _state() -> WorkflowState:
    state = WorkflowState(document_text="doc")
    state.workflow_graph = _graph()
    return state


def _full_output() -> CVPAOutput:
    return CVPAOutput.model_validate(
        {
            "assignments": [
                {"node_id": "start", "phase": "capture", "rationale": "intake", "confidence": 0.9},
                {"node_id": "check", "phase": "validate", "rationale": "gate", "confidence": 0.8},
                {"node_id": "work", "phase": "process", "rationale": "core", "confidence": 0.85},
                {"node_id": "end", "phase": "activate", "rationale": "done", "confidence": 0.7},
            ]
        }
    )


async def test_classifies_every_node_exactly_once() -> None:
    provider = MockProvider(structured=[_full_output()])
    state = await CVPAClassifierAgent(provider).run(_state())

    cvpa = state.cvpa_classification
    assert cvpa is not None
    assigned_ids = [a.node_id for a in cvpa.assignments]
    assert sorted(assigned_ids) == ["check", "end", "start", "work"]
    assert len(assigned_ids) == len(set(assigned_ids))  # exactly one each
    assert all(a.phase in set(CVPAPhase) for a in cvpa.assignments)
    assert state.stage is CompilationStage.CLASSIFIED
    assert state.confidence_scores is not None
    assert state.confidence_scores.cvpa is not None


async def test_every_assignment_has_rationale_and_confidence() -> None:
    provider = MockProvider(structured=[_full_output()])
    state = await CVPAClassifierAgent(provider).run(_state())
    for assignment in state.cvpa_classification.assignments:
        assert assignment.rationale
        assert 0.0 <= assignment.confidence <= 1.0


async def test_missing_node_filled_by_fallback() -> None:
    partial = CVPAOutput.model_validate(
        {"assignments": [{"node_id": "work", "phase": "process", "confidence": 0.9}]}
    )
    provider = MockProvider(structured=[partial])
    state = await CVPAClassifierAgent(provider).run(_state())

    by_id = {a.node_id: a for a in state.cvpa_classification.assignments}
    assert set(by_id) == {"start", "check", "work", "end"}
    # Fallback uses structural heuristic by node type.
    assert by_id["start"].phase is CVPAPhase.CAPTURE
    assert by_id["check"].phase is CVPAPhase.VALIDATE
    assert by_id["end"].phase is CVPAPhase.ACTIVATE
    assert "Fallback" in (by_id["start"].rationale or "")


async def test_unknown_node_and_bad_phase_are_ignored() -> None:
    noisy = CVPAOutput.model_validate(
        {
            "assignments": [
                {"node_id": "ghost", "phase": "capture", "confidence": 1.0},
                {"node_id": "work", "phase": "nonsense", "confidence": 1.0},
            ]
        }
    )
    provider = MockProvider(structured=[noisy])
    state = await CVPAClassifierAgent(provider).run(_state())

    by_id = {a.node_id: a for a in state.cvpa_classification.assignments}
    assert "ghost" not in by_id
    # "work" had an invalid phase -> fell back to PROCESS heuristic.
    assert by_id["work"].phase is CVPAPhase.PROCESS


async def test_duplicate_assignment_keeps_highest_confidence() -> None:
    dupes = CVPAOutput.model_validate(
        {
            "assignments": [
                {"node_id": "work", "phase": "capture", "confidence": 0.4},
                {"node_id": "work", "phase": "process", "confidence": 0.95},
            ]
        }
    )
    provider = MockProvider(structured=[dupes])
    state = await CVPAClassifierAgent(provider).run(_state())
    work = next(a for a in state.cvpa_classification.assignments if a.node_id == "work")
    assert work.phase is CVPAPhase.PROCESS


async def test_phase_summaries_cover_all_four_phases() -> None:
    provider = MockProvider(structured=[_full_output()])
    state = await CVPAClassifierAgent(provider).run(_state())
    phases = {s.phase for s in state.cvpa_classification.phase_summaries}
    assert phases == {
        CVPAPhase.CAPTURE,
        CVPAPhase.VALIDATE,
        CVPAPhase.PROCESS,
        CVPAPhase.ACTIVATE,
    }


async def test_diagram_is_color_coded_by_phase() -> None:
    state = _state()
    state.mermaid_diagram = None  # ensure the agent (re)produces it
    provider = MockProvider(structured=[_full_output()])
    state = await CVPAClassifierAgent(provider).run(state)

    source = state.mermaid_diagram.source
    # A classDef and class assignment exist for each phase present.
    for phase in ("capture", "validate", "process", "activate"):
        assert f"classDef {phase} " in source
        assert f" {phase};" in source
    # The decision node is grouped under validate, the task under process.
    assert "class check validate;" in source
    assert "class work process;" in source
    # Still a valid flowchart.
    assert source.startswith("flowchart TD")


async def test_requires_graph() -> None:
    provider = MockProvider(structured=[_full_output()])
    with pytest.raises(CompilationError):
        await CVPAClassifierAgent(provider).run(WorkflowState(document_text="doc"))


async def test_requires_llm() -> None:
    with pytest.raises(CompilationError):
        await CVPAClassifierAgent(None).run(_state())

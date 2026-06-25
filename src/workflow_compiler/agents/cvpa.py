"""CVPAClassifierAgent: assign every graph node to a CVPA phase.

The LLM proposes phase assignments; the agent then *reconciles* them
deterministically so the output always satisfies the core invariant: every node
is assigned to exactly one of Capture / Validate / Process / Activate. Nodes the
model misses or returns ambiguously fall back to a structural heuristic with
reduced confidence.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.agents.serialization import graph_to_text
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.graph.mermaid import to_mermaid_with_cvpa
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    CompilationStage,
    ConfidenceScores,
    CVPAClassification,
    CVPANodeAssignment,
    CVPAPhase,
    CVPAPhaseSummary,
    NodeType,
    WorkflowGraph,
    WorkflowState,
)
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "classify_cvpa"
_SYSTEM = (
    "You are a precise business-process classifier. Assign every node to exactly "
    "one CVPA phase and respond with strict JSON."
)

#: The four real phases a node may end up in (UNCLASSIFIED is never a final state).
_PHASES = (CVPAPhase.CAPTURE, CVPAPhase.VALIDATE, CVPAPhase.PROCESS, CVPAPhase.ACTIVATE)

#: Structural fallback phase by node type, used when the LLM omits a node.
_FALLBACK_BY_TYPE: dict[NodeType, CVPAPhase] = {
    NodeType.START: CVPAPhase.CAPTURE,
    NodeType.EVENT: CVPAPhase.CAPTURE,
    NodeType.DECISION: CVPAPhase.VALIDATE,
    NodeType.GATEWAY: CVPAPhase.VALIDATE,
    NodeType.TASK: CVPAPhase.PROCESS,
    NodeType.SUBPROCESS: CVPAPhase.PROCESS,
    NodeType.TIMER: CVPAPhase.PROCESS,
    NodeType.END: CVPAPhase.ACTIVATE,
    NodeType.SIGNAL: CVPAPhase.ACTIVATE,
}
#: Confidence assigned to a heuristic fallback assignment.
_FALLBACK_CONFIDENCE = 0.3


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _parse_phase(raw: str) -> CVPAPhase | None:
    """Parse a model-supplied phase string, returning ``None`` if unrecognized."""
    try:
        phase = CVPAPhase(raw.strip().lower())
    except ValueError:
        return None
    return phase if phase in _PHASES else None


class _CVPAAssignmentOut(BaseModel):
    """One model-proposed node assignment (permissive)."""

    model_config = ConfigDict(extra="ignore")

    node_id: str = Field(default="")
    phase: str = Field(default="")
    rationale: str = Field(default="")
    confidence: float = Field(default=0.5)


class CVPAOutput(BaseModel):
    """Structured LLM output for CVPA classification."""

    model_config = ConfigDict(extra="ignore")

    assignments: list[_CVPAAssignmentOut] = Field(default_factory=list)


class CVPAClassifierAgent(BaseAgent):
    """Classify every node of ``state.workflow_graph`` into a CVPA phase.

    Depends only on :class:`BaseLLMProvider`. The LLM result is reconciled so the
    final :class:`CVPAClassification` covers every node exactly once.
    """

    name = "cvpa-classifier"

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Store the LLM provider and an optional prompt manager."""
        super().__init__(llm)
        self._prompts = prompt_manager or PromptManager()

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Classify nodes, reconcile coverage, score, and update ``state``."""
        if self._llm is None:
            raise CompilationError("CVPAClassifierAgent requires an LLM provider.")
        if state.workflow_graph is None:
            raise CompilationError("CVPAClassifierAgent requires a built workflow_graph.")
        if not state.workflow_graph.nodes:
            raise CompilationError("Cannot classify a workflow_graph with no nodes.")

        prompt = self._prompts.render(
            _PROMPT_NAME, workflow_graph=graph_to_text(state.workflow_graph)
        )
        result = await self._llm.structured(prompt, CVPAOutput, system=_SYSTEM)

        classification, llm_covered = self._reconcile(result, state.workflow_graph)
        confidence = self._score(classification, llm_covered)

        state.cvpa_classification = classification
        # Re-render the Mermaid diagram with nodes color-coded by CVPA phase.
        title = state.workflow_metadata.name if state.workflow_metadata else None
        state.mermaid_diagram = to_mermaid_with_cvpa(
            state.workflow_graph, classification, title=title
        )
        scores = state.confidence_scores or ConfidenceScores()
        notes = {
            **scores.notes,
            "cvpa": (
                f"{len(classification.assignments)} nodes classified; "
                f"{llm_covered} from model, "
                f"{len(classification.assignments) - llm_covered} by fallback."
            ),
        }
        state.confidence_scores = scores.model_copy(update={"cvpa": confidence, "notes": notes})
        state.stage = CompilationStage.CLASSIFIED
        state.touch()
        return state

    # -- internals ----------------------------------------------------------

    def _reconcile(
        self, result: CVPAOutput, graph: WorkflowGraph
    ) -> tuple[CVPAClassification, int]:
        """Map the LLM output onto the graph, guaranteeing exactly-one coverage.

        Returns the reconciled classification and the number of nodes that were
        covered by a valid model assignment (vs. heuristic fallback).
        """
        node_ids = [node.id for node in graph.nodes]
        valid_ids = set(node_ids)

        # Keep the highest-confidence valid assignment per node id from the LLM.
        chosen: dict[str, CVPANodeAssignment] = {}
        for item in result.assignments:
            node_id = item.node_id.strip()
            phase = _parse_phase(item.phase)
            if node_id not in valid_ids or phase is None:
                continue
            confidence = _clamp(item.confidence)
            existing = chosen.get(node_id)
            if existing is None or confidence > existing.confidence:
                chosen[node_id] = CVPANodeAssignment(
                    node_id=node_id,
                    phase=phase,
                    rationale=item.rationale.strip() or None,
                    confidence=confidence,
                )

        llm_covered = len(chosen)

        # Fill any uncovered nodes with a structural fallback.
        assignments: list[CVPANodeAssignment] = []
        for node in graph.nodes:
            if node.id in chosen:
                assignments.append(chosen[node.id])
                continue
            phase = _FALLBACK_BY_TYPE.get(node.node_type, CVPAPhase.PROCESS)
            assignments.append(
                CVPANodeAssignment(
                    node_id=node.id,
                    phase=phase,
                    rationale=f"Fallback by node type ({node.node_type.value}).",
                    confidence=_FALLBACK_CONFIDENCE,
                )
            )

        summaries = self._summarize(assignments)
        return CVPAClassification(assignments=assignments, phase_summaries=summaries), llm_covered

    @staticmethod
    def _summarize(assignments: list[CVPANodeAssignment]) -> list[CVPAPhaseSummary]:
        """Build a per-phase summary (one entry per phase, in canonical order)."""
        summaries: list[CVPAPhaseSummary] = []
        for phase in _PHASES:
            ids = [a.node_id for a in assignments if a.phase == phase]
            summaries.append(
                CVPAPhaseSummary(
                    phase=phase,
                    node_ids=ids,
                    summary=f"{len(ids)} node(s) in the {phase.value} phase.",
                )
            )
        return summaries

    @staticmethod
    def _score(classification: CVPAClassification, llm_covered: int) -> float:
        """Blend mean per-node confidence with the model's coverage fraction."""
        assignments = classification.assignments
        if not assignments:
            return 0.0
        mean_conf = sum(a.confidence for a in assignments) / len(assignments)
        coverage = llm_covered / len(assignments)
        return round(_clamp(0.5 * mean_conf + 0.5 * coverage), 4)

"""GraphBuilderAgent: build a WorkflowGraph + Mermaid diagram deterministically.

This agent does **not** use an LLM. It infers workflow structure from the
categorized :class:`WorkflowFacts` using :class:`WorkflowGraphBuilder` (NetworkX)
and renders a Mermaid diagram, then updates the :class:`WorkflowState`.
"""

from __future__ import annotations

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.graph.builder import WorkflowGraphBuilder
from workflow_compiler.graph.mermaid import to_mermaid
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.models import (
    CompilationStage,
    ConfidenceScores,
    FactCategory,
    WorkflowFacts,
    WorkflowState,
)

#: Structural fact categories that contribute to the graph confidence score.
_STRUCTURAL = (
    FactCategory.ACTIVITY,
    FactCategory.DECISION,
    FactCategory.EVENT,
    FactCategory.STATE_TRANSITION,
    FactCategory.EXCEPTION,
)


class GraphBuilderAgent(BaseAgent):
    """Construct a canonical workflow graph and Mermaid diagram from facts."""

    name = "graph-builder"

    def __init__(self, *, builder: WorkflowGraphBuilder | None = None) -> None:
        """Graph building is deterministic, so no LLM provider is required."""
        super().__init__(None)
        self._builder = builder or WorkflowGraphBuilder()

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Build the graph + diagram and update ``state`` in place."""
        if state.workflow_facts is None:
            raise CompilationError("GraphBuilderAgent requires extracted workflow_facts.")

        structure = state.workflow_facts.structure
        if structure is not None and not structure.is_empty():
            # Relational extraction available: wire edges from explicit links.
            graph, _nx = self._builder.build_from_structure(structure)
        else:
            # Legacy flat facts: fall back to positional inference.
            graph, _nx = self._builder.build(state.workflow_facts)
        diagram = to_mermaid(
            graph,
            title=state.workflow_metadata.name if state.workflow_metadata else None,
        )
        confidence = self._score(state.workflow_facts)

        state.workflow_graph = graph
        state.mermaid_diagram = diagram
        scores = state.confidence_scores or ConfidenceScores()
        state.confidence_scores = scores.model_copy(update={"graph": confidence})
        state.stage = CompilationStage.GRAPH_BUILT
        state.touch()
        return state

    @staticmethod
    def _score(facts: WorkflowFacts) -> float:
        """Deterministic confidence from the breadth of structural signals."""
        present = {fact.category for fact in facts.facts}
        has_backbone = bool(
            present & {FactCategory.ACTIVITY, FactCategory.STATE_TRANSITION}
        )
        if not has_backbone:
            return 0.0
        ratio = sum(1 for category in _STRUCTURAL if category in present) / len(_STRUCTURAL)
        return round(0.5 + 0.5 * ratio, 4)

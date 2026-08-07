"""TemporalCodeGeneratorAgent: render runnable Temporal code from the design.

This agent is **deterministic** — like :class:`GraphBuilderAgent`, it uses no
LLM. It consumes the :class:`TemporalWorkflowDesign` produced upstream (and the
:class:`WorkflowGraph` for control-flow ordering) and mechanically renders a
:class:`TemporalCodeBundle` of Temporal Python SDK source files. The design
remains specification-only; the executable code is a separate artifact.
"""

from __future__ import annotations

from workflow_compiler.codegen.temporal import TemporalPythonCodeGenerator
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.models import (
    CompilationStage,
    ConfidenceScores,
    WorkflowState,
)


class TemporalCodeGeneratorAgent(BaseAgent):
    """Render the Temporal design into an executable code bundle."""

    name = "temporal-code-generator"

    def __init__(self, *, generator: TemporalPythonCodeGenerator | None = None) -> None:
        """Code generation is deterministic, so no LLM provider is required."""
        super().__init__(None)
        self._generator = generator or TemporalPythonCodeGenerator()

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Generate the Temporal code bundle and update ``state`` in place."""
        if state.temporal_design is None:
            raise CompilationError(
                "TemporalCodeGeneratorAgent requires a temporal_design."
            )

        bundle = self._generator.generate(state.temporal_design, graph=state.workflow_graph)

        state.temporal_code = bundle
        scores = state.confidence_scores or ConfidenceScores()
        notes = {
            **scores.notes,
            "temporal_code": (
                f"{len(bundle.files)} files for package '{bundle.package_name}'."
            ),
        }
        state.confidence_scores = scores.model_copy(update={"notes": notes})
        state.stage = CompilationStage.CODE_GENERATED
        state.touch()
        return state

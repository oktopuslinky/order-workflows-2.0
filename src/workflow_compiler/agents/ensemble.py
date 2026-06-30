"""``ConsensusMergeAgent``: run an LLM agent N times and merge the candidates.

This wraps an existing single-responsibility agent (discovery or fact
extraction). It runs N temperature-diversified copies concurrently, then combines
their proposed *parts* via a per-stage merger (see :mod:`ensemble_merge`) rather
than picking one winner. Candidates run under a per-candidate timeout and an
overall budget; a slow or failing candidate is simply excluded from the merge —
the run only fails if *every* candidate fails.

The merge is reference-free (votes + referential integrity + evidence grounding),
so it raises grounding/consistency, not certified truth; the human approval gate
remains the oracle.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from workflow_compiler.agents.ensemble_merge import (
    MergeProvenance,
    ground_scores,
    local_grounder,
    merge_facts,
    merge_metadata,
)
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.llm.ensemble_provider import TemperatureProvider
from workflow_compiler.models import ConfidenceScores, WorkflowState

_DEFAULT_PER_CANDIDATE_TIMEOUT = 300.0
_DEFAULT_OVERALL_TIMEOUT = 480.0


@dataclass(frozen=True)
class StageSpec:
    """Per-stage hooks that adapt a generic merge to a concrete artifact."""

    note_key: str
    extract: Callable[[WorkflowState], object | None]
    texts: Callable[[object], list[str]]
    merge: Callable[..., tuple[object, MergeProvenance]]
    apply: Callable[[WorkflowState, object], None]


class ConsensusMergeAgent(BaseAgent):
    """Run an inner agent N times at varied temperatures and merge the results."""

    def __init__(
        self,
        *,
        inner_factory: Callable[[BaseLLMProvider], BaseAgent],
        provider: BaseLLMProvider,
        temperatures: list[float],
        spec: StageSpec,
        name: str | None = None,
        per_candidate_timeout: float = _DEFAULT_PER_CANDIDATE_TIMEOUT,
        overall_timeout: float = _DEFAULT_OVERALL_TIMEOUT,
    ) -> None:
        """Configure the ensemble around an inner-agent factory and merger."""
        super().__init__(provider)
        if not temperatures:
            raise ValueError("ConsensusMergeAgent requires at least one temperature.")
        self._inner_factory = inner_factory
        self._provider = provider
        self._temperatures = temperatures
        self._spec = spec
        self._per_candidate_timeout = per_candidate_timeout
        self._overall_timeout = overall_timeout
        self.name = name or f"consensus-merge:{spec.note_key}"

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Produce N candidates, merge them, and return the merged state."""
        survivors = await self._gather(state)
        artifacts = [a for s in survivors if (a := self._spec.extract(s)) is not None]
        if not artifacts:
            raise CompilationError(
                f"{self.name}: all {len(self._temperatures)} ensemble candidates failed."
            )

        ground = await self._build_grounder(state, artifacts)
        merged, prov = self._spec.merge(
            artifacts, document_text=state.document_text, ground=ground
        )

        base = survivors[0]
        self._spec.apply(base, merged)
        scores = base.confidence_scores or ConfidenceScores()
        notes = {
            **scores.notes,
            self._spec.note_key: (
                f"ensemble of {len(self._temperatures)} "
                f"({len(artifacts)} survived): {prov.summary()}"
            ),
        }
        base.confidence_scores = scores.model_copy(update={"notes": notes})
        base.touch()
        return base

    # -- internals ----------------------------------------------------------

    async def _run_one(self, state: WorkflowState, temperature: float) -> WorkflowState:
        provider = TemperatureProvider(self._provider, temperature=temperature)
        agent = self._inner_factory(provider)
        candidate = state.model_copy(deep=True)
        return await asyncio.wait_for(
            agent.run(candidate), timeout=self._per_candidate_timeout
        )

    async def _gather(self, state: WorkflowState) -> list[WorkflowState]:
        tasks = [
            asyncio.create_task(self._run_one(state, t)) for t in self._temperatures
        ]
        done, pending = await asyncio.wait(tasks, timeout=self._overall_timeout)
        for task in pending:
            task.cancel()
        survivors: list[WorkflowState] = []
        for task in tasks:
            if task in done and not task.cancelled() and task.exception() is None:
                survivors.append(task.result())
        return survivors

    async def _build_grounder(
        self, state: WorkflowState, artifacts: list[object]
    ) -> Callable[[str], float]:
        """Precompute grounding (embeddings best-effort), local fallback for misses."""
        texts: list[str] = []
        seen: set[str] = set()
        for artifact in artifacts:
            for text in self._spec.texts(artifact):
                if text and text not in seen:
                    seen.add(text)
                    texts.append(text)
        embed = getattr(self._provider, "embed", None)
        ground_map = await ground_scores(texts, state.document_text, embed)
        local = local_grounder(state.document_text)

        def ground(text: str) -> float:
            return ground_map.get(text, local(text))

        return ground


# --- per-stage specs --------------------------------------------------------


def _facts_texts(artifact: object) -> list[str]:
    from workflow_compiler.models import WorkflowFacts

    assert isinstance(artifact, WorkflowFacts)
    texts = [f.statement for f in artifact.facts]
    if artifact.structure is not None:
        s = artifact.structure
        texts += [a.name for a in s.activities]
        texts += [d.question for d in s.decisions]
        texts += [x.reason for x in s.exceptions]
        texts += [c.name for c in s.compensations]
        texts += [v.name for v in s.events]
    return texts


def _facts_apply(state: WorkflowState, merged: object) -> None:
    from workflow_compiler.models import WorkflowFacts

    assert isinstance(merged, WorkflowFacts)
    state.workflow_facts = merged


def _metadata_texts(artifact: object) -> list[str]:
    from workflow_compiler.models import WorkflowMetadata

    assert isinstance(artifact, WorkflowMetadata)
    return [
        *artifact.actors,
        *artifact.systems,
        *artifact.trigger_events,
        *artifact.start_states,
        *artifact.end_states,
    ]


def _metadata_apply(state: WorkflowState, merged: object) -> None:
    from workflow_compiler.models import WorkflowMetadata

    assert isinstance(merged, WorkflowMetadata)
    state.workflow_metadata = merged


FACTS_SPEC = StageSpec(
    note_key="facts_ensemble",
    extract=lambda s: s.workflow_facts,
    texts=_facts_texts,
    merge=merge_facts,
    apply=_facts_apply,
)

DISCOVERY_SPEC = StageSpec(
    note_key="metadata_ensemble",
    extract=lambda s: s.workflow_metadata,
    texts=_metadata_texts,
    merge=merge_metadata,
    apply=_metadata_apply,
)

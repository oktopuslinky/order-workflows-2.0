"""Tests for the consensus-merge ensemble: diversity, merging, and resilience.

Covers the three new pieces:
1. ``TemperatureProvider`` forwards calls and injects its temperature.
2. ``merge_structures`` / ``merge_metadata`` apply *majority backbone + flagged
   singletons* with reference-free grounding.
3. ``ConsensusMergeAgent`` runs N candidates, tolerates failures, and merges.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from workflow_compiler.agents.ensemble import DISCOVERY_SPEC, ConsensusMergeAgent
from workflow_compiler.agents.ensemble_merge import (
    ground_scores,
    merge_metadata,
    merge_structures,
)
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.llm import MockProvider, TemperatureProvider
from workflow_compiler.models import (
    ActivityNode,
    ExceptionNode,
    WorkflowMetadata,
    WorkflowState,
    WorkflowStructure,
)

# --- TemperatureProvider ----------------------------------------------------


class _Recorder(BaseLLMProvider):
    name = "recorder"

    def __init__(self) -> None:
        self.temps: list[float] = []

    async def complete(self, prompt, *, system=None, temperature=0.0, max_tokens=None):
        self.temps.append(temperature)
        return "x"

    async def structured(self, prompt, schema, *, system=None, temperature=0.0):
        self.temps.append(temperature)
        return schema()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


async def test_temperature_provider_injects_temperature() -> None:
    rec = _Recorder()
    provider = TemperatureProvider(rec, temperature=0.7)

    class _Schema(BaseModel):
        x: int = 0

    await provider.complete("p")
    await provider.structured("p", _Schema)
    assert rec.temps == [0.7, 0.7]
    assert provider.temperature == 0.7


# --- grounding --------------------------------------------------------------


async def test_grounding_falls_back_when_embeddings_unavailable() -> None:
    async def bad_embed(texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    scores = await ground_scores(
        ["Pre-authorise charge", "zzz unrelated"],
        "We pre-authorise charge here.",
        bad_embed,
    )
    assert scores["Pre-authorise charge"] > scores["zzz unrelated"]


# --- merge_structures -------------------------------------------------------


def _struct(
    act_names: list[tuple[str, str]], exc: tuple[str, str, str] | None
) -> WorkflowStructure:
    activities = [ActivityNode(id=i, name=n) for i, n in act_names]
    exceptions = (
        [ExceptionNode(id=exc[0], reason=exc[1], raised_by=exc[2])] if exc else []
    )
    return WorkflowStructure(activities=activities, exceptions=exceptions)


async def test_merge_structures_votes_and_grounds() -> None:
    document = "Pre-authorise the charge. If declined, reject. Send confirmation."
    candidates = [
        _struct([("a1", "Pre-authorise charge"), ("a2", "Send confirmation")],
                ("e1", "DECLINED", "a1")),
        _struct([("x1", "Pre-authorise charge"), ("x2", "Send confirmation")],
                ("x9", "DECLINED", "x1")),
        # third candidate hallucinates "Verify age" (not in the document) and
        # mis-attributes the exception to it.
        _struct([("p1", "Pre-authorise charge"), ("p2", "Verify age")],
                ("p9", "DECLINED", "p2")),
    ]
    merged, prov = merge_structures(candidates, document_text=document)

    names = {a.name for a in merged.activities}
    assert "Pre-authorise charge" in names  # 3 votes
    assert "Send confirmation" in names  # 2 votes
    assert "Verify age" not in names  # 1 vote, ungrounded -> dropped
    assert any("Verify age" in d for d in prov.dropped_singletons)

    # The exception survives; majority resolves raised_by to the pre-auth activity.
    assert len(merged.exceptions) == 1
    preauth = next(a.id for a in merged.activities if a.name == "Pre-authorise charge")
    assert merged.exceptions[0].raised_by == preauth


async def test_merge_metadata_vote_thresholded_union() -> None:
    candidates = [
        WorkflowMetadata(name="Upgrade", actors=["Customer", "Warehouse"], systems=["Pay"]),
        WorkflowMetadata(name="Upgrade", actors=["Customer", "Warehouse"], systems=["Pay"]),
        WorkflowMetadata(name="Upgrade", actors=["Customer"], systems=["Pay"]),
    ]
    merged, _prov = merge_metadata(candidates, document_text="customer warehouse pay")
    assert merged.name == "Upgrade"
    assert set(merged.actors) == {"Customer", "Warehouse"}  # both >= 2 votes
    assert merged.systems == ["Pay"]


# --- ConsensusMergeAgent ----------------------------------------------------


class _FakeDiscovery(BaseAgent):
    """Inner agent that emits temperature-dependent metadata, optionally failing."""

    def __init__(self, provider: BaseLLMProvider, *, fail_above: float | None = None) -> None:
        super().__init__(provider)
        self._fail_above = fail_above

    async def run(self, state: WorkflowState) -> WorkflowState:
        temp = getattr(self._llm, "temperature", 0.0)
        if self._fail_above is not None and temp > self._fail_above:
            raise CompilationError("candidate failed")
        actors = ["Customer", "Warehouse"] if temp < 0.6 else ["Customer"]
        state.workflow_metadata = WorkflowMetadata(name="W", actors=actors, systems=["Pay"])
        return state


def _agent(fail_above: float | None = None) -> ConsensusMergeAgent:
    return ConsensusMergeAgent(
        inner_factory=lambda p: _FakeDiscovery(p, fail_above=fail_above),
        provider=MockProvider(),
        temperatures=[0.2, 0.5, 0.8],
        spec=DISCOVERY_SPEC,
    )


async def test_consensus_agent_merges_candidates() -> None:
    state = WorkflowState(document_text="Customer and warehouse handle pay.")
    result = await _agent().run(state)
    assert set(result.workflow_metadata.actors) == {"Customer", "Warehouse"}
    assert "metadata_ensemble" in result.confidence_scores.notes


async def test_consensus_agent_tolerates_a_failing_candidate() -> None:
    state = WorkflowState(document_text="Customer and warehouse handle pay.")
    # The 0.8 candidate fails; the two survivors still merge.
    result = await _agent(fail_above=0.7).run(state)
    assert set(result.workflow_metadata.actors) == {"Customer", "Warehouse"}


async def test_consensus_agent_raises_when_all_candidates_fail() -> None:
    state = WorkflowState(document_text="doc")
    with pytest.raises(CompilationError):
        await _agent(fail_above=0.0).run(state)

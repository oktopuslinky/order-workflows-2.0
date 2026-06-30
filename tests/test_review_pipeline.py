"""Tests for the sequential review pipeline framework.

Covers the deterministic patch appliers (the heart of the framework), the
end-to-end :class:`ReviewPipelineAgent`, idempotency, and the compiler's
ensemble > review > plain precedence.
"""

from __future__ import annotations

from workflow_compiler import WorkflowCompiler
from workflow_compiler.agents import (
    ConsensusMergeAgent,
    FactsPatchApplier,
    MetadataPatchApplier,
    ReviewPipelineAgent,
    WorkflowDiscovery,
    WorkflowDiscoveryAgent,
    rebuild_facts,
)
from workflow_compiler.agents.review_pipeline import METADATA_REVIEW_SPEC
from workflow_compiler.compiler import EnsembleConfig, ReviewConfig
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    ActivityNode,
    CompensationNode,
    Evidence,
    FactCategory,
    Patch,
    PatchAction,
    ReviewResult,
    WorkflowFacts,
    WorkflowMetadata,
    WorkflowState,
    WorkflowStructure,
)

_DOC = (
    "The customer submits an order. The payment gateway authorizes the charge. "
    "The warehouse validates payment, processes the order, and ships the order. "
    "If the payment is declined, the order is cancelled. Release inventory on failure. "
    "A timeout error can occur while contacting the gateway."
)


# --------------------------------------------------------------------------- #
# MetadataPatchApplier
# --------------------------------------------------------------------------- #


def test_metadata_add_is_grounded_and_deduped() -> None:
    applier = MetadataPatchApplier()
    md = WorkflowMetadata(name="Orders", actors=["Customer"], systems=[])

    patches = [
        # grounded → added
        Patch(
            action=PatchAction.ADD,
            target="systems",
            payload={"value": "Payment Gateway"},
            evidence=Evidence(quote="the payment gateway authorizes the charge"),
        ),
        # duplicate (case-insensitive) → dropped
        Patch(action=PatchAction.ADD, target="actors", payload={"value": "customer"}),
        # ungrounded → dropped
        Patch(action=PatchAction.ADD, target="actors", payload={"value": "Auditor"}),
    ]
    out, summary = applier.apply(md, patches, _DOC)

    assert out.systems == ["Payment Gateway"]
    assert out.actors == ["Customer"]
    assert "1 applied" in summary and "2 dropped" in summary


def test_metadata_review_is_idempotent() -> None:
    applier = MetadataPatchApplier()
    md = WorkflowMetadata(name="Orders", systems=["Payment Gateway"])
    add = Patch(
        action=PatchAction.ADD,
        target="systems",
        payload={"value": "Payment Gateway"},
        evidence=Evidence(quote="the payment gateway authorizes the charge"),
    )
    out, _ = applier.apply(md, [add], _DOC)
    assert out.systems == ["Payment Gateway"]  # no duplicate appended


def test_metadata_merge_collapses_equivalent_labels() -> None:
    applier = MetadataPatchApplier()
    md = WorkflowMetadata(name="Orders", systems=["OMS", "Order Management System"])
    merge = Patch(
        action=PatchAction.MERGE,
        target="systems",
        payload={"values": ["OMS", "Order Management System"], "into": "Order Management System"},
    )
    out, _ = applier.apply(md, [merge], _DOC)
    assert out.systems == ["Order Management System"]


# --------------------------------------------------------------------------- #
# FactsPatchApplier
# --------------------------------------------------------------------------- #


def _facts() -> WorkflowFacts:
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate payment"),
            ActivityNode(id="a2", name="Process order"),
        ]
    )
    return rebuild_facts(structure, [])


def test_facts_add_activity_grounded_and_dedup() -> None:
    applier = FactsPatchApplier()
    facts = _facts()
    patches = [
        Patch(
            action=PatchAction.ADD,
            target="activity",
            payload={"name": "Ship order"},
            evidence=Evidence(quote="ships the order"),
        ),
        # duplicate name → dropped
        Patch(action=PatchAction.ADD, target="activity", payload={"name": "validate payment"}),
    ]
    out, summary = applier.apply(facts, patches, _DOC)
    names = [a.name for a in out.structure.activities]
    assert names == ["Validate payment", "Process order", "Ship order"]
    assert "1 applied" in summary


def test_facts_add_with_dangling_relation_is_nulled_by_validation() -> None:
    applier = FactsPatchApplier()
    facts = _facts()
    patch = Patch(
        action=PatchAction.ADD,
        target="exception",
        payload={"reason": "Timeout error", "raised_by": "a99"},  # a99 does not exist
        evidence=Evidence(quote="a timeout error can occur"),
    )
    out, _ = applier.apply(facts, [patch], _DOC)
    exc = out.structure.exceptions
    assert len(exc) == 1
    assert exc[0].reason == "Timeout error"
    assert exc[0].raised_by is None  # dangling reference dropped by validated()


def test_facts_merge_repoints_references() -> None:
    applier = FactsPatchApplier()
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Process order"),
            ActivityNode(id="a2", name="Place order"),
        ],
        compensations=[CompensationNode(id="c1", name="Release inventory", compensates="a2")],
    )
    facts = rebuild_facts(structure, [])

    merge = Patch(action=PatchAction.MERGE, target="activity:a1+a2")
    out, _ = applier.apply(facts, [merge], _DOC)

    assert [a.id for a in out.structure.activities] == ["a1"]
    assert out.structure.compensations[0].compensates == "a1"

    # Idempotent: a2 is already gone → re-running merges nothing.
    again, summary = applier.apply(out, [merge], _DOC)
    assert [a.id for a in again.structure.activities] == ["a1"]
    assert "0 applied" in summary


def test_rebuild_facts_projects_flat_facts_from_structure() -> None:
    facts = _facts()
    activities = [f.statement for f in facts.facts if f.category == FactCategory.ACTIVITY]
    assert activities == ["Validate payment", "Process order"]


# --------------------------------------------------------------------------- #
# ReviewPipelineAgent (end to end with a MockProvider)
# --------------------------------------------------------------------------- #


def _discovery() -> WorkflowDiscovery:
    return WorkflowDiscovery(name="Orders", actors=["Customer"], systems=[], confidence=0.9)


async def test_review_pipeline_applies_then_settles() -> None:
    # discovery, then completeness adds a system, grounding + consistency no-op.
    provider = MockProvider(
        structured=[
            _discovery(),
            ReviewResult(
                patches=[
                    Patch(
                        action=PatchAction.ADD,
                        target="systems",
                        payload={"value": "Payment Gateway"},
                        evidence=Evidence(quote="the payment gateway authorizes the charge"),
                    )
                ]
            ),
            ReviewResult(patches=[Patch(action=PatchAction.NO_CHANGE)]),
            ReviewResult(patches=[]),
        ]
    )
    agent = ReviewPipelineAgent(
        inner_factory=lambda p: WorkflowDiscoveryAgent(p),
        provider=provider,
        spec=METADATA_REVIEW_SPEC,
    )
    state = WorkflowState(document_text=_DOC)
    out = await agent.run(state)

    assert out.workflow_metadata is not None
    assert out.workflow_metadata.systems == ["Payment Gateway"]
    assert "metadata_review" in out.confidence_scores.notes


async def test_review_pipeline_emits_nested_progress() -> None:
    provider = MockProvider(
        structured=[
            _discovery(),
            ReviewResult(patches=[]),
            ReviewResult(patches=[]),
            ReviewResult(patches=[]),
        ]
    )
    agent = ReviewPipelineAgent(
        inner_factory=lambda p: WorkflowDiscoveryAgent(p),
        provider=provider,
        spec=METADATA_REVIEW_SPEC,
    )
    events: list[tuple[str, str, int, int]] = []
    agent.set_progress(
        lambda name, status, index, total, **_: events.append((name, status, index, total))
    )
    await agent.run(WorkflowState(document_text=_DOC))

    started = [(n, i, t) for (n, s, i, t) in events if s == "start"]
    assert started == [
        ("generate", 1, 4),
        ("review:completeness", 2, 4),
        ("review:grounding", 3, 4),
        ("review:consistency", 4, 4),
    ]
    # every start has a matching done
    assert sum(1 for e in events if e[1] == "done") == 4


async def test_review_pipeline_no_change_leaves_artifact_intact() -> None:
    provider = MockProvider(
        structured=[
            _discovery(),
            ReviewResult(patches=[]),
            ReviewResult(patches=[]),
            ReviewResult(patches=[]),
        ]
    )
    agent = ReviewPipelineAgent(
        inner_factory=lambda p: WorkflowDiscoveryAgent(p),
        provider=provider,
        spec=METADATA_REVIEW_SPEC,
    )
    out = await agent.run(WorkflowState(document_text=_DOC))
    assert out.workflow_metadata.actors == ["Customer"]
    assert out.workflow_metadata.systems == []


# --------------------------------------------------------------------------- #
# Compiler precedence: ensemble > review > plain
# --------------------------------------------------------------------------- #


def _compiler(*, ensemble: bool, review: bool) -> WorkflowCompiler:
    return WorkflowCompiler(
        llm_provider=MockProvider(),
        ensemble=EnsembleConfig(enabled=ensemble),
        review=ReviewConfig(enabled=review),
    )


def test_precedence_ensemble_wins_when_both_enabled() -> None:
    discovery_agent = _compiler(ensemble=True, review=True)._agents[0]
    assert isinstance(discovery_agent, ConsensusMergeAgent)


def test_precedence_review_default_when_ensemble_off() -> None:
    discovery_agent = _compiler(ensemble=False, review=True)._agents[0]
    assert isinstance(discovery_agent, ReviewPipelineAgent)


def test_precedence_plain_when_both_off() -> None:
    discovery_agent = _compiler(ensemble=False, review=False)._agents[0]
    assert isinstance(discovery_agent, WorkflowDiscoveryAgent)

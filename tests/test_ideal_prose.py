"""Tests for the grounding-checked prose polish pass."""

from __future__ import annotations

import pytest

from workflow_compiler.agents.ideal_prose import (
    IdealProseAgent,
    IdealProseOutput,
    _ActivityProse,
)
from workflow_compiler.authoring import render_ideal_section
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import WorkflowFacts, WorkflowMetadata, WorkflowState
from workflow_compiler.models.structure import ActivityNode, WorkflowStructure

_SOURCE = (
    "The Settlement Service validates the order using order_id and returns whether it "
    "is settleable. The Inventory Service reserves inventory for the order."
)


def _state() -> WorkflowState:
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate order"),
            ActivityNode(id="a2", name="Reserve inventory"),
        ]
    )
    return WorkflowState(
        document_text=_SOURCE,
        workflow_metadata=WorkflowMetadata(name="Order Settlement"),
        workflow_facts=WorkflowFacts(structure=structure),
    )


@pytest.mark.asyncio
async def test_grounded_descriptions_kept_ungrounded_dropped() -> None:
    out = IdealProseOutput(
        activities=[
            _ActivityProse(
                name="Validate order",
                description="The Settlement Service validates the order using order_id.",
            ),
            # Ungrounded — invents an unrelated system not in the source.
            _ActivityProse(
                name="Reserve inventory",
                description="A quantum teleporter dispatches interstellar cargo drones.",
            ),
        ]
    )
    agent = IdealProseAgent(MockProvider(structured=[out]))

    descriptions = await agent.describe_activities(
        activity_names=["Validate order", "Reserve inventory"], source_text=_SOURCE
    )

    assert "Validate order" in descriptions
    assert "Reserve inventory" not in descriptions  # dropped as ungrounded


@pytest.mark.asyncio
async def test_no_activities_returns_empty() -> None:
    agent = IdealProseAgent(MockProvider(structured=[IdealProseOutput()]))
    assert await agent.describe_activities(activity_names=[], source_text=_SOURCE) == {}


def test_render_uses_descriptions_but_keeps_bold_name() -> None:
    md = render_ideal_section(
        _state(),
        descriptions={"Validate order": "the Settlement Service checks order_id."},
    )
    # Polished prose used, canonical name preserved verbatim in bold.
    assert "**Validate order** — the Settlement Service checks order_id." in md
    # Un-polished activity falls back to the deterministic wording.
    assert "The workflow performs **Reserve inventory**." in md

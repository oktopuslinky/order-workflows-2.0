"""Tests for WorkflowSegmenterAgent (document → workflows)."""

from __future__ import annotations

import pytest

from workflow_compiler.agents.segmenter import (
    DocumentSegmentation,
    WorkflowSegmenterAgent,
    _SegmentOut,
    canonical_name,
)
from workflow_compiler.llm.providers.mock import MockProvider


def test_canonical_name_normalizes() -> None:
    assert canonical_name("order cancellation") == "Order Cancellation"
    assert canonical_name("refund-settlement") == "Refund Settlement"
    assert canonical_name("OrderCancellation") == "OrderCancellation"


@pytest.mark.asyncio
async def test_segments_two_workflows_with_invokes_link() -> None:
    seg = DocumentSegmentation(
        segments=[
            _SegmentOut(
                id="w1",
                name="order cancellation",
                summary="Cancel an order.",
                text="When a customer cancels an order, validate it and start a refund.",
                invokes=["Refund Settlement"],
                questions=["What is the cancellation window?"],
            ),
            _SegmentOut(
                id="w2",
                name="refund settlement",
                summary="Settle a refund.",
                text="The refund is processed to the original payment method.",
                invokes=["Nonexistent Workflow"],
            ),
        ],
        clarifications=["Which currency applies?"],
    )
    provider = MockProvider(structured=[seg])
    agent = WorkflowSegmenterAgent(provider)

    segments, clarifications = await agent.segment("some multi-workflow document")

    assert [s.name for s in segments] == ["Order Cancellation", "Refund Settlement"]
    assert segments[0].source_text.startswith("When a customer cancels")
    # Invokes resolves to a known workflow name; unknown links are dropped.
    assert segments[0].invokes == ["Refund Settlement"]
    assert segments[1].invokes == []
    assert segments[0].questions == ["What is the cancellation window?"]
    assert clarifications == ["Which currency applies?"]


@pytest.mark.asyncio
async def test_empty_result_falls_back_to_single_workflow() -> None:
    provider = MockProvider(structured=[DocumentSegmentation(segments=[])])
    agent = WorkflowSegmenterAgent(provider)

    segments, _ = await agent.segment("a single workflow document")

    assert len(segments) == 1
    assert segments[0].source_text == "a single workflow document"


@pytest.mark.asyncio
async def test_empty_document_raises() -> None:
    from workflow_compiler.exceptions import CompilationError

    agent = WorkflowSegmenterAgent(MockProvider())
    with pytest.raises(CompilationError):
        await agent.segment("   ")

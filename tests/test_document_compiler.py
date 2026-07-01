"""End-to-end tests for the multi-workflow DocumentCompiler front-end."""

from __future__ import annotations

from typing import Any

import pytest

from workflow_compiler.agents import (
    CVPAOutput,
    FactExtraction,
    TemporalDesignOutput,
    WorkflowDiscovery,
)
from workflow_compiler.agents.segmenter import (
    DocumentSegmentation,
    WorkflowSegmenterAgent,
    _SegmentOut,
)
from workflow_compiler.compiler import ReviewConfig, WorkflowCompiler
from workflow_compiler.document_compiler import DocumentCompiler
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import CompilationStage
from workflow_compiler.storage import DocumentStore, InMemoryStateStore

_NO_REVIEW = ReviewConfig(enabled=False)


def _segmentation() -> DocumentSegmentation:
    return DocumentSegmentation(
        segments=[
            _SegmentOut(
                id="w1",
                name="Order Cancellation",
                summary="Cancel an order.",
                text="When a customer cancels an order, validate and start a refund.",
                invokes=["Refund Settlement"],
                questions=["What is the cancellation window?"],
            ),
            _SegmentOut(
                id="w2",
                name="Refund Settlement",
                summary="Settle a refund.",
                text="The refund is processed to the original payment method.",
            ),
        ],
        clarifications=["Which currency applies?"],
    )


def _discovery() -> WorkflowDiscovery:
    return WorkflowDiscovery(
        name="Order Cancellation",
        purpose="Cancel an order and refund.",
        actors=["Customer"],
        systems=["Payment Gateway"],
        trigger_events=["cancellation.requested received"],
        confidence=0.9,
    )


def _facts() -> FactExtraction:
    return FactExtraction.model_validate(
        {
            "inputs": ["order_id", "customer_id"],
            "outputs": ["refund_id"],
            "activity_nodes": [
                {"id": "a1", "name": "Validate cancellation"},
                {"id": "a2", "name": "Reserve refund"},
            ],
            "decision_nodes": [
                {
                    "id": "d1",
                    "question": "Is the order cancellable?",
                    "after": "a1",
                    "yes_target": "a2",
                    "no_target": "x1",
                }
            ],
            "exception_nodes": [{"id": "x1", "reason": "NotCancellable", "raised_by": "a1"}],
            "compensation_nodes": [
                {"id": "c1", "name": "Release refund", "compensates": "a2"}
            ],
            "confidence": 0.9,
        }
    )


def _cvpa() -> CVPAOutput:
    return CVPAOutput.model_validate(
        {"assignments": [{"node_id": "start", "phase": "capture", "confidence": 0.9}]}
    )


def _temporal() -> TemporalDesignOutput:
    return TemporalDesignOutput.model_validate(
        {
            "workflow_name": "Order Cancellation",
            "task_queue": "cancel",
            "activities": [{"name": "validate cancellation"}, {"name": "reserve refund"}],
            "child_workflows": [{"name": "Refund Settlement"}],
            "confidence": 0.9,
        }
    )


class _TypedMock(MockProvider):
    """A MockProvider that dispatches structured responses by schema type.

    This makes the ``asyncio.gather`` extraction in ``author_document`` order
    independent — each schema always gets its own canned response.
    """

    def __init__(self) -> None:
        super().__init__()
        self._by_schema = {
            DocumentSegmentation: _segmentation,
            WorkflowDiscovery: _discovery,
            FactExtraction: _facts,
            CVPAOutput: _cvpa,
            TemporalDesignOutput: _temporal,
        }

    async def structured(  # type: ignore[override]
        self, prompt: str, schema: type, *, system: Any = None, temperature: float = 0.0
    ):
        self.calls.append(("structured", prompt))
        factory = self._by_schema.get(schema)
        if factory is None:
            raise AssertionError(f"no canned response for {schema.__name__}")
        return factory()


def _document_compiler(tmp_path) -> DocumentCompiler:  # type: ignore[no-untyped-def]
    provider = _TypedMock()
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    return DocumentCompiler(
        compiler=inner,
        segmenter=WorkflowSegmenterAgent(provider),
        document_store=DocumentStore(tmp_path),
    )


@pytest.mark.asyncio
async def test_author_produces_master_with_two_workflows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dc = _document_compiler(tmp_path)
    doc = await dc.author_document("a messy two-workflow document", persist=False)

    assert [s.name for s in doc.segments] == ["Order Cancellation", "Refund Settlement"]
    master = doc.master_document or ""
    assert "# Order Cancellation" in master
    assert "# Refund Settlement" in master
    assert "invokes `Refund Settlement` as a child workflow" in master
    assert "## Workflows detected" in master
    assert "What is the cancellation window?" in master  # open question surfaced


@pytest.mark.asyncio
async def test_compile_authored_fans_out_to_completed_workflows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dc = _document_compiler(tmp_path)
    doc = await dc.author_document("a messy two-workflow document", persist=False)

    compilation, results = await dc.compile_authored(
        doc.master_document or "", auto_approve=True, persist=False
    )

    assert [slug for slug, _ in results] == ["order_cancellation", "refund_settlement"]
    for _slug, state in results:
        assert state.stage is CompilationStage.COMPLETED
        assert state.temporal_code is not None
    # The invoking workflow modelled the other as a child workflow.
    invoker = results[0][1]
    assert invoker.temporal_design is not None
    child_names = [c.name for c in invoker.temporal_design.child_workflows]
    assert any("Refund" in name for name in child_names)
    assert len(compilation.workflow_ids) == 2

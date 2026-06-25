"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from workflow_compiler.models import WorkflowState


@pytest.fixture
def sample_document() -> str:
    """A minimal business workflow document for tests."""
    return (
        "When a customer submits an order, validate the payment details, "
        "process the order, and notify the warehouse to activate fulfillment."
    )


@pytest.fixture
def fresh_state(sample_document: str) -> WorkflowState:
    """A freshly ingested workflow state holding only the document text."""
    return WorkflowState(document_text=sample_document)

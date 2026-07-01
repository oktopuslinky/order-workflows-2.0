"""Tests for the master-document parser and the reauthor round."""

from __future__ import annotations

import pytest

from tests.test_document_compiler import _document_compiler  # reuse harness
from workflow_compiler.authoring import assemble_master, parse_master, render_ideal_section
from workflow_compiler.authoring.split import split_master
from workflow_compiler.document_compiler import DocumentCompiler
from workflow_compiler.models import WorkflowSegment, WorkflowState


def _master() -> str:
    seg = WorkflowSegment(id="w1", name="Order Cancellation", invokes=["Refund Settlement"])
    section = render_ideal_section(
        WorkflowState(document_text="x"), name="Order Cancellation", invokes=seg.invokes
    )
    return assemble_master(
        segments=[seg],
        sections={"w1": section},
        checklists={"w1": None},
        clarifications=[],
        global_notes="- I also saw a Chargeback flow.",
        guidance={"w1": "- Treat cancellation as idempotent."},
        open_questions={"w1": ["What is the cancellation window?"]},
    )


def test_parse_master_extracts_notes_guidance_and_invokes() -> None:
    parsed = parse_master(_master())
    assert "Chargeback" in parsed.global_notes
    assert len(parsed.workflows) == 1
    wf = parsed.workflows[0]
    assert wf.name == "Order Cancellation"
    assert wf.slug == "order_cancellation"
    assert wf.guidance == "- Treat cancellation as idempotent."
    assert wf.open_questions == ["What is the cancellation window?"]
    assert wf.invokes == ["Refund Settlement"]
    # Ideal content keeps the workflow body but not the helper blocks.
    assert wf.ideal_content.startswith("# Order Cancellation")
    assert "### Guidance" not in wf.ideal_content
    assert "### Open questions" not in wf.ideal_content


def test_master_notes_and_guidance_are_stripped_on_compile_split() -> None:
    parts = split_master(_master())
    assert len(parts) == 1
    _slug, doc = parts[0]
    assert "Notes to the compiler" not in doc
    assert "### Guidance" not in doc
    assert "idempotent" not in doc  # guidance never reaches the compiled doc


@pytest.mark.asyncio
async def test_reauthor_preserves_notes_and_regenerates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dc: DocumentCompiler = _document_compiler(tmp_path)
    doc = await dc.author_document("a messy two-workflow document", persist=False)

    # Simulate a human edit: drop notes into the master document.
    edited = (doc.master_document or "").replace(
        "_(no notes yet)_", "- Cancellation must be idempotent."
    )
    refined = await dc.reauthor(edited, persist=False)

    master = refined.master_document or ""
    # The global note survives the round-trip.
    assert "Cancellation must be idempotent." in master
    # Both workflows are still present after re-authoring.
    assert "# Order Cancellation" in master
    assert "# Refund Settlement" in master
    assert "## Notes to the compiler" in master

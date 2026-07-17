"""Tests for the deterministic edit-request parser (spec/edit_ingest.py)."""

from __future__ import annotations

import pytest

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.spec.edit_ingest import parse_edit_request

_SLUGS = {"order", "shipping"}

_HAPPY = """\
# Edit Request

## Project

- Rename the project owner to Order Platform Team.

## Workflow: order

### Add

- After "Release inventory", the system notifies the warehouse team
  via the Notification Service.
- A business rule: refunds over $500 require manager approval.

### Modify

- "Deprovision service" retry count changes from 3 to 5.

### Remove

- The manager-approval step for orders above $1,000.

### Triggers

- Add a trigger: order starts shipping when payment is settled.

## Workflow: shipping

### Modify

- The delivery SLA changes from 5 days to 3 days.

## Add Workflow: returns

# Returns Workflow

## Purpose

Handle customer returns end to end.

## Remove Workflow: shipping-legacy

## Reason

Ops request OPS-142, June policy update.
"""


def test_happy_multi_workflow_doc() -> None:
    doc = parse_edit_request(_HAPPY, _SLUGS | {"shipping-legacy"})
    assert [w.slug for w in doc.workflows] == ["order", "shipping"]
    order = doc.workflows[0]
    assert len(order.blocks["Add"]) == 2
    assert "notifies the warehouse team via the Notification Service." in order.blocks["Add"][0]
    assert order.blocks["Modify"] == ['"Deprovision service" retry count changes from 3 to 5.']
    assert order.blocks["Triggers"] == [
        "Add a trigger: order starts shipping when payment is settled."
    ]
    assert doc.workflows[1].blocks["Modify"]
    assert doc.project_bullets == ["Rename the project owner to Order Platform Team."]
    assert [s.slug for s in doc.add_workflows] == ["returns"]
    assert "Handle customer returns" in doc.add_workflows[0].body
    assert doc.remove_workflows == ["shipping-legacy"]
    assert doc.reason == "Ops request OPS-142, June policy update."


def test_missing_h1_fails() -> None:
    with pytest.raises(CompilationError, match="# Edit Request"):
        parse_edit_request("## Workflow: order\n### Add\n- x\n", _SLUGS)


def test_unknown_slug_lists_valid_ones() -> None:
    doc = "# Edit Request\n\n## Workflow: nope\n\n### Add\n- x\n"
    with pytest.raises(CompilationError, match=r"Unknown workflow slug 'nope'.*order.*shipping"):
        parse_edit_request(doc, _SLUGS)


def test_unknown_change_block_fails() -> None:
    doc = "# Edit Request\n\n## Workflow: order\n\n### Rewrite\n- x\n"
    with pytest.raises(CompilationError, match="Unknown change block"):
        parse_edit_request(doc, _SLUGS)


def test_duplicate_workflow_section_fails() -> None:
    doc = (
        "# Edit Request\n\n## Workflow: order\n\n### Add\n- x\n\n"
        "## Workflow: order\n\n### Remove\n- y\n"
    )
    with pytest.raises(CompilationError, match="Duplicate '## Workflow: order'"):
        parse_edit_request(doc, _SLUGS)


def test_add_workflow_slug_collision_fails() -> None:
    doc = "# Edit Request\n\n## Add Workflow: order\n\nSome body.\n"
    with pytest.raises(CompilationError, match="already exists"):
        parse_edit_request(doc, _SLUGS)


def test_add_workflow_empty_body_fails() -> None:
    doc = "# Edit Request\n\n## Add Workflow: returns\n"
    with pytest.raises(CompilationError, match="empty body"):
        parse_edit_request(doc, _SLUGS)


def test_remove_unknown_workflow_fails() -> None:
    doc = "# Edit Request\n\n## Remove Workflow: ghost\n"
    with pytest.raises(CompilationError, match="no such slug"):
        parse_edit_request(doc, _SLUGS)


def test_split_merge_syntax_is_reserved() -> None:
    for heading in ("## Split Workflow: order", "## Merge Workflows: order + shipping"):
        doc = f"# Edit Request\n\n{heading}\n\n- details\n"
        with pytest.raises(CompilationError, match="reserved for a future release"):
            parse_edit_request(doc, _SLUGS)


def test_edit_and_remove_same_workflow_conflicts() -> None:
    doc = (
        "# Edit Request\n\n## Workflow: order\n\n### Add\n- x\n\n"
        "## Remove Workflow: order\n"
    )
    with pytest.raises(CompilationError, match="both edited and removed"):
        parse_edit_request(doc, _SLUGS)


def test_empty_request_fails() -> None:
    doc = "# Edit Request\n\n## Workflow: order\n\n### Add\n\n## Reason\n\nBecause.\n"
    with pytest.raises(CompilationError, match="contains no changes"):
        parse_edit_request(doc, _SLUGS)


def test_unrecognized_section_fails() -> None:
    doc = "# Edit Request\n\n## Notes\n- x\n"
    with pytest.raises(CompilationError, match="Unrecognized section"):
        parse_edit_request(doc, _SLUGS)


def test_stray_content_outside_blocks_fails() -> None:
    doc = "# Edit Request\n\n## Workflow: order\n\nplease change stuff\n"
    with pytest.raises(CompilationError, match="must live inside"):
        parse_edit_request(doc, _SLUGS)


def test_parser_imports_no_llm() -> None:
    # The parser module must be usable without any LLM machinery loaded.
    import workflow_compiler.spec.edit_ingest as mod

    assert not any("llm" in name for name in vars(mod) if not name.startswith("__"))

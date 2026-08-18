"""The BCR-001 artifacts produced live (Nemotron, 2026-08-18) parse and carry the
facts the plan's live verification asked for. They are Phase 2/3 inputs."""

from __future__ import annotations

from pathlib import Path

from workflow_compiler.change.parse import parse_epic, parse_impact, parse_stories, parse_tdd
from workflow_compiler.change.render import render_epic, render_impact, render_stories, render_tdd
from workflow_compiler.models.change import TDD_SECTIONS

FIXTURES = Path(__file__).parent / "fixtures" / "change_artifacts"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_impact_fixture_names_the_affected_code_docs_and_tests() -> None:
    doc = parse_impact(_read("BCR-001-impact-analysis.md"))
    assert doc.cr_id == "BCR-001" and doc.target_workflow.startswith("OrderWorkflow")
    refs = " ".join(f"{a.kind} {a.ref} {a.rationale} {a.kg_ref}" for a in doc.affected)
    for expected in (
        "order_workflow.py",
        "types.py",
        "complete_order",
        "TC-06",
        "TC-09",
        "TC-10",
        "US-003",
        "US-004",
        "US-005",
        "TP-",
        "EPIC-001",
        "EPIC-002",
    ):
        assert expected in refs, expected
    assert [r.req_id for r in doc.requirements] == [f"BCR-01-0{i}" for i in range(1, 7)]
    assert doc.kg_rows and doc.sources, "deterministic appendix + Sources footer"
    assert any("order_workflow.py" in s.path for s in doc.sources)
    assert render_impact(parse_impact(render_impact(doc))) == render_impact(doc)


def test_epic_fixture_has_a_story_map_numbered_from_the_catalog() -> None:
    doc = parse_epic(_read("EPIC-002.md"))
    assert doc.id == "EPIC-002" and doc.linked_bcr == "BCR-001"
    assert doc.statement and doc.value and doc.capabilities and doc.dod
    assert [row.id for row in doc.story_map][:2] == ["US-008", "US-009"]
    assert len(doc.story_map) >= 4 and doc.nfrs and doc.risks
    assert render_epic(parse_epic(render_epic(doc))) == render_epic(doc)


def test_stories_fixture_has_given_style_acceptance_criteria() -> None:
    doc = parse_stories(_read("US-008-015-stories.md"))
    assert doc.epic_id == "EPIC-002"
    assert [s.id for s in doc.stories][:3] == ["US-008", "US-009", "US-010"]
    for story in doc.stories:
        assert story.as_a.lower().startswith("as ") and story.i_want.lower().startswith("i want")
        assert story.acceptance and all(a.startswith("Given") for a in story.acceptance)
        assert story.implements, story.id
    assert render_stories(parse_stories(render_stories(doc))) == render_stories(doc)


def test_tdd_fixture_has_existing_vs_proposed_per_section() -> None:
    doc = parse_tdd(_read("TDD-ORD-002.md"))
    assert doc.id == "TDD-ORD-002" and doc.supersedes == "TDD-ORD-001"
    assert doc.linked_epic == "EPIC-002"
    assert [s.number for s in doc.sections] == [n for _, n, _ in TDD_SECTIONS]
    for section in doc.sections:
        assert section.existing and section.proposed, section.number
    text = "\n".join(s.proposed for s in doc.sections)
    for expected in (
        "PARTIALLY_PROVISIONED",
        "PARTIALLY_DISPATCHED",
        "list[ProvisioningResult]",
        "list[DispatchResult]",
        "ShipmentGroup",
    ):
        assert expected in text, expected
    saga = next(s for s in doc.sections if s.key == "saga")
    assert "group" in saga.proposed.lower()
    assert "order-state-machine-partial-shipment.mmd" in " ".join(doc.diagrams_needed)
    assert render_tdd(parse_tdd(render_tdd(doc))) == render_tdd(doc)

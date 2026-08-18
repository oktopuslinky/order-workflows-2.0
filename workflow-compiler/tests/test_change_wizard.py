"""Offline tests for the change-request wizard: BCR parsing, id assignment,
render→parse round trips, the engine state machine and versioning."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from workflow_compiler.change import bcr, ids
from workflow_compiler.change.engine import ChangeWizardEngine, WizardStateError
from workflow_compiler.change.parse import (
    ArtifactParseError,
    parse_epic,
    parse_impact,
    parse_stories,
    parse_tdd,
)
from workflow_compiler.change.render import render_epic, render_impact, render_stories, render_tdd
from workflow_compiler.change.service import ChangeRequestService
from workflow_compiler.exceptions import CompilationError, LLMProviderError, StateNotFoundError
from workflow_compiler.kg import InMemoryKnowledgeBaseStore, KgService
from workflow_compiler.kg.ingest import zip_folder
from workflow_compiler.kg.models import KbCatalog, KnowledgeBase
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models.change import (
    TDD_SECTIONS,
    AffectedItem,
    ArtifactKind,
    ArtifactStatus,
    ChangeRequestStage,
    EpicDoc,
    ImpactDoc,
    ImpactTableRow,
    NfrRow,
    RequirementImpact,
    RiskRow,
    SourceRef,
    StepStatus,
    StoriesDoc,
    StoryDoc,
    StoryMapRow,
    TddDoc,
    TddSection,
    VersionSource,
    WizardQuestionStatus,
)
from workflow_compiler.storage.change_store import (
    FileChangeRequestStore,
    InMemoryChangeRequestStore,
    validate_cr_id,
)

from .test_kg_service import build_corpus

T = TypeVar("T", bound=BaseModel)

BCR_TEXT = """Business Change Request (BCR)

Partial Shipment Support for Multi-Line Orders

Document ID: BCR-001

Status: Proposed — Pending Impact Assessment

Requested By: VP, Supply Chain Operations

Date Raised: 2026-08-10

Target Workflow: OrderWorkflow (EPIC-001 / TDD-ORD-001)

1. Change Summary

Currently, OrderWorkflow provisions and dispatches an order as a single unit (see TDD §4.1).

3. Requested Change — Functional Requirements

Req ID | Requirement
BCR-01-01 | The system shall split an order into shipment groups at provisioning time.
BCR-01-02 | Each shipment group shall be independently provisioned and dispatched.
BCR-01-03 | The parent order shall remain PARTIALLY_DISPATCHED until all groups reach DISPATCHED.

4. Impact on Existing Design

Data contracts (src/shared/types.py): ProvisioningResult must become list[ProvisioningResult].
Workflow (src/workflows/order_workflow.py): fan out per group; complete_order and get_status change.
"""


# --------------------------------------------------------------- BCR parsing


def test_bcr_meta_requirements_title_and_seeds() -> None:
    meta = bcr.parse_meta(BCR_TEXT)
    assert meta.doc_id == "BCR-001"
    assert meta.status == "Proposed — Pending Impact Assessment"
    assert meta.requested_by == "VP, Supply Chain Operations"
    assert meta.date_raised == "2026-08-10"
    assert meta.target_workflow == "OrderWorkflow (EPIC-001 / TDD-ORD-001)"
    reqs = bcr.parse_requirements(BCR_TEXT)
    assert [r.id for r in reqs] == ["BCR-01-01", "BCR-01-02", "BCR-01-03"]
    assert reqs[2].text.startswith("The parent order shall remain")
    assert (
        bcr.parse_title(BCR_TEXT, fallback="x") == "Partial Shipment Support for Multi-Line Orders"
    )
    seeds = bcr.seed_terms(BCR_TEXT, reqs)
    for expected in (
        "types.py",
        "order_workflow.py",
        "complete_order",
        "get_status",
        "PARTIALLY_DISPATCHED",
        "TDD §4.1",
        "EPIC-001",
        "TDD-ORD-001",
        "ProvisioningResult",
    ):
        assert expected in seeds, expected


def test_bcr_markdown_style_requirements_and_missing_meta() -> None:
    text = "# Faster refunds\n\n- BCR-02-01 — Refund within 24h.\n- BCR-02-02: Notify customer.\n"
    assert bcr.parse_meta(text).doc_id is None
    assert [r.id for r in bcr.parse_requirements(text)] == ["BCR-02-01", "BCR-02-02"]
    assert bcr.parse_title(text, fallback="f") == "Faster refunds"
    assert bcr.title_from_filename("BCR-007-night-shipping.docx") == "Night shipping"


# ------------------------------------------------------------ id assignment


def test_ids_from_catalog() -> None:
    catalog = KbCatalog(
        epics=["EPIC-001", "EPIC-001-A"],
        stories=[f"US-00{i}" for i in range(1, 8)],
        test_cases=[f"TC-{i:02d}" for i in range(1, 18)],
        requirements=["BR-01", "BCR-001"],
        documents=["BRD-ORD-001", "TDD-ORD-001", "TP-ORD-001"],
    )
    assigned = ids.assign_ids(catalog, target_hint="OrderWorkflow (EPIC-001 / TDD-ORD-001)")
    assert assigned.epic_id == "EPIC-002"
    assert assigned.prior_epic_id == "EPIC-001"
    assert assigned.tdd_id == "TDD-ORD-002"
    assert assigned.prior_tdd_id == "TDD-ORD-001"
    assert assigned.next_test_case == "TC-18"
    assert ids.story_ids(catalog, 3) == ["US-008", "US-009", "US-010"]
    assert ids.story_ids(catalog, 2, already=["US-010"]) == ["US-011", "US-012"]


def test_ids_on_an_empty_catalog() -> None:
    assigned = ids.assign_ids(KbCatalog())
    assert assigned.epic_id == "EPIC-001"
    assert assigned.tdd_id == "TDD-ORD-001"
    assert assigned.prior_tdd_id is None
    assert ids.story_ids(KbCatalog(), 1) == ["US-001"]
    assert assigned.next_test_case == "TC-01"


# ------------------------------------------------------- render ↔ parse


def _impact_doc() -> ImpactDoc:
    return ImpactDoc(
        title="Partial Shipment Support",
        cr_id="BCR-001",
        target_workflow="OrderWorkflow (EPIC-001 / TDD-ORD-001)",
        kb_name="Order lifecycle",
        summary="Structural change.\n\nSecond paragraph with a | pipe.",
        requirements=[
            RequirementImpact(req_id="BCR-01-01", requirement="split | groups", impact="types.py")
        ],
        affected=[
            AffectedItem(
                kind="module",
                ref="existing_Codebase/shared/types.py",
                change_type="modify",
                rationale="list results\nsecond line",
                kg_ref="mod:existing_Codebase/shared/types.py",
            ),
            AffectedItem(kind="test_case", ref="TC-06", change_type="verify", rationale="dispatch"),
        ],
        design_impacts=["State machine: PARTIALLY_* states"],
        risks=["Backward compatibility"],
        open_decisions=["Finance: consolidated vs itemized invoice"],
        kg_rows=[
            ImpactTableRow(node_id="US-003", type="UserStory", name="US-003", hops=1, via="x ← y")
        ],
        coverage_note="Retrieval coverage 75% — terms not found: foo",
        sources=[SourceRef(path="existing_Codebase/workflows/order_workflow.py", spans=[(1, 112)])],
    )


def test_impact_round_trip() -> None:
    doc = _impact_doc()
    md = render_impact(doc)
    assert md.startswith("# Impact Analysis — BCR-001 — Partial Shipment Support")
    assert "## 3. Affected Components" in md and "## Sources" in md
    back = parse_impact(md)
    assert back == doc
    assert render_impact(back) == md


def test_epic_round_trip() -> None:
    doc = EpicDoc(
        id="EPIC-002",
        title="Partial Shipment Support (Multi-Line Orders)",
        owner="Order Management Product Team",
        linked_brd="BRD-ORD-001",
        linked_bcr="BCR-001",
        status="Proposed",
        target_release="R2026.4",
        statement="As the platform, we need split shipments so that …",
        value=["Fewer complaints", "Faster delivery"],
        capabilities=["Provisioning per shipment group"],
        dod=["Passing TC-18…", "Load tested"],
        dod_done=[False, True],
        story_map=[
            StoryMapRow(id="US-008", title="Split order into groups", status="Proposed", doc=""),
            StoryMapRow(id="US-009", title="Dispatch per group", status="Proposed", doc=""),
        ],
        nfrs=[NfrRow(nfr="Idempotency", target="No duplicate dispatch per group")],
        dependencies=["Inventory Service", "Finance"],
        risks=[RiskRow(risk="Fan-out complexity", mitigation="Design review")],
        sources=[SourceRef(path="Business_Docs/epics/EPIC-001.docx")],
    )
    md = render_epic(doc)
    assert "## Story Map" in md and "- [x] Load tested" in md
    back = parse_epic(md)
    assert back == doc
    assert render_epic(back) == md


def test_stories_round_trip() -> None:
    doc = StoriesDoc(
        epic_id="EPIC-002",
        epic_title="Partial Shipment Support",
        linked_bcr="BCR-001",
        stories=[
            StoryDoc(
                id="US-008",
                title="Split order into shipment groups",
                epic="EPIC-002 — Partial Shipment Support",
                status="Proposed",
                points=5,
                as_a="As a fulfilment operator,",
                i_want="I want in-stock items grouped separately,",
                so_that="so that they ship immediately.",
                acceptance=[
                    "Given a multi-line order, when provisioning runs, then groups are created",
                    "Given all items in stock, the order transitions to PROVISIONED",
                ],
                notes="Implements BCR-01-01. See TDD-ORD-002 §4.2 and TC-18.",
                implements=["BCR-01-01", "BCR-01-02"],
            ),
            StoryDoc(id="US-009", title="Dispatch per group", points=8),
        ],
    )
    md = render_stories(doc)
    assert "## US-008: Split order into shipment groups" in md
    assert "### Acceptance Criteria" in md and "- [ ] Given a multi-line order" in md
    back = parse_stories(md)
    assert back == doc
    assert render_stories(back) == md


def test_tdd_round_trip_with_tables_and_fences() -> None:
    sections = []
    for key, number, title in TDD_SECTIONS:
        proposed = (
            f"Proposed for {key}.\n\n| Activity | Retry |\n| --- | --- |\n| dispatch_order | 5 |"
        )
        if key == "saga":
            proposed += "\n\n```python\n# not a heading\ntry:\n    await provision()\n```"
        sections.append(
            TddSection(
                key=key, number=number, title=title, existing=f"Existing {key}.", proposed=proposed
            )
        )
    doc = TddDoc(
        id="TDD-ORD-002",
        title="OrderWorkflow — Temporal Implementation (Partial Shipment)",
        linked_epic="EPIC-002",
        supersedes="TDD-ORD-001",
        version="0.1",
        status="Draft",
        author="Platform Engineering",
        sections=sections,
        diagrams_needed=["order-state-machine-partial-shipment.mmd"],
        sources=[SourceRef(path="existing_Codebase/shared/types.py", spans=[(1, 98)])],
    )
    md = render_tdd(doc)
    assert "## 4. Workflow Design" in md and "### 4.3 Saga / Compensation Logic" in md
    assert "#### Existing" in md and "### Proposed" in md
    back = parse_tdd(md)
    assert [s.number for s in back.sections] == [n for _, n, _ in TDD_SECTIONS]
    assert back == doc
    assert render_tdd(back) == md


def test_headings_inside_bodies_are_demoted() -> None:
    doc = _impact_doc()
    doc.summary = "Intro\n## Sneaky heading\ntext"
    md = render_impact(doc)
    assert "## Sneaky heading" not in md and "**Sneaky heading**" in md
    assert parse_impact(md).risks == doc.risks


def test_parse_rejects_titleless_markdown() -> None:
    with pytest.raises(ArtifactParseError):
        parse_epic("just prose\n\n## Story Map\n")


# ------------------------------------------------------------- store


async def test_change_store_round_trip_and_id_guard(tmp_path: Path) -> None:
    from workflow_compiler.models.change import ChangeRequest

    store = FileChangeRequestStore(tmp_path)
    cr = ChangeRequest(kb_id="kb", title="t", document_text="doc")
    await store.save(cr)
    assert (tmp_path / "change_requests" / f"{cr.cr_id}.json").is_file()
    loaded = await store.load(cr.cr_id)
    assert loaded.title == "t" and await store.exists(cr.cr_id)
    assert await store.list_ids() == [cr.cr_id]
    with pytest.raises(StateNotFoundError):
        validate_cr_id("../etc/passwd")
    with pytest.raises(StateNotFoundError):
        await store.load("..")
    await store.delete(cr.cr_id)
    assert await store.list_ids() == []


# ------------------------------------------------------------- engine


class ScriptedAnalyst(MockProvider):
    """Answers by output-schema name so the wizard can be driven end to end offline."""

    def __init__(self) -> None:
        super().__init__()
        self.followup_once = True
        self.by_schema: dict[str, Any] = {
            "DraftedWizardQuestions": {
                "questions": [
                    {
                        "question": "Consolidated or itemized invoice?",
                        "why": "BCR-01-04",
                        "options": [{"label": "One consolidated invoice", "detail": ""}],
                    },
                    {"question": "Cancel a single group?", "why": "BCR-01-05", "options": []},
                ]
            },
            "ImpactDraft": {
                "summary": "Structural change to OrderWorkflow.",
                "requirements": [
                    {"req_id": "BCR-01-01", "requirement": "split", "impact": "types.py"}
                ],
                "affected": [
                    {
                        "kind": "module",
                        "ref": "src/orders/workflow.py",
                        "change_type": "MODIFY",
                        "rationale": "fan out",
                        "kg_ref": "mod:src/orders/workflow.py",
                    }
                ],
                "design_impacts": ["Workflow: fan out per group"],
                "risks": ["Backward compatibility"],
                "open_decisions": ["Finance: invoice shape"],
            },
            "EpicDraft": {
                "epic": {
                    "id": "EPIC-999",
                    "title": "Partial Shipment Support",
                    "statement": "As the platform we need …",
                    "value": ["v"],
                    "capabilities": ["c"],
                    "dod": ["d1", "d2"],
                    "story_map": [
                        {"id": "US-1", "title": "Split order"},
                        {"id": "", "title": "Dispatch per group"},
                        {"id": "", "title": "Cancel a group"},
                        {"id": "", "title": "Consolidated completion"},
                    ],
                    "nfrs": [{"nfr": "Idempotency", "target": "per group"}],
                    "dependencies": ["Finance"],
                    "risks": [{"risk": "r", "mitigation": "m"}],
                }
            },
            "Revision": {"markdown": "", "summary": "Renamed the epic."},
        }
        self.calls_by_schema: dict[str, int] = {}

    async def structured(  # type: ignore[override]
        self, prompt: str, schema: type[T], *, system: str | None = None, temperature: float = 0.0
    ) -> T:
        name = schema.__name__
        self.calls.append(("structured", prompt))
        self.calls_by_schema[name] = self.calls_by_schema.get(name, 0) + 1
        if name == "AnswerNote":
            if "ALREADY asked" not in prompt and self.followup_once:
                self.followup_once = False
                return schema.model_validate(
                    {
                        "note": "",
                        "resolved": False,
                        "followup_question": "Per order or per group?",
                        "followup_options": [{"label": "Per order", "detail": ""}],
                    }
                )
            return schema.model_validate(
                {"note": "Decision: consolidated invoice.", "resolved": True}
            )
        if name == "StoriesDraft":
            wanted = [ln for ln in prompt.splitlines() if ln.startswith("- US-") and ":" in ln]
            stories = []
            for ln in wanted:
                sid, title = ln[2:].split(":", 1)
                stories.append(
                    {
                        "id": sid.strip(),
                        "title": title.strip(),
                        "points": 5,
                        "as_a": "As an operator,",
                        "i_want": "I want groups,",
                        "so_that": "so that items ship.",
                        "acceptance": ["Given a group, when it ships, then DISPATCHED"],
                        "notes": "Implements BCR-01-01.",
                        "implements": ["BCR-01-01"],
                    }
                )
            return schema.model_validate({"stories": stories})
        if name == "TddDraft":
            keys = [ln.split("`")[1] for ln in prompt.splitlines() if ln.startswith("- `")]
            return schema.model_validate(
                {
                    "sections": [
                        {"key": k, "existing": f"old {k}", "proposed": f"new {k}"} for k in keys
                    ],
                    "diagrams_needed": ["order-state-machine-partial-shipment.mmd"]
                    if "state_machine" in keys
                    else [],
                }
            )
        if name == "Revision":
            marker = "## Revised at\n"
            current = prompt.split("```markdown\n", 1)[1].rsplit("```", 1)[0]
            revised = current.replace("## Sources", marker + "\n## Sources", 1)
            return schema.model_validate({"markdown": revised, "summary": "Added a section."})
        return schema.model_validate(self.by_schema[name])


@pytest.fixture
async def ready_kb(tmp_path: Path) -> tuple[KgService, KnowledgeBase]:
    kg = KgService(InMemoryKnowledgeBaseStore(tmp_path / "state"))
    kb = await kg.create_from_zip(
        "mini", zip_folder(build_corpus(tmp_path / "kb_mini")), owner_id="u1", filename="m.zip"
    )
    return kg, await kg.index(kb.kb_id)


@pytest.fixture
def analyst() -> ScriptedAnalyst:
    return ScriptedAnalyst()


@pytest.fixture
async def service(
    ready_kb: tuple[KgService, KnowledgeBase], analyst: ScriptedAnalyst
) -> ChangeRequestService:
    kg, _kb = ready_kb
    return ChangeRequestService(InMemoryChangeRequestStore(), kg, lambda name, model: analyst)


async def test_create_parses_bcr_and_records_kb(
    service: ChangeRequestService, ready_kb: tuple[KgService, KnowledgeBase]
) -> None:
    _kg, kb = ready_kb
    cr = await service.create(kb.kb_id, text=BCR_TEXT, filename="BCR-001.md", provider="mock")
    assert cr.kb_name == "mini" and cr.title.startswith("Partial Shipment")
    assert cr.bcr_meta.doc_id == "BCR-001"
    assert [r.id for r in cr.requirements] == ["BCR-01-01", "BCR-01-02", "BCR-01-03"]
    assert "get_status" in cr.impact_seed_terms
    assert cr.wizard.provider == "mock" and cr.stage == ChangeRequestStage.CREATED
    assert cr.wizard.current is not None and cr.wizard.current.kind == ArtifactKind.IMPACT
    with pytest.raises(CompilationError):
        await service.create(kb.kb_id, text="   ")


async def test_full_wizard_flow_offline(
    service: ChangeRequestService,
    ready_kb: tuple[KgService, KnowledgeBase],
    analyst: ScriptedAnalyst,
) -> None:
    _kg, kb = ready_kb
    cr = await service.create(kb.kb_id, text=BCR_TEXT, filename="BCR-001.md")
    cr_id = cr.cr_id

    # answer/draft before start are refused
    with pytest.raises(WizardStateError):
        await service.answer(cr_id, "x")

    cr = await service.start(cr_id)
    assert cr.wizard.started_at is not None and cr.stage == ChangeRequestStage.IN_PROGRESS
    assert cr.ids.epic_id == "EPIC-001"  # kb_mini has no epic → first id
    assert cr.ids.tdd_id == "TDD-ORD-001"
    assert cr.impact_table, "impact traversal from BCR seeds is recorded"
    assert all(r.type != "Chunk" for r in cr.impact_table)

    # questions for the impact step
    cr = await service.start_questions(cr_id)
    step = cr.wizard.step("impact")
    assert step.status == StepStatus.ASKING and len(step.questions) == 2
    assert step.questions[0].options[0].label == "One consolidated invoice"
    prompt_used = analyst.calls[-1][1]
    assert "Change request BCR-001" in prompt_used
    assert "Knowledge-graph excerpts" in prompt_used and "impact traversal" in prompt_used
    # idempotent
    before = len(analyst.calls)
    await service.start_questions(cr_id)
    assert len(analyst.calls) == before

    # first answer → one follow-up, second answer resolves; third question skipped
    cr, outcome = await service.answer(cr_id, "Not sure")
    assert outcome.followup is True
    q = cr.wizard.step("impact").questions[0]
    assert q.awaiting_followup and q.prompt == "Per order or per group?"
    assert q.prompt_options[0].label == "Per order"
    cr, outcome = await service.answer(cr_id, "Per order", option="Per order")
    assert outcome.followup is False
    q = cr.wizard.step("impact").questions[0]
    assert q.status == WizardQuestionStatus.ANSWERED and q.chosen_option == "Per order"
    assert cr.wizard.step("impact").notes == ["Decision: consolidated invoice."]
    cr = await service.skip(cr_id)
    assert cr.wizard.step("impact").questions[1].status == WizardQuestionStatus.SKIPPED
    with pytest.raises(WizardStateError):
        await service.skip(cr_id)

    # cannot jump ahead
    with pytest.raises(WizardStateError):
        await service.draft(cr_id, "epic")

    # draft impact
    progress: list[str] = []
    cr = await service.draft(cr_id, "impact", progress=lambda m, d, t: progress.append(m))
    art = cr.artifacts.impact
    assert art.status == ArtifactStatus.DRAFTED and art.version == 1
    assert art.history[0].source == VersionSource.LLM_DRAFT
    assert progress and progress[-1] == "rendering"
    doc = parse_impact(art.markdown)
    assert doc.cr_id == "BCR-001" and doc.kb_name == "mini"
    assert doc.affected[0].change_type == "modify"  # normalised
    assert [r.req_id for r in doc.requirements] == ["BCR-01-01", "BCR-01-02", "BCR-01-03"]
    assert doc.requirements[1].impact == "(not assessed)"
    assert doc.kg_rows and doc.sources, "sources footer + deterministic appendix present"
    assert art.sources == doc.sources
    assert "Decision: consolidated invoice." in analyst.calls[-1][1]

    # human edit → new version; approval → cursor moves
    cr = await service.edit(
        cr_id, "impact", art.markdown.replace("Structural change", "Big change")
    )
    assert cr.artifacts.impact.version == 2
    assert cr.artifacts.impact.history[-1].source == VersionSource.HUMAN_EDIT
    with pytest.raises(CompilationError):
        await service.edit(cr_id, "impact", "no title here")
    cr = await service.approve(cr_id, "impact")
    assert cr.artifacts.impact.status == ArtifactStatus.APPROVED
    assert cr.wizard.cursor == 1 and cr.wizard.current is not None
    assert cr.wizard.current.kind == ArtifactKind.EPIC

    # epic: draft without asking (questions auto-skipped / none), ids assigned by engine
    cr = await service.draft(cr_id, "epic")
    epic = parse_epic(cr.artifacts.epic.markdown)
    assert epic.id == "EPIC-001"  # engine wins over the model's EPIC-999
    assert [r.id for r in epic.story_map] == ["US-006", "US-007", "US-008", "US-009"]
    assert cr.ids.story_ids == ["US-006", "US-007", "US-008", "US-009"]
    assert epic.linked_bcr == "BCR-001" and epic.dod_done == [False, False]
    assert cr.wizard.step("epic").status == StepStatus.DRAFTED
    cr = await service.approve(cr_id, "epic")

    # stories: one per story-map row, batched calls
    calls_before = analyst.calls_by_schema.get("StoriesDraft", 0)
    cr = await service.draft(cr_id, "stories")
    assert analyst.calls_by_schema["StoriesDraft"] - calls_before == 2  # 4 stories, batches of 3
    stories = parse_stories(cr.artifacts.stories.markdown)
    assert [s.id for s in stories.stories] == ["US-006", "US-007", "US-008", "US-009"]
    assert stories.stories[0].acceptance[0].startswith("Given")
    assert stories.stories[0].epic.startswith("EPIC-001")
    cr = await service.approve(cr_id, "stories")

    # tdd: four chunked calls, all sections present, existing vs proposed
    calls_before = analyst.calls_by_schema.get("TddDraft", 0)
    cr = await service.draft(cr_id, "tdd")
    assert analyst.calls_by_schema["TddDraft"] - calls_before == 4
    tdd = parse_tdd(cr.artifacts.tdd.markdown)
    assert tdd.id == "TDD-ORD-001" and tdd.linked_epic == "EPIC-001"
    assert len(tdd.sections) == len(TDD_SECTIONS)
    assert tdd.sections[3].existing == "old state_machine"
    assert tdd.sections[3].proposed == "new state_machine"
    assert tdd.diagrams_needed == ["order-state-machine-partial-shipment.mmd"]

    # revise → llm_revision version; then approve completes the wizard
    cr = await service.revise(cr_id, "tdd", "Add a section")
    assert cr.artifacts.tdd.version == 2
    assert cr.artifacts.tdd.history[-1].source == VersionSource.LLM_REVISION
    assert "## Revised at" in cr.artifacts.tdd.markdown
    cr = await service.approve(cr_id, "tdd")
    assert cr.wizard.complete and cr.stage == ChangeRequestStage.COMPLETE
    with pytest.raises(WizardStateError):
        await service.answer(cr_id, "anything")

    # editing an approved artifact re-opens it for approval without moving the cursor back
    cr = await service.edit(cr_id, "impact", cr.artifacts.impact.markdown + "\nExtra.\n")
    assert cr.artifacts.impact.status == ArtifactStatus.DRAFTED
    assert cr.stage == ChangeRequestStage.COMPLETE or cr.wizard.complete
    cr = await service.approve(cr_id, "impact")
    assert cr.artifacts.impact.status == ArtifactStatus.APPROVED
    assert cr.wizard.cursor == 4


async def test_draft_failure_records_error_and_keeps_state(
    ready_kb: tuple[KgService, KnowledgeBase],
) -> None:
    kg, kb = ready_kb
    failing = MockProvider()  # empty queue → raises on structured()
    service = ChangeRequestService(InMemoryChangeRequestStore(), kg, lambda n, m: failing)
    cr = await service.create(kb.kb_id, text=BCR_TEXT, filename="BCR-001.md")
    await service.start(cr.cr_id)
    with pytest.raises(LLMProviderError):
        await service.draft(cr.cr_id, "impact")
    cr = await service.get(cr.cr_id)
    step = cr.wizard.step("impact")
    assert step.error and step.status == StepStatus.PENDING
    assert cr.artifacts.impact.version == 0


async def test_engine_brief_lists_sources_from_retrieval(
    service: ChangeRequestService,
    ready_kb: tuple[KgService, KnowledgeBase],
    analyst: ScriptedAnalyst,
) -> None:
    kg, kb = ready_kb
    cr = await service.create(kb.kb_id, text=BCR_TEXT, filename="BCR-001.md")
    cr = await service.start(cr.cr_id)
    from workflow_compiler.agents.change_analyst import ChangeAnalystAgent

    engine = ChangeWizardEngine(ChangeAnalystAgent(analyst), kg, total_budget=800)
    brief = await engine.brief(cr, "impact")
    assert brief.sources, "retrievals produce a sources list"
    assert all(s.path for s in brief.sources)
    assert "### Requirements" in brief.text and "BCR-01-03" in brief.text

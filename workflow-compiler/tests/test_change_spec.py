"""Phase 3: KG grounder, change spec render/parse/validate, dialogue over changes.md,
and the ProjectCompiler wiring (grounded compile → validate → approve gate)."""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_compiler.agents.change_spec import ChangeSpecAgent, impact_table_text
from workflow_compiler.change.render import render_impact
from workflow_compiler.compiler import ReviewConfig, WorkflowCompiler
from workflow_compiler.dialogue.agenda import agenda_fingerprint, has_anything_to_ask
from workflow_compiler.dialogue.change_ops import apply_component_updates, park_change_question
from workflow_compiler.exceptions import ApprovalError
from workflow_compiler.kg import InMemoryKnowledgeBaseStore, KgGrounder, KgService, KnowledgeBase
from workflow_compiler.kg.grounding import grounding_query
from workflow_compiler.kg.ingest import zip_folder
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    CHANGES_SLUG,
    ChangeSpec,
    ChangeSpecDraft,
    ChangeType,
    CompilationProject,
    ComponentChange,
    ComponentKind,
    ComponentUpdate,
    ProjectStage,
    Provenance,
    Severity,
    SpecItem,
)
from workflow_compiler.models.change import (
    AffectedItem,
    ChangeRequest,
    ChangeRequirement,
    ImpactDoc,
    RequirementImpact,
)
from workflow_compiler.project_compiler import ProjectCompiler
from workflow_compiler.prompts import PromptManager
from workflow_compiler.spec.change_ingest import ingest_change_markdown
from workflow_compiler.spec.change_renderer import CHANGES_FILENAME, render_change_spec
from workflow_compiler.spec.change_validator import validate_change_spec
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.project_store import InMemoryProjectStore

from .test_kg_service import build_corpus

_NO_REVIEW = ReviewConfig(enabled=False)

TDD_TEXT = """Technical Design Document (TDD)
Document ID: TDD-order-002
1. Overview
Existing: OrderWorkflow in src/orders/workflow.py provisions and dispatches one order.
Proposed: split the order into shipment groups; provision_order and dispatch_order run
per group; OrderState gains PARTIALLY_PROVISIONED and PARTIALLY_DISPATCHED.
2. Testing
Existing: tests cover the happy path.
Proposed: add tests for a group failing while the other ships.
"""


def _spec() -> ChangeSpec:
    return ChangeSpec(
        components=[
            ComponentChange(
                name="src/orders/workflow.py",
                kind=ComponentKind.MODULE,
                path="mod:src/orders/workflow.py",
                existing="Provisions and dispatches one order.",
                proposed="Fan out per shipment group.\nCompensate per group.",
                change_type=ChangeType.MODIFY,
                requirement_ids=["BCR-01-01", "BCR-01-02"],
                provenance=Provenance.DOCUMENT_GROUNDED,
            ),
            ComponentChange(
                name="OrderState",
                kind=ComponentKind.TYPE,
                path="src/orders/types.py",
                existing="",
                proposed="Add PARTIALLY_PROVISIONED / PARTIALLY_DISPATCHED.",
                change_type=ChangeType.ADD,
                provenance=Provenance.LLM_INFERRED,
            ),
            ComponentChange(
                name="order-state-machine-partial.mmd",
                kind=ComponentKind.DIAGRAM,
                path="",
                proposed="New companion diagram for the per-group state machine.",
                change_type=ChangeType.ADD,
                provenance=Provenance.HUMAN_PROVIDED,
            ),
        ],
        assumptions=[
            SpecItem(text="Groups are fixed at capture.", provenance=Provenance.LLM_INFERRED)
        ],
        open_questions=[
            SpecItem(
                text="Refund a cancelled group immediately?", provenance=Provenance.LLM_INFERRED
            ),
            SpecItem(
                text="Which carrier API?",
                provenance=Provenance.HUMAN_PROVIDED,
                resolved=True,
                answer="the existing one",
                ref="dialogue:q1",
            ),
        ],
        sources=["src/orders/workflow.py — lines 1-40", "docs/TDD-order.md — lines 1-14"],
        version=3,
    )


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def kg(tmp_path: Path) -> KgService:
    return KgService(InMemoryKnowledgeBaseStore(tmp_path / "state"))


@pytest.fixture
async def kb(kg: KgService, tmp_path: Path) -> KnowledgeBase:
    corpus = build_corpus(tmp_path / "kb_mini")
    created = await kg.create_from_zip("mini", zip_folder(corpus), owner_id="u1", filename="m.zip")
    return await kg.index(created.kb_id)


def _project_compiler(kg: KgService | None = None) -> ProjectCompiler:
    provider = MockProvider(script_defaults=True)
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    return ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=InMemoryProjectStore(),
        segmentation_review=False,
        kg_service=kg,
    )


def _change_request(kb_id: str) -> ChangeRequest:
    cr = ChangeRequest(
        kb_id=kb_id, kb_name="mini", title="BCR-001 partial shipments", document_text="BCR"
    )
    cr.requirements = [
        ChangeRequirement(id="BCR-01-01", text="split"),
        ChangeRequirement(id="BCR-01-02", text="per group"),
    ]
    doc = ImpactDoc(
        cr_id="BCR-001", title="Partial shipments", summary="Structural change.",
        requirements=[RequirementImpact(req_id="BCR-01-01", requirement="split", impact="wf")],
        affected=[
            AffectedItem(kind="module", ref="src/orders/workflow.py", change_type="modify",
                         rationale="fan out", kg_ref="mod:src/orders/workflow.py"),
            AffectedItem(kind="test", ref="tests/test_workflow.py", change_type="add",
                         rationale="new cases", kg_ref=""),
        ],
    )
    cr.artifacts.impact.markdown = render_impact(doc)
    cr.artifacts.impact.status = "approved"
    return cr


# ------------------------------------------------------------------ prompts / grounder


def test_prompts_render_with_and_without_kg_context() -> None:
    prompts = PromptManager()
    for name in ("discover_workflows", "discover_workflow", "extract_facts"):
        plain = prompts.render(name, document_text="DOC")
        empty = prompts.render(name, document_text="DOC", kg_context="")
        assert plain == empty, name
        assert "KG BLOCK" not in plain
        grounded = prompts.render(name, document_text="DOC", kg_context="KG BLOCK\n")
        assert "KG BLOCK" in grounded and grounded.replace("KG BLOCK\n", "") == plain
    plain = prompts.render(
        "design_temporal", workflow_graph="G", workflow_facts="F", cvpa_classification="C"
    )
    grounded = prompts.render(
        "design_temporal", workflow_graph="G", workflow_facts="F",
        cvpa_classification="C", kg_context="KG BLOCK\n",
    )
    assert "KG BLOCK" in grounded and grounded.replace("KG BLOCK\n", "") == plain
    # the TDD hint lives in the segmentation prompt
    assert "technical design document" in prompts.render(
        "discover_workflows", document_text="x"
    ).lower()


def test_grounding_query_puts_identifiers_first() -> None:
    query = grounding_query("Call provision_order in workflows/order_workflow.py then wait.")
    head = query.split("\n", 1)[0]
    assert "provision_order" in head and "order_workflow.py" in head


async def test_grounder_no_op_when_unset() -> None:
    compiler = _project_compiler()
    project = await compiler.compile_document(TDD_TEXT, persist=False)
    assert project.kb_id is None
    assert project.change_spec is None
    assert project.grounding is None
    assert CHANGES_SLUG not in ProjectCompiler.spec_markdown(project)
    assert compiler.grounder_for(project) is None


async def test_grounder_renders_a_block_with_sources(kg: KgService, kb: KnowledgeBase) -> None:
    grounder = KgGrounder(kg, kb.kb_id, kb_name="Mini KB", budget=2000)
    result = await grounder.context_for("how does dispatch_order compensate provision_order")
    assert not result.empty
    assert result.block.startswith("KNOWLEDGE-GRAPH CONTEXT")
    assert '"Mini KB"' in result.block
    assert result.block.rstrip().endswith("--- END KNOWLEDGE GRAPH CONTEXT ---")
    assert result.sources
    assert any("workflow.py" in s or "activities.py" in s for s in result.sources)
    assert list(grounder.sources_seen) == result.sources
    # cached: the same text does not hit the graph again
    again = await grounder.context_for("how does dispatch_order compensate provision_order")
    assert again is result
    # a broken kb id degrades to an empty block, never raises
    broken = KgGrounder(kg, "nope")
    assert (await broken.context_for("anything")).empty
    assert await broken.block_for("anything") is None


# ------------------------------------------------------------------ render ⇄ parse


def test_change_spec_render_parse_identity() -> None:
    spec = _spec()
    markdown = render_change_spec(spec, kb_id="kb1", kb_name="Mini", change_request_id="cr1",
                                  change_request_title="BCR-001")
    assert markdown.startswith("# Change Spec\n")
    assert "### src/orders/workflow.py — module, modify\n" in markdown
    assert "### OrderState — type, add [inferred]\n" in markdown
    assert "### order-state-machine-partial.mmd — diagram, add [human]\n" in markdown
    assert "- knowledge base: Mini (`kb1`)" in markdown
    assert "- [x] (dialogue:q1) Which carrier API? [human]\n  Answer: the existing one" in markdown
    parsed = ingest_change_markdown(None, markdown).spec
    assert parsed.model_dump() == spec.model_dump()
    assert render_change_spec(parsed, kb_id="kb1", kb_name="Mini", change_request_id="cr1",
                              change_request_title="BCR-001") == markdown


def test_change_spec_ingest_merges_human_edits() -> None:
    spec = _spec()
    markdown = render_change_spec(spec)
    edited = markdown.replace(
        "## Assumptions\n",
        "### get_status — query, modify\n- path:\n- requirements:\n\n"
        "#### Existing\nOne status.\n\n#### Proposed\nPer-group status.\n\n## Assumptions\n",
    ).replace(
        "Fan out per shipment group.\nCompensate per group.",
        "Fan out per shipment group.\nCompensate per group.\nEmit a per-group event.",
    )
    result = ingest_change_markdown(spec, edited)
    new = result.spec
    assert new.version == spec.version + 1
    workflow = new.component("src/orders/workflow.py")
    assert workflow is not None and workflow.provenance is Provenance.HUMAN_PROVIDED
    assert "Emit a per-group event." in workflow.proposed
    added = new.component("get_status", ComponentKind.QUERY)
    assert added is not None and added.provenance is Provenance.HUMAN_PROVIDED
    assert added.proposed == "Per-group status."
    # untouched entries keep their provenance; grounding/sources are read-only
    assert new.component("OrderState").provenance is Provenance.LLM_INFERRED  # type: ignore[union-attr]
    assert new.sources == spec.sources
    assert any("get_status" in c for c in result.changes)


# ------------------------------------------------------------------ validator


async def test_change_validator_findings(kg: KgService, kb: KnowledgeBase) -> None:
    spec = ChangeSpec(
        components=[
            ComponentChange(name="src/orders/workflow.py", kind=ComponentKind.MODULE,
                            path="src/orders/workflow.py", proposed="fan out",
                            requirement_ids=["BCR-01-01"]),
            ComponentChange(name="dispatch_order", kind=ComponentKind.ACTIVITY,
                            path="fn:src/orders/activities.py:dispatch_order", proposed="x"),
            ComponentChange(name="OrderState", kind=ComponentKind.TYPE,
                            path="src/orders/state.py", proposed="new states",
                            requirement_ids=["BCR-01-09"]),
            ComponentChange(name="tests/test_workflow.py", kind=ComponentKind.TEST,
                            path="tests/test_workflow.py", proposed="",
                            change_type=ChangeType.MODIFY),
            ComponentChange(name="new_thing.py", kind=ComponentKind.MODULE, path="src/new_thing.py",
                            proposed="brand new", change_type=ChangeType.ADD),
        ]
    )
    findings = await validate_change_spec(
        spec, kg=kg, kb_id=kb.kb_id, requirement_ids=["BCR-01-01", "BCR-01-02"]
    )
    by_message = {f.message: f for f in findings}
    assert all(f.workflow == CHANGES_SLUG for f in findings)
    # resolvable paths (file, fn symbol) raise nothing
    assert not any("src/orders/workflow.py" in m and "not in the knowledge base" in m
                   for m in by_message)
    assert not any("dispatch_order (activity) points" in m for m in by_message)
    # unresolvable path → WARNING with search suggestions
    bad_path = next(f for m, f in by_message.items() if "src/orders/state.py" in m)
    assert bad_path.severity is Severity.WARNING
    assert bad_path.suggestion and "did you mean" in bad_path.suggestion
    # unknown requirement id → WARNING
    bad_req = next(f for m, f in by_message.items() if "BCR-01-09" in m)
    assert bad_req.severity is Severity.WARNING
    # empty proposed → BLOCKING
    empty = next(f for m, f in by_message.items() if "no proposed change" in m)
    assert empty.severity is Severity.BLOCKING
    # an ADD is allowed to point at a path that does not exist yet
    assert not any("new_thing" in m for m in by_message)
    # without a KB / requirement list only the structural rules run
    offline = await validate_change_spec(spec)
    assert {f.severity for f in offline} == {Severity.BLOCKING}
    assert not await validate_change_spec(ChangeSpec(components=[
        ComponentChange(name="a", proposed="b")]))
    assert (await validate_change_spec(ChangeSpec()))[0].severity is Severity.WARNING


# ------------------------------------------------------------------ agent + seed


def test_agent_to_spec_cleans_and_seeds() -> None:
    seeds = [
        ComponentChange(name="src/orders/workflow.py", kind=ComponentKind.MODULE,
                        path="mod:src/orders/workflow.py", existing="one order",
                        proposed="fan out", requirement_ids=["BCR-01-01"],
                        provenance=Provenance.DOCUMENT_GROUNDED),
    ]
    draft = ChangeSpecDraft.model_validate({
        "components": [
            {"name": "`src/orders/workflow.py`", "kind": "file", "change_type": "modified",
             "requirement_ids": ["BCR-01-01", "BCR-09-99"], "existing": "", "proposed": ""},
            {"name": "src/orders/workflow.py", "kind": "module", "proposed": "dup"},
            {"name": "OrderState", "kind": "class", "path": "src/orders/types.py",
             "proposed": "new states", "change_type": "new"},
            {"name": "", "proposed": "ignored"},
        ],
        "assumptions": ["A"], "open_questions": [" Q ", ""],
    })
    spec = ChangeSpecAgent.to_spec(
        draft, TDD_TEXT, seed_components=seeds, requirement_ids=["BCR-01-01"], sources=["s"]
    )
    assert [c.name for c in spec.components] == ["src/orders/workflow.py", "OrderState"]
    workflow = spec.components[0]
    assert workflow.kind is ComponentKind.MODULE and workflow.change_type is ChangeType.MODIFY
    assert workflow.path == "mod:src/orders/workflow.py"  # from the seed
    assert workflow.existing == "one order" and workflow.proposed == "fan out"
    assert workflow.requirement_ids == ["BCR-01-01"]
    assert workflow.provenance is Provenance.DOCUMENT_GROUNDED
    state = spec.components[1]
    assert state.kind is ComponentKind.TYPE and state.change_type is ChangeType.ADD
    assert state.provenance is Provenance.DOCUMENT_GROUNDED  # named in the TDD text
    assert [a.text for a in spec.assumptions] == ["A"]
    assert [q.text for q in spec.open_questions] == ["Q"]
    assert spec.sources == ["s"]
    # a model that returns nothing keeps the seeds; seeds it skips are appended
    empty = ChangeSpecAgent.to_spec(ChangeSpecDraft(), TDD_TEXT, seed_components=seeds)
    assert [c.name for c in empty.components] == ["src/orders/workflow.py"]
    extra = [*seeds, ComponentChange(name="tests/test_x.py", kind=ComponentKind.TEST,
                                     proposed="new cases", change_type=ChangeType.ADD)]
    kept = ChangeSpecAgent.to_spec(draft, TDD_TEXT, seed_components=extra)
    assert [c.name for c in kept.components] == [
        "src/orders/workflow.py", "OrderState", "tests/test_x.py"]
    assert impact_table_text([]) == "(none)"


def test_seed_components_from_change_request() -> None:
    from workflow_compiler.change.spec_seed import seed_components

    cr = _change_request("kb")
    seeds = seed_components(cr)
    assert [(c.name, c.kind.value, c.change_type.value, c.path) for c in seeds] == [
        ("src/orders/workflow.py", "module", "modify", "mod:src/orders/workflow.py"),
        ("tests/test_workflow.py", "test", "add", "tests/test_workflow.py"),
    ]
    assert seeds[0].proposed == "fan out"  # rationale until the TDD supplies text
    assert seed_components(ChangeRequest(kb_id="kb", title="t", document_text="x")) == []


# ------------------------------------------------------------------ change_ops


def test_apply_component_updates_and_park() -> None:
    spec = _spec()
    new, summary, warnings = apply_component_updates(
        spec,
        [
            ComponentUpdate(action="modify", name="OrderState", path="src/orders/types.py",
                            proposed="Add PARTIALLY_* states."),
            ComponentUpdate(action="modify", name="workflow.py", requirement_ids=["BCR-01-01"]),
            ComponentUpdate(action="add", name="cancel_group", kind="signal",
                            proposed="Cancel one group.", change_type="add"),
            ComponentUpdate(action="remove", name="order-state-machine-partial.mmd"),
            ComponentUpdate(action="modify", name="ghost", proposed="p"),
            ComponentUpdate(action="remove", name="nothing-here"),
            ComponentUpdate(action="modify", name="OrderState", proposed="Add PARTIALLY_* states."),
        ],
        resolve_questions=["Refund a cancelled group immediately?"],
    )
    assert spec.version == 3 and new.version == 4  # the input is untouched
    assert new.component("OrderState").proposed == "Add PARTIALLY_* states."  # type: ignore[union-attr]
    assert new.component("OrderState").provenance is Provenance.HUMAN_PROVIDED  # type: ignore[union-attr]
    assert new.component("src/orders/workflow.py").requirement_ids == ["BCR-01-01"]  # type: ignore[union-attr]
    assert new.component("cancel_group", ComponentKind.SIGNAL) is not None
    assert new.component("order-state-machine-partial.mmd") is None
    assert new.component("ghost") is not None  # a modify of an unknown name adds it
    assert new.open_questions[0].resolved is True
    assert any("added it instead" in w for w in warnings)
    assert any("no component named 'nothing-here'" in w for w in warnings)
    assert any("changed nothing" in w for w in warnings)
    assert summary[-1] == "change spec version bumped to 4"
    unchanged, summary, _ = apply_component_updates(spec, [])
    assert not summary and unchanged.version == 3
    parked = park_change_question(spec, "later", ref="dialogue:x")
    assert parked.open_questions[-1].provenance is Provenance.HUMAN_PROVIDED
    assert len(spec.open_questions) == 2


def test_agenda_includes_the_change_spec() -> None:
    project = CompilationProject(document_text="d")
    assert not has_anything_to_ask(project)
    base = agenda_fingerprint(project)
    project.change_spec = _spec()
    assert has_anything_to_ask(project)  # one unresolved open question
    assert agenda_fingerprint(project) != base
    project.change_spec.open_questions[0].resolved = True
    assert not has_anything_to_ask(project)


# ------------------------------------------------------------------ ProjectCompiler wiring


async def test_grounded_compile_validate_and_approve_gate(
    kg: KgService, kb: KnowledgeBase, tmp_path: Path
) -> None:
    compiler = _project_compiler(kg)
    cr = _change_request(kb.kb_id)
    grounder = KgGrounder(kg, kb.kb_id, kb_name="Mini KB")
    project = await compiler.compile_document(TDD_TEXT, grounder=grounder, change_request=cr)
    assert project.kb_id == kb.kb_id and project.change_request_id == cr.cr_id
    assert project.grounding is not None
    assert project.grounding.kb_name == "Mini KB"
    assert project.grounding.change_request_title == cr.title
    assert project.grounding.requirement_ids == ["BCR-01-01", "BCR-01-02"]
    assert project.grounding.sources  # the packets dereferenced corpus files
    assert project.change_spec is not None
    names = {c.name for c in project.change_spec.components}
    assert {"src/orders/workflow.py", "dispatch_order"} <= names  # the mock's demo draft
    assert "change_spec" in project.stage_timings
    # the prompts saw the KG block (segmentation + facts + change spec)
    llm = compiler._llm
    assert isinstance(llm, MockProvider)
    prompts = [p for kind, p in llm.calls if kind == "structured"]
    assert sum("KNOWLEDGE-GRAPH CONTEXT" in p for p in prompts) >= 3

    files = ProjectCompiler.spec_markdown(project)
    assert CHANGES_SLUG in files and files[CHANGES_SLUG].startswith("# Change Spec")
    assert "- knowledge base: Mini KB" in files[CHANGES_SLUG]
    assert f"({cr.cr_id})" not in files[CHANGES_SLUG]  # id is backticked
    assert cr.title in files[CHANGES_SLUG]

    # spec files on disk include changes.md, and read back under the pseudo-slug
    paths = compiler.write_spec_files(project, tmp_path / "specs")
    assert (tmp_path / "specs" / CHANGES_FILENAME) in paths
    read = compiler.read_spec_files(project, tmp_path / "specs")
    assert read[CHANGES_SLUG] == files[CHANGES_SLUG]
    assert "## Change Spec" in compiler.render_overview(project)

    # validate: an edited changes.md with an empty Proposed → BLOCKING under __changes__
    edited = files[CHANGES_SLUG].replace(
        "#### Proposed\nAccept a shipment group id and dispatch that group only.",
        "#### Proposed\n<!-- none -->",
    )
    assert edited != files[CHANGES_SLUG]
    validated = await compiler.validate_specs(
        project.project_id, markdown_by_slug={CHANGES_SLUG: edited}
    )
    changes_findings = validated.validation_findings[CHANGES_SLUG]
    assert any(f.severity is Severity.BLOCKING and "dispatch_order" in f.message
               for f in changes_findings)
    assert validated.change_spec is not None
    assert validated.change_spec.component("dispatch_order").proposed == ""  # type: ignore[union-attr]
    assert validated.stage is ProjectStage.SPEC_VALIDATED

    # approve refuses on the blocking change finding, honours accept_incomplete
    with pytest.raises(ApprovalError, match=r"changes\.md has blocking findings"):
        await compiler.approve_spec(project.project_id)
    approved = await compiler.approve_spec(project.project_id, accept_incomplete=True)
    assert approved.spec_approval_status.value == "approved"
    assert CHANGES_SLUG in approved.validation_findings

    # quick save (update_specs) folds changes.md too, without validation
    fixed = files[CHANGES_SLUG]
    saved = await compiler.update_specs(project.project_id, {CHANGES_SLUG: fixed})
    assert saved.change_spec is not None
    assert saved.change_spec.component("dispatch_order").proposed.startswith("Accept a shipment")  # type: ignore[union-attr]


async def test_dialogue_asks_and_applies_change_spec_answers(
    kg: KgService, kb: KnowledgeBase
) -> None:
    compiler = _project_compiler(kg)
    grounder = KgGrounder(kg, kb.kb_id, kb_name="Mini KB")
    project = await compiler.compile_document(TDD_TEXT, grounder=grounder)
    assert project.change_request_id is None and project.change_spec is not None
    # blank one Proposed so validate raises a BLOCKING change finding
    files = ProjectCompiler.spec_markdown(project)
    edited = files[CHANGES_SLUG].replace(
        "#### Proposed\nAccept a shipment group id and dispatch that group only.",
        "#### Proposed\n<!-- none -->",
    )
    project = await compiler.validate_specs(
        project.project_id, markdown_by_slug={CHANGES_SLUG: edited}
    )
    assert any(f.severity is Severity.BLOCKING for f in project.validation_findings[CHANGES_SLUG])

    project, session = await compiler.start_dialogue(project.project_id)
    slugs = {q.slug for q in session.questions}
    assert CHANGES_SLUG in slugs  # the mock's canned agenda is re-slugged per file
    # answer the change-spec question: the mock's ChangeAnswerPlan fills dispatch_order
    while session.current is not None and session.current.slug != CHANGES_SLUG:
        project, session = await compiler.skip_dialogue(project.project_id)
    project, session, outcome = await compiler.answer_dialogue(
        project.project_id, "dispatch one shipment group per call"
    )
    assert outcome.applied and any("dispatch_order" in c for c in outcome.changes)
    assert project.change_spec is not None
    assert project.change_spec.component("dispatch_order").proposed.startswith("Mock-answered")  # type: ignore[union-attr]
    assert project.change_spec.component("dispatch_order").provenance is Provenance.HUMAN_PROVIDED  # type: ignore[union-attr]
    assert project.change_spec.version == 3  # ingest bump + answer bump
    assert project.stage is ProjectStage.SPEC_DRAFTED
    assert CHANGES_SLUG in project.dialogue_session.applied_specs  # type: ignore[union-attr]
    project = await compiler.end_dialogue(project.project_id)
    assert CHANGES_SLUG not in project.validation_findings  # cleared → re-validate

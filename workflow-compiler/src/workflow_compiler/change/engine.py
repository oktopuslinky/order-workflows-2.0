"""ChangeWizardEngine — the deterministic state machine of the change wizard.

The wizard walks a :class:`~workflow_compiler.models.change.ChangeRequest`
through **Impact → EPIC → Stories → TDD**. Per step:

``start_step``  → the agent drafts 2-5 clarifying questions (grounded in a brief)
``answer/skip`` → each answer becomes one brief line (one follow-up at most)
``draft``       → brief = BCR + answers + KG retrievals + impact traversal +
                  previously approved artifacts → agent plan → **engine assigns
                  ids from the KB catalog** → :mod:`change.render` → new
                  ``llm_draft`` version
``revise``      → chat instruction → agent edits the markdown → ``llm_revision``
``edit``        → human markdown → ``human_edit`` version (must still parse)
``approve``     → artifact approved, cursor advances

Everything except the agent calls is pure and synchronous. Long agent calls
(questions, draft, revise) are run by the API as jobs; ``answer`` is one short
call and stays synchronous, like the Resolve dialogue.

Grounding is visible: the KB files/spans that made it into a draft's brief are
recorded on the artifact and rendered as its ``## Sources`` footer, and low
retrieval coverage is surfaced as a note in the artifact rather than hidden.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from workflow_compiler.agents.change_analyst import ChangeAnalystAgent
from workflow_compiler.exceptions import ApprovalError, CompilationError
from workflow_compiler.kg.models import KgPacket, KgSection
from workflow_compiler.kg.service import KgService
from workflow_compiler.models.change import (
    STEP_LABELS,
    TDD_SECTIONS,
    WIZARD_ORDER,
    ArtifactKind,
    ArtifactStatus,
    ChangeRequest,
    ChangeRequestStage,
    ChangeType,
    EpicDoc,
    ImpactDoc,
    ImpactTableRow,
    RequirementImpact,
    SourceRef,
    StepStatus,
    StoriesDoc,
    StoryDoc,
    StoryMapRow,
    TddDoc,
    TddSection,
    VersionSource,
    WizardQuestion,
    WizardQuestionStatus,
    WizardStep,
)

from . import ids as idmod
from .parse import ArtifactParseError, parse_artifact, parse_epic
from .render import render_epic, render_impact, render_stories, render_tdd

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], None]


class WizardStateError(ApprovalError):
    """The requested wizard transition is not allowed in the current state (HTTP 409)."""


#: Node types worth showing in the deterministic impact appendix (topics and
#: raw chunks are noise for a reader; they still drive retrieval).
_IMPACT_ROW_TYPES = frozenset(
    {
        "Module",
        "Function",
        "Class",
        "Document",
        "Epic",
        "UserStory",
        "TestCase",
        "Requirement",
        "Config",
        "Service",
    }
)

#: TDD sections are drafted in chunks so a single Nemotron answer stays short
#: enough to be reliable JSON (Phase 0 lesson: long answers get truncated).
_TDD_CHUNKS: tuple[tuple[str, ...], ...] = (
    ("overview", "why_temporal", "architecture"),
    ("state_machine", "activities", "saga"),
    ("idempotency", "signals_queries", "timeouts", "delivery_wait"),
    ("data_contracts", "observability", "testing", "open_items"),
)
_STORY_BATCH = 3

_STEP_QUERIES: dict[ArtifactKind, tuple[str, ...]] = {
    ArtifactKind.IMPACT: (
        "state machine states transitions cancel compensation saga",
        "test plan scope out of scope test cases matrix",
        "epic definition of done story map",
    ),
    ArtifactKind.EPIC: (
        "epic statement business value in-scope capabilities definition of done story map "
        "non-functional requirements dependencies risks",
        "business requirements objectives scope",
    ),
    ArtifactKind.STORIES: (
        "user story acceptance criteria given when notes implements",
        "provision order dispatch order complete order cancel status query",
    ),
    ArtifactKind.TDD: (
        "technical design overview why temporal architecture state machine",
        "activities purpose idempotency strategy retry policy timeouts SLA",
        "saga compensation logic idempotency keys signals queries continue as new delivery wait",
        "data contracts types dataclasses OrderState ProvisioningResult DispatchResult",
        "workflow run method compensate provisioning dispatch cancel signal",
        "testing strategy time-skipping test cases",
    ),
}


@dataclass
class Brief:
    """What the drafter sees, plus the grounding bookkeeping the artifact records."""

    text: str
    sources: list[SourceRef] = field(default_factory=list)
    coverage: float = 1.0
    coverage_note: str = ""
    packets: list[KgPacket] = field(default_factory=list)


@dataclass
class AnswerOutcome:
    question: WizardQuestion
    followup: bool
    step: WizardStep


class ChangeWizardEngine:
    """Deterministic wizard over one change request (see module docstring)."""

    def __init__(
        self,
        agent: ChangeAnalystAgent,
        kg: KgService,
        *,
        per_query_budget: int = 1200,
        total_budget: int = 6000,
        impact_hops: int = 2,
        max_impact_rows: int = 80,
        max_questions: int = 5,
    ) -> None:
        self._agent = agent
        self._kg = kg
        self._per_query_budget = per_query_budget
        self._total_budget = total_budget
        self._impact_hops = impact_hops
        self._max_impact_rows = max_impact_rows
        self._max_questions = max_questions

    # ------------------------------------------------------------------ util
    @staticmethod
    def _step(cr: ChangeRequest, kind: ArtifactKind | str | None) -> WizardStep:
        if kind is None:
            current = cr.wizard.current
            if current is None:
                raise WizardStateError("The wizard is complete; every step is approved.")
            return current
        return cr.wizard.step(kind)

    @staticmethod
    def _require_started(cr: ChangeRequest) -> None:
        if cr.wizard.started_at is None:
            raise WizardStateError("Start the wizard first (POST …/wizard/start).")

    def _check_reachable(self, cr: ChangeRequest, step: WizardStep) -> None:
        index = cr.wizard.index_of(step.kind)
        if index > cr.wizard.cursor:
            previous = STEP_LABELS[WIZARD_ORDER[index - 1]]
            raise WizardStateError(
                f"Approve the {previous} step before working on {STEP_LABELS[step.kind]}."
            )

    # ----------------------------------------------------------------- start
    async def initialize(self, cr: ChangeRequest) -> ChangeRequest:
        """LLM-free start: reserve ids from the catalog and compute the impact traversal."""
        if cr.wizard.started_at is None:
            catalog = await self._kg.catalog(cr.kb_id)
            cr.ids = idmod.assign_ids(catalog, target_hint=cr.bcr_meta.target_workflow)
            cr.impact_table = await self._impact_rows(cr)
            cr.wizard.started_at = cr.wizard.updated_at
            cr.stage = ChangeRequestStage.IN_PROGRESS
            cr.touch()
        return cr

    async def start(self, cr: ChangeRequest) -> ChangeRequest:
        """Reserve ids, compute the impact traversal and ask the first step's questions."""
        await self.initialize(cr)
        current = cr.wizard.current
        if current is not None and current.status == StepStatus.PENDING:
            await self.start_step(cr, current.kind)
        return cr

    async def start_step(
        self, cr: ChangeRequest, kind: ArtifactKind | str | None = None
    ) -> ChangeRequest:
        """Draft the clarifying questions for ``kind`` (default: the current step)."""
        self._require_started(cr)
        step = self._step(cr, kind)
        self._check_reachable(cr, step)
        if step.status not in (StepStatus.PENDING, StepStatus.ASKING) or step.questions:
            return cr  # already asked (or past asking) — idempotent
        brief = await self.brief(cr, step.kind)
        drafted = await self._agent.draft_questions(step.kind, brief.text)
        step.questions = [
            WizardQuestion(text=q.question.strip(), why=q.why.strip(), options=q.options)
            for q in drafted.questions[: self._max_questions]
            if q.question.strip()
        ]
        step.status = StepStatus.ASKING
        step.started_at = step.started_at or cr.wizard.updated_at
        if step.questions:
            step.say(
                "assistant",
                f"Before drafting the {STEP_LABELS[step.kind].lower()} I have "
                f"{len(step.questions)} question(s). Answer, skip, or draft now.",
                "status",
            )
            for q in step.questions:
                step.say("assistant", q.text, "question")
        else:
            step.say("assistant", "No clarifying questions — you can draft now.", "status")
        cr.touch()
        return cr

    # ---------------------------------------------------------- answer/skip
    async def answer(
        self, cr: ChangeRequest, answer: str, *, option: str | None = None
    ) -> AnswerOutcome:
        self._require_started(cr)
        step = self._step(cr, None)
        question = step.current_question
        if question is None:
            raise WizardStateError("No question is awaiting an answer on the current step.")
        text = answer.strip()
        if not text:
            raise CompilationError("The answer is empty.")
        prior = question.followups[-1] if question.followups else None
        step.say("user", text, "answer")
        note = await self._agent.interpret_answer(
            step.kind,
            question=question.prompt,
            answer=text,
            brief_context=self.brief_lite(cr, step),
            prior_followup=prior,
        )
        question.answer = text if question.answer is None else f"{question.answer}\n{text}"
        question.chosen_option = option if option and option == text else question.chosen_option
        if not note.resolved and note.followup_question and not prior:
            question.followups.append(note.followup_question.strip())
            question.followup_options = note.followup_options
            step.say("assistant", note.followup_question.strip(), "followup")
            cr.touch()
            return AnswerOutcome(question=question, followup=True, step=step)
        line = (note.note or text).strip()
        question.note = line
        question.status = WizardQuestionStatus.ANSWERED
        step.notes.append(line)
        step.say("assistant", f"Noted: {line}", "note")
        cr.touch()
        return AnswerOutcome(question=question, followup=False, step=step)

    def skip(self, cr: ChangeRequest) -> ChangeRequest:
        self._require_started(cr)
        step = self._step(cr, None)
        question = step.current_question
        if question is None:
            raise WizardStateError("No question is awaiting an answer on the current step.")
        question.status = WizardQuestionStatus.SKIPPED
        step.say("user", "(skipped)", "answer")
        cr.touch()
        return cr

    # ---------------------------------------------------------------- draft
    async def draft(
        self,
        cr: ChangeRequest,
        kind: ArtifactKind | str | None = None,
        *,
        progress: ProgressFn | None = None,
    ) -> ChangeRequest:
        """Draft (or re-draft) the artifact of ``kind``; unanswered questions are skipped."""
        self._require_started(cr)
        step = self._step(cr, kind)
        self._check_reachable(cr, step)
        for question in step.questions:
            if question.status == WizardQuestionStatus.PENDING:
                question.status = WizardQuestionStatus.SKIPPED
        report = progress or (lambda message, done, total: None)
        step.status = StepStatus.DRAFTING
        step.error = None
        try:
            report("assembling brief", 0, 0)
            brief = await self.brief(cr, step.kind)
            if step.kind == ArtifactKind.IMPACT:
                markdown, note = await self._draft_impact(cr, brief, report)
            elif step.kind == ArtifactKind.EPIC:
                markdown, note = await self._draft_epic(cr, brief, report)
            elif step.kind == ArtifactKind.STORIES:
                markdown, note = await self._draft_stories(cr, brief, report)
            else:
                markdown, note = await self._draft_tdd(cr, brief, report)
        except Exception as exc:
            step.status = StepStatus.ASKING if step.questions else StepStatus.PENDING
            if cr.artifacts.get(step.kind).version:
                step.status = StepStatus.DRAFTED
            step.error = str(exc)
            step.say("assistant", f"Drafting failed: {exc}", "status")
            cr.touch()
            raise
        artifact = cr.artifacts.get(step.kind)
        artifact.add_version(markdown, VersionSource.LLM_DRAFT, note)
        artifact.status = ArtifactStatus.DRAFTED
        artifact.sources = brief.sources
        artifact.coverage = brief.coverage
        step.status = StepStatus.DRAFTED
        step.drafted_at = cr.wizard.updated_at
        step.say(
            "assistant", f"Drafted {STEP_LABELS[step.kind]} v{artifact.version}: {note}", "draft"
        )
        cr.touch()
        return cr

    async def _draft_impact(
        self, cr: ChangeRequest, brief: Brief, report: ProgressFn
    ) -> tuple[str, str]:
        report("drafting impact analysis", 0, 1)
        plan = await self._agent.draft_impact(brief.text)
        affected = []
        for item in plan.affected:
            change = item.change_type.strip().lower()
            if change not in {c.value for c in ChangeType}:
                change = ChangeType.MODIFY.value
            affected.append(item.model_copy(update={"change_type": change}))
        # Every requirement gets a row even if the model dropped one.
        seen = {r.req_id for r in plan.requirements}
        reqs = list(plan.requirements) + [
            RequirementImpact(req_id=r.id, requirement=r.text, impact="(not assessed)")
            for r in cr.requirements
            if r.id not in seen
        ]
        doc = ImpactDoc(
            title=cr.title,
            cr_id=cr.doc_id,
            target_workflow=cr.bcr_meta.target_workflow or "",
            kb_name=cr.kb_name,
            status="Draft",
            summary=plan.summary,
            requirements=reqs,
            affected=affected,
            design_impacts=plan.design_impacts,
            risks=plan.risks,
            open_decisions=plan.open_decisions,
            kg_rows=cr.impact_table,
            coverage_note=brief.coverage_note,
            sources=brief.sources,
        )
        report("rendering", 1, 1)
        return render_impact(doc), f"{len(affected)} affected components, {len(reqs)} requirements"

    async def _draft_epic(
        self, cr: ChangeRequest, brief: Brief, report: ProgressFn
    ) -> tuple[str, str]:
        report("drafting epic", 0, 1)
        catalog = await self._kg.catalog(cr.kb_id)
        first_story = idmod.story_ids(catalog, 1)[0]
        plan = await self._agent.draft_epic(
            brief.text, epic_id=cr.ids.epic_id, story_id_hint=first_story
        )
        epic: EpicDoc = plan.epic
        epic.id = cr.ids.epic_id
        epic.title = epic.title.strip() or cr.title
        epic.linked_bcr = epic.linked_bcr or cr.doc_id
        epic.status = epic.status or "Proposed"
        rows = [row for row in epic.story_map if row.title.strip()]
        new_ids = idmod.story_ids(catalog, len(rows))
        cr.ids.story_ids = new_ids
        epic.story_map = [
            StoryMapRow(id=sid, title=row.title.strip(), status=row.status or "Proposed", doc="")
            for sid, row in zip(new_ids, rows, strict=True)
        ]
        if len(epic.dod_done) < len(epic.dod):
            epic.dod_done = list(epic.dod_done) + [False] * (len(epic.dod) - len(epic.dod_done))
        epic.coverage_note = brief.coverage_note
        epic.sources = brief.sources
        report("rendering", 1, 1)
        return render_epic(epic), f"{epic.id} with {len(epic.story_map)} stories in the story map"

    async def _draft_stories(
        self, cr: ChangeRequest, brief: Brief, report: ProgressFn
    ) -> tuple[str, str]:
        epic_art = cr.artifacts.epic
        if not epic_art.markdown:
            raise WizardStateError("Draft and approve the EPIC before drafting its stories.")
        epic = parse_epic(epic_art.markdown)
        specs = [(row.id, row.title) for row in epic.story_map if row.id and row.title]
        if not specs:
            raise CompilationError("The EPIC's story map is empty — add stories to it first.")
        epic_ref = f"{epic.id} — {epic.title}".strip(" —")
        drafted: dict[str, StoryDoc] = {}
        batches = [specs[i : i + _STORY_BATCH] for i in range(0, len(specs), _STORY_BATCH)]
        for n, batch in enumerate(batches):
            report(f"drafting stories {batch[0][0]}…{batch[-1][0]}", n, len(batches))
            plan = await self._agent.draft_stories(brief.text, epic_ref=epic_ref, stories=batch)
            for i, story in enumerate(plan.stories):
                key = story.id.strip()
                if key not in {sid for sid, _ in batch}:
                    key = batch[i][0] if i < len(batch) else ""
                if key and key not in drafted:
                    drafted[key] = story
        stories: list[StoryDoc] = []
        for sid, title in specs:
            story = drafted.get(sid) or StoryDoc(id=sid, title=title, notes="(not drafted)")
            story.id = sid
            story.title = story.title.strip() or title
            story.epic = story.epic or epic_ref
            story.status = story.status or "Proposed"
            stories.append(story)
        doc = StoriesDoc(
            epic_id=epic.id,
            epic_title=epic.title,
            linked_bcr=cr.doc_id,
            stories=stories,
            coverage_note=brief.coverage_note,
            sources=brief.sources,
        )
        report("rendering", len(batches), len(batches))
        return render_stories(doc), f"{len(stories)} stories ({specs[0][0]}…{specs[-1][0]})"

    async def _draft_tdd(
        self, cr: ChangeRequest, brief: Brief, report: ProgressFn
    ) -> tuple[str, str]:
        by_key = {key: (number, title) for key, number, title in TDD_SECTIONS}
        drafted: dict[str, TddSection] = {}
        diagrams: list[str] = []
        for n, chunk in enumerate(_TDD_CHUNKS):
            spec = [(key, *by_key[key]) for key in chunk]
            report(f"drafting TDD sections {spec[0][1]}-{spec[-1][1]}", n, len(_TDD_CHUNKS))
            plan = await self._agent.draft_tdd_sections(
                brief.text,
                tdd_id=cr.ids.tdd_id,
                prior_tdd_id=cr.ids.prior_tdd_id or "",
                sections=spec,
            )
            for section in plan.sections:
                key = section.key.strip()
                if key in by_key and key not in drafted:
                    number, title = by_key[key]
                    drafted[key] = TddSection(
                        key=key,
                        number=number,
                        title=title,
                        existing=section.existing.strip(),
                        proposed=section.proposed.strip(),
                    )
            for name in plan.diagrams_needed:
                if name.strip() and name.strip() not in diagrams:
                    diagrams.append(name.strip())
        sections = [
            drafted.get(key)
            or TddSection(key=key, number=number, title=title, existing="", proposed="")
            for key, number, title in TDD_SECTIONS
        ]
        target = cr.bcr_meta.target_workflow or "Workflow"
        workflow_name = target.split("(")[0].strip()
        doc = TddDoc(
            id=cr.ids.tdd_id,
            title=f"{workflow_name} — Temporal Implementation ({cr.title})",
            linked_epic=cr.ids.epic_id,
            supersedes=cr.ids.prior_tdd_id or "",
            version="0.1",
            status="Draft",
            author="Platform Engineering",
            sections=sections,
            diagrams_needed=diagrams,
            coverage_note=brief.coverage_note,
            sources=brief.sources,
        )
        report("rendering", len(_TDD_CHUNKS), len(_TDD_CHUNKS))
        missing = [s.number for s in sections if not s.proposed]
        note = f"{cr.ids.tdd_id}: {len(sections) - len(missing)}/{len(sections)} sections drafted"
        if missing:
            note += f" (empty: {', '.join(missing)})"
        return render_tdd(doc), note

    # --------------------------------------------------------------- revise
    async def revise(
        self, cr: ChangeRequest, kind: ArtifactKind | str, message: str
    ) -> ChangeRequest:
        self._require_started(cr)
        step = self._step(cr, kind)
        artifact = cr.artifacts.get(step.kind)
        if not artifact.markdown:
            raise WizardStateError(f"Nothing to revise — draft the {STEP_LABELS[step.kind]} first.")
        instruction = message.strip()
        if not instruction:
            raise CompilationError("The revision message is empty.")
        step.say("user", instruction, "message")
        brief = await self.brief(cr, step.kind)
        revision = await self._agent.revise(
            step.kind,
            markdown=artifact.markdown,
            instruction=instruction,
            brief_context=brief.text[:24_000],
        )
        markdown = revision.markdown.strip()
        if not markdown:
            raise CompilationError("The model returned an empty revision.")
        markdown = self._ensure_parses(step.kind, markdown + "\n")
        summary = revision.summary.strip() or "Revised as instructed."
        if markdown.strip() == artifact.markdown.strip():
            step.say("assistant", summary, "status")
            cr.touch()
            return cr
        artifact.add_version(markdown, VersionSource.LLM_REVISION, summary)
        if artifact.status == ArtifactStatus.APPROVED:
            artifact.status = ArtifactStatus.DRAFTED
            step.status = StepStatus.DRAFTED
        step.say("assistant", f"v{artifact.version}: {summary}", "revision")
        cr.touch()
        return cr

    def edit(
        self, cr: ChangeRequest, kind: ArtifactKind | str, markdown: str, *, note: str = ""
    ) -> ChangeRequest:
        """A human edit is a new ``human_edit`` version (the markdown must still parse)."""
        step = cr.wizard.step(kind)
        artifact = cr.artifacts.get(step.kind)
        text = markdown.replace("\r\n", "\n").rstrip() + "\n"
        if not text.strip():
            raise CompilationError("The edited markdown is empty.")
        text = self._ensure_parses(step.kind, text)
        if text.strip() == artifact.markdown.strip():
            return cr
        artifact.add_version(text, VersionSource.HUMAN_EDIT, note or "Edited by hand.")
        if artifact.status == ArtifactStatus.APPROVED:
            artifact.status = ArtifactStatus.DRAFTED
        if step.status in (StepStatus.PENDING, StepStatus.ASKING, StepStatus.APPROVED):
            step.status = StepStatus.DRAFTED
        step.say(
            "user", f"Edited the {STEP_LABELS[step.kind].lower()} (v{artifact.version}).", "edit"
        )
        cr.touch()
        return cr

    def approve(self, cr: ChangeRequest, kind: ArtifactKind | str | None = None) -> ChangeRequest:
        step = self._step(cr, kind)
        artifact = cr.artifacts.get(step.kind)
        if not artifact.markdown:
            raise WizardStateError(f"Draft the {STEP_LABELS[step.kind]} before approving it.")
        index = cr.wizard.index_of(step.kind)
        if index > cr.wizard.cursor:
            self._check_reachable(cr, step)
        artifact.status = ArtifactStatus.APPROVED
        artifact.approved_at = cr.wizard.updated_at
        step.status = StepStatus.APPROVED
        step.approved_at = cr.wizard.updated_at
        step.say("user", f"Approved v{artifact.version}.", "approve")
        if index == cr.wizard.cursor:
            cr.wizard.cursor = index + 1
        if all(a.status == ArtifactStatus.APPROVED for a in cr.artifacts.all()):
            cr.stage = ChangeRequestStage.COMPLETE
        else:
            cr.stage = ChangeRequestStage.IN_PROGRESS
        cr.touch()
        return cr

    @staticmethod
    def _ensure_parses(kind: ArtifactKind, markdown: str) -> str:
        try:
            parse_artifact(kind.value, markdown)
        except ArtifactParseError as exc:
            raise CompilationError(
                f"The {STEP_LABELS[kind].lower()} markdown lost its structure: {exc}"
            ) from exc
        return markdown

    # ---------------------------------------------------------------- brief
    async def _impact_rows(self, cr: ChangeRequest) -> list[ImpactTableRow]:
        seeds = list(cr.impact_seed_terms)
        if cr.bcr_meta.doc_id:
            seeds.insert(0, cr.bcr_meta.doc_id)
        if not seeds:
            return []
        rows = await self._kg.impact(cr.kb_id, seeds, max_hops=self._impact_hops)
        kept = [
            ImpactTableRow(
                node_id=r.node_id, type=r.type, name=r.name, path=r.path, hops=r.hops, via=r.via
            )
            for r in rows
            if r.type in _IMPACT_ROW_TYPES
        ]
        return kept[: self._max_impact_rows]

    def _queries(self, cr: ChangeRequest, kind: ArtifactKind) -> list[str]:
        queries: list[str] = []
        head = f"{cr.doc_id} {cr.title}".strip()
        queries.append(head)
        queries += [r.text for r in cr.requirements]
        terms = list(cr.impact_seed_terms)
        for i in range(0, len(terms), 6):
            queries.append(" ".join(terms[i : i + 6]))
        queries += list(_STEP_QUERIES.get(kind, ()))
        seen: set[str] = set()
        out: list[str] = []
        for q in queries:
            key = q.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(q.strip())
        return out

    async def brief(self, cr: ChangeRequest, kind: ArtifactKind | str) -> Brief:
        """Assemble the drafting brief for a step (KB retrievals + deterministic tables)."""
        step_kind = ArtifactKind(kind)
        packets: list[KgPacket] = []
        for query in self._queries(cr, step_kind):
            try:
                packets.append(
                    await self._kg.retrieve(cr.kb_id, query, budget=self._per_query_budget)
                )
            except Exception as exc:  # pragma: no cover - retrieval must never block drafting
                log.warning("kg retrieve failed for %r: %s", query, exc)
        sections, sources = _pack_sections(packets, self._total_budget)
        coverage = sum(p.coverage for p in packets) / len(packets) if packets else 0.0
        uncovered: list[str] = []
        for p in packets:
            for term in p.uncovered_terms:
                if term not in uncovered:
                    uncovered.append(term)
        note = ""
        if packets and coverage < 0.8:
            note = (
                f"Retrieval coverage {coverage:.0%} — terms not found in the knowledge base: "
                + ", ".join(uncovered[:12])
            )
        elif not packets:
            note = "No knowledge-base context could be retrieved for this artifact."
        text = self._brief_text(cr, step_kind, sections, note)
        return Brief(
            text=text, sources=sources, coverage=coverage, coverage_note=note, packets=packets
        )

    def brief_lite(self, cr: ChangeRequest, step: WizardStep) -> str:
        parts = [f"Change request {cr.doc_id} — {cr.title}", ""]
        parts += [f"- {r.id}: {r.text}" for r in cr.requirements]
        parts += ["", "Assigned ids: " + self._ids_line(cr)]
        if step.notes:
            parts += ["", "Decisions so far:"] + [f"- {n}" for n in step.notes]
        return "\n".join(parts)

    @staticmethod
    def _ids_line(cr: ChangeRequest) -> str:
        bits = [f"new EPIC {cr.ids.epic_id}"]
        if cr.ids.prior_epic_id:
            bits[-1] += f" (extends {cr.ids.prior_epic_id})"
        if cr.ids.story_ids:
            bits.append(f"stories {cr.ids.story_ids[0]}…{cr.ids.story_ids[-1]}")
        bits.append(
            f"new TDD {cr.ids.tdd_id}"
            + (f" (supersedes {cr.ids.prior_tdd_id})" if cr.ids.prior_tdd_id else "")
        )
        if cr.ids.next_test_case:
            bits.append(f"next test case {cr.ids.next_test_case}")
        return "; ".join(bits)

    def _brief_text(
        self, cr: ChangeRequest, kind: ArtifactKind, sections: Sequence[KgSection], note: str
    ) -> str:
        lines: list[str] = []
        src = f" (source file: {cr.source_filename})" if cr.source_filename else ""
        lines += [
            f"### Change request {cr.doc_id} — {cr.title}{src}",
            "",
            cr.document_text.strip(),
            "",
        ]
        if cr.requirements:
            lines += ["### Requirements"] + [f"- {r.id}: {r.text}" for r in cr.requirements] + [""]
        lines += [
            "### Assigned identifiers (use verbatim; never invent others)",
            f"- {self._ids_line(cr)}",
            "",
        ]
        step = cr.wizard.step(kind)
        lines += ["### Requester decisions from the clarifying questions"]
        lines += [f"- {n}" for n in step.notes] or ["- (none yet)"]
        lines.append("")
        if cr.impact_table:
            lines += [
                "### Deterministic knowledge-graph impact traversal "
                f"(seeds from the change request → {self._impact_hops} hops)",
                "",
                "| Hops | Type | Node | Path |",
                "| --- | --- | --- | --- |",
            ]
            lines += [
                f"| {r.hops} | {r.type} | {r.name} | {r.path or ''} |" for r in cr.impact_table
            ]
            lines.append("")
        lines += ["### Knowledge-graph excerpts (real names, paths and line spans)"]
        if note:
            lines += [f"> {note}"]
        lines.append("")
        for section in sections:
            where = section.path or section.node_id
            span = (
                f" — lines {section.start_line}-{section.end_line}"
                if section.start_line and section.end_line
                else ""
            )
            lines += [f"#### `{where}`{span} [{section.band}]", "", section.text.strip(), ""]
        prior = [k for k in WIZARD_ORDER if k != kind and cr.artifacts.get(k).markdown]
        if prior:
            lines += ["### Artifacts already drafted/approved for this change"]
            for k in prior:
                art = cr.artifacts.get(k)
                lines += [
                    f"#### {STEP_LABELS[k]} (v{art.version}, {art.status.value})",
                    "",
                    art.markdown.strip(),
                    "",
                ]
        return "\n".join(lines).strip() + "\n"


def _pack_sections(
    packets: Sequence[KgPacket], budget: int
) -> tuple[list[KgSection], list[SourceRef]]:
    """Round-robin sections across packets, dedupe by node id, stop at ``budget`` tokens."""
    seen: set[str] = set()
    picked: list[KgSection] = []
    used = 0
    depth = 0
    exhausted = False
    while not exhausted:
        exhausted = True
        for packet in packets:
            if depth < len(packet.sections):
                exhausted = False
                section = packet.sections[depth]
                key = section.node_id or f"{section.path}:{section.start_line}"
                if key in seen:
                    continue
                if used + section.tokens > budget and picked:
                    continue
                seen.add(key)
                picked.append(section)
                used += section.tokens
        depth += 1
    sources: dict[str, SourceRef] = {}
    for section in picked:
        if not section.path:
            continue
        ref = sources.setdefault(section.path, SourceRef(path=section.path, spans=[]))
        if section.start_line and section.end_line:
            span = (section.start_line, section.end_line)
            if span not in ref.spans:
                ref.spans.append(span)
    for ref in sources.values():
        ref.spans.sort()
    return picked, sorted(sources.values(), key=lambda r: r.path)

"""ProjectCompiler: the spec-centric front-end orchestrator.

Layered **on top of** :class:`WorkflowCompiler` (which is unchanged for the
classic single-document path), the project compiler drives the spec-centric
pipeline::

    document → segmentation → per-workflow discovery + facts → WorkflowSpecs
             → spec files on disk               [HUMAN GATE: edit ⇄ validate]
             → approve → per-workflow back-end (graph → auto-review ≥ threshold
               → CVPA → Temporal design → code)

The human reviews and edits Markdown spec files; :mod:`workflow_compiler.spec`
folds edits back onto the structured models. Approval seeds one
:class:`WorkflowState` per spec and hands it to the existing back-end via
``WorkflowCompiler.compile_prepared`` — the per-workflow pipeline does not know
the project exists.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from workflow_compiler.agents.segmentation import WorkflowSegmentationAgent
from workflow_compiler.checklist import amend as checklist_amend
from workflow_compiler.compiler import (
    ProgressCallback,
    ProgressEvent,
    WorkflowCompiler,
    _emit,
)
from workflow_compiler.exceptions import ApprovalError, CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    ApprovalStatus,
    CompilationProject,
    CompilationStage,
    ProjectStage,
    Provenance,
    SpecItem,
    WorkflowFacts,
    WorkflowMetadata,
    WorkflowSpec,
    WorkflowState,
)
from workflow_compiler.prompts import PromptManager
from workflow_compiler.spec import SpecValidator, ingest_spec_markdown, render_spec
from workflow_compiler.storage.project_store import FileProjectStore, ProjectStore

if TYPE_CHECKING:
    from workflow_compiler.config import Settings

#: Filename of the project-level summary written next to the spec files.
OVERVIEW_FILENAME = "overview.md"


class ProjectCompiler:
    """Compile a document into reviewed specs, then each spec into artifacts."""

    def __init__(
        self,
        *,
        llm_provider: BaseLLMProvider | None = None,
        workflow_compiler: WorkflowCompiler | None = None,
        project_store: ProjectStore | None = None,
        prompt_manager: PromptManager | None = None,
        segmentation_review: bool = True,
        graph_health_threshold: float = 0.9,
    ) -> None:
        """Wire the front-end collaborators around an inner workflow compiler."""
        self._llm = llm_provider
        self._prompts = prompt_manager or PromptManager()
        self._compiler = workflow_compiler or WorkflowCompiler(
            llm_provider=llm_provider, prompt_manager=self._prompts
        )
        self._projects: ProjectStore = project_store or FileProjectStore()
        self._segmentation = WorkflowSegmentationAgent(
            llm_provider, prompt_manager=self._prompts, review_enabled=segmentation_review
        )
        self._validator = SpecValidator(llm_provider, prompt_manager=self._prompts)
        self._threshold = graph_health_threshold

    @classmethod
    def from_settings(
        cls,
        *,
        llm_provider: BaseLLMProvider | None = None,
        settings: Settings | None = None,
    ) -> ProjectCompiler:
        """Build a fully wired project compiler from application settings."""
        from workflow_compiler.config import get_settings
        from workflow_compiler.llm import ProviderFactory

        resolved = settings or get_settings()
        provider = llm_provider or ProviderFactory().from_settings(resolved)
        return cls(
            llm_provider=provider,
            workflow_compiler=WorkflowCompiler.from_settings(
                llm_provider=provider, settings=resolved
            ),
            project_store=FileProjectStore(resolved.state_store_path),
            graph_health_threshold=resolved.graph_health_threshold,
        )

    @property
    def workflow_compiler(self) -> WorkflowCompiler:
        """The inner per-workflow compiler (back-end)."""
        return self._compiler

    # ------------------------------------------------------------------ #
    # Stage 1: document → project with drafted specs
    # ------------------------------------------------------------------ #

    async def compile_document(
        self,
        document_text: str,
        *,
        persist: bool = True,
        project_id: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> CompilationProject:
        """Segment the document and draft one reviewed spec per workflow.

        Stops at the spec gate (``SPEC_DRAFTED``): the caller renders the spec
        files for the user, who edits them and drives ``validate_specs`` /
        ``approve_spec``.
        """
        if not document_text or not document_text.strip():
            raise CompilationError("Cannot compile an empty document.")

        project = CompilationProject(document_text=document_text)
        if project_id is not None:
            project.project_id = project_id

        _emit(progress, ProgressEvent(
            phase="agent", name=self._segmentation.name, status="start", index=1, total=2,
        ))
        started = time.perf_counter()
        self._segmentation.set_progress(self._sub_reporter(progress))
        try:
            segments, references, warnings = await self._segmentation.run(document_text)
        finally:
            self._segmentation.set_progress(None)
        project.segments = segments
        project.cross_references = references
        project.warnings = warnings
        project.stage = ProjectStage.WORKFLOWS_DISCOVERED
        _emit(progress, ProgressEvent(
            phase="agent", name=self._segmentation.name, status="done", index=1, total=2,
            seconds=time.perf_counter() - started, stage=project.stage.value,
        ))

        total = len(segments)
        for index, segment in enumerate(segments, start=1):
            name = f"extract:{segment.slug}"
            _emit(progress, ProgressEvent(
                phase="agent", name=name, status="start", index=index, total=total,
            ))
            seg_started = time.perf_counter()
            state = await self._compiler.extract_facts(
                segment.text, project_id=project.project_id
            )
            project.specs.append(self._build_spec(segment.slug, state))
            _emit(progress, ProgressEvent(
                phase="agent", name=name, status="done", index=index, total=total,
                seconds=time.perf_counter() - seg_started, stage=state.stage.value,
            ))

        project.stage = ProjectStage.SPEC_DRAFTED
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    @staticmethod
    def _build_spec(slug: str, state: WorkflowState) -> WorkflowSpec:
        """Assemble a WorkflowSpec from an extracted state (checklist absorbed)."""
        metadata = state.workflow_metadata or WorkflowMetadata(name=slug)
        spec = WorkflowSpec(
            slug=slug,
            metadata=metadata,
            facts=state.workflow_facts or WorkflowFacts(),
        )
        # Absorb the readiness checklist: every uncleared item becomes an open
        # question the user answers in the spec file (replacing the old form).
        if state.checklist is not None:
            for item in state.checklist.needs_input():
                spec.open_questions.append(
                    SpecItem(
                        text=item.question or item.requirement,
                        ref=item.id,
                        provenance=Provenance.LLM_INFERRED,
                    )
                )
        return spec

    # ------------------------------------------------------------------ #
    # Stage 2: the edit ⇄ validate loop
    # ------------------------------------------------------------------ #

    async def validate_specs(
        self,
        project_id: str,
        *,
        markdown_by_slug: dict[str, str] | None = None,
        persist: bool = True,
        progress: ProgressCallback | None = None,
    ) -> CompilationProject:
        """Fold edited spec files back in, then run the three validator passes.

        ``markdown_by_slug`` carries the (possibly edited) file contents; specs
        without an entry are validated as stored. Findings land in
        ``project.validation_findings[slug]``.
        """
        project = await self._projects.load(project_id)
        findings_by_slug: dict[str, list[str]] = {}
        total = len(project.specs)

        for index, spec in enumerate(list(project.specs), start=1):
            name = f"validate:{spec.slug}"
            _emit(progress, ProgressEvent(
                phase="review", name=name, status="start", index=index, total=total,
            ))
            started = time.perf_counter()
            findings: list[str] = []
            current = spec
            markdown = (markdown_by_slug or {}).get(spec.slug)
            if markdown is not None:
                result = ingest_spec_markdown(
                    current, markdown, project.document_text, project.cross_references
                )
                current = result.spec
                project.cross_references = result.cross_references
                findings.extend(f"ingest: {c}" for c in result.changes)
                findings.extend(f"ingest warning: {w}" for w in result.warnings)
            current, validator_findings, _note = await self._validator.validate(
                current, project.document_text, project.cross_references
            )
            findings.extend(validator_findings)
            findings_by_slug[spec.slug] = findings
            self._replace_spec(project, current)
            _emit(progress, ProgressEvent(
                phase="review", name=name, status="done", index=index, total=total,
                seconds=time.perf_counter() - started,
            ))

        project.validation_findings = findings_by_slug
        project.stage = ProjectStage.SPEC_VALIDATED
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    async def update_specs(
        self,
        project_id: str,
        markdown_by_slug: dict[str, str],
        *,
        persist: bool = True,
    ) -> CompilationProject:
        """Deterministically fold edited spec files in — no validator, no LLM.

        The quick-save path (e.g. the API's ``PUT /projects/{id}/spec``): edits
        are parsed, merged, provenance-recorded, and referential integrity is
        re-enforced, but the three review passes do not run.
        """
        project = await self._projects.load(project_id)
        for spec in list(project.specs):
            markdown = markdown_by_slug.get(spec.slug)
            if markdown is None:
                continue
            result = ingest_spec_markdown(
                spec, markdown, project.document_text, project.cross_references
            )
            project.cross_references = result.cross_references
            self._replace_spec(project, result.spec)
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    # ------------------------------------------------------------------ #
    # Stage 3: approval → per-workflow back-end
    # ------------------------------------------------------------------ #

    async def approve_spec(
        self,
        project_id: str,
        *,
        workflows: list[str] | None = None,
        reviewer: str | None = None,
        markdown_by_slug: dict[str, str] | None = None,
        accept_incomplete: bool = False,
        allow_unconfirmed_references: bool = False,
        persist: bool = True,
        progress: ProgressCallback | None = None,
    ) -> CompilationProject:
        """Approve the specs and compile each workflow through the back-end.

        For every selected spec a :class:`WorkflowState` is seeded from the
        approved specification (its ``document_text`` is the rendered spec, so
        downstream prompts see the normalized artifact, not the original
        document) and run through graph → review → CVPA → Temporal design →
        code. The graph review acts as an automatic gate: health at or above
        the configured threshold continues, below it the workflow is left
        pending and the project is marked ``NEEDS_ATTENTION``.
        """
        project = await self._projects.load(project_id)

        if markdown_by_slug:
            for spec in list(project.specs):
                markdown = markdown_by_slug.get(spec.slug)
                if markdown is None:
                    continue
                result = ingest_spec_markdown(
                    spec, markdown, project.document_text, project.cross_references
                )
                project.cross_references = result.cross_references
                self._replace_spec(project, result.spec)

        selected = [
            spec
            for spec in project.specs
            if workflows is None or spec.slug in workflows
        ]
        if not selected:
            raise ApprovalError(f"Project {project_id!r} has no matching specs to approve.")

        unconfirmed = [
            r
            for r in project.cross_references
            if not r.user_confirmed
            and any(
                s.slug in (r.source_workflow, r.target_workflow) for s in selected
            )
        ]
        if unconfirmed and not allow_unconfirmed_references:
            links = ", ".join(
                f"{r.source_workflow}.{r.output_field} -> "
                f"{r.target_workflow}.{r.input_field}"
                for r in unconfirmed
            )
            raise ApprovalError(
                "Unconfirmed cross-workflow dependencies must be validated before "
                f"approval (tick their checkbox in the spec files): {links}"
            )

        project.spec_approval_status = ApprovalStatus.APPROVED
        project.stage = ProjectStage.COMPILING
        needs_attention = False
        total = len(selected)

        for index, spec in enumerate(selected, start=1):
            name = f"compile:{spec.slug}"
            _emit(progress, ProgressEvent(
                phase="approve", name=name, status="start", index=index, total=total,
            ))
            started = time.perf_counter()
            state = self._seed_state(project, spec)
            state = checklist_amend.apply(
                state, self._answers(spec), accept_as_is=accept_incomplete
            )
            if state.checklist is not None and not state.checklist.is_satisfied():
                unmet = [item.id for item in state.checklist.unmet_required()]
                project.validation_findings.setdefault(spec.slug, []).append(
                    "blocked: unmet required checklist items "
                    f"{unmet} — answer the open questions in the spec file "
                    "or approve with accept_incomplete"
                )
                needs_attention = True
                _emit(progress, ProgressEvent(
                    phase="approve", name=name, status="done", index=index, total=total,
                    seconds=time.perf_counter() - started, stage="blocked",
                ))
                continue
            state = await self._compiler.compile_prepared(
                state,
                review_mode=True,
                persist=persist,
                auto_approve_threshold=self._threshold,
                reviewer=reviewer,
                progress=progress,
            )
            project.workflow_ids[spec.slug] = state.workflow_id
            if state.stage != CompilationStage.COMPLETED:
                needs_attention = True
                report = state.review_report
                issues = [issue.message for issue in report.errors] if report else []
                health = (
                    report.health_score
                    if report is not None and report.health_score is not None
                    else 0.0
                )
                project.validation_findings.setdefault(spec.slug, []).append(
                    f"graph health {health:.2f} below threshold {self._threshold:.2f} — "
                    "left pending for manual review"
                    + (f"; issues: {'; '.join(issues)}" if issues else "")
                )
            _emit(progress, ProgressEvent(
                phase="approve", name=name, status="done", index=index, total=total,
                seconds=time.perf_counter() - started, stage=state.stage.value,
            ))

        project.stage = (
            ProjectStage.NEEDS_ATTENTION if needs_attention else ProjectStage.COMPLETED
        )
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    def _seed_state(self, project: CompilationProject, spec: WorkflowSpec) -> WorkflowState:
        """Build the back-end input state from an approved spec.

        The state's ``document_text`` is the **rendered spec**, not the original
        document: downstream stages (Temporal design prompts, checklist,
        grounding) operate on the normalized, human-approved artifact.
        """
        rendered = render_spec(spec, project.cross_references)
        state = WorkflowState(document_text=rendered, project_id=project.project_id)
        state.workflow_metadata = spec.metadata.model_copy(deep=True)
        state.workflow_facts = spec.facts.model_copy(deep=True)
        state.stage = CompilationStage.FACTS_EXTRACTED
        return state

    @staticmethod
    def _answers(spec: WorkflowSpec) -> dict[str, str]:
        """Checklist answers folded from the spec's answered open questions."""
        return {
            question.ref: question.answer or ""
            for question in spec.open_questions
            if question.ref and question.answer
        }

    @staticmethod
    def _replace_spec(project: CompilationProject, spec: WorkflowSpec) -> None:
        project.specs = [spec if s.slug == spec.slug else s for s in project.specs]

    @staticmethod
    def _sub_reporter(progress: ProgressCallback | None) -> object:
        return WorkflowCompiler._sub_reporter(progress)

    # ------------------------------------------------------------------ #
    # Persistence + spec files on disk
    # ------------------------------------------------------------------ #

    async def load_project(self, project_id: str) -> CompilationProject:
        """Load a stored project by id."""
        return await self._projects.load(project_id)

    async def save_project(self, project: CompilationProject) -> None:
        """Persist a project."""
        await self._projects.save(project)

    async def list_projects(self) -> list[str]:
        """Return the ids of all stored projects."""
        return await self._projects.list_ids()

    def write_spec_files(self, project: CompilationProject, directory: str | Path) -> list[Path]:
        """Write ``overview.md`` plus one ``<slug>.md`` per spec; return the paths."""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for spec in project.specs:
            path = root / f"{spec.slug}.md"
            path.write_text(
                render_spec(spec, project.cross_references), encoding="utf-8"
            )
            paths.append(path)
        overview = root / OVERVIEW_FILENAME
        overview.write_text(self.render_overview(project), encoding="utf-8")
        paths.append(overview)
        return paths

    @staticmethod
    def read_spec_files(
        project: CompilationProject, directory: str | Path
    ) -> dict[str, str]:
        """Read the spec files present in ``directory`` keyed by slug."""
        root = Path(directory)
        contents: dict[str, str] = {}
        for spec in project.specs:
            path = root / f"{spec.slug}.md"
            if path.is_file():
                contents[spec.slug] = path.read_text(encoding="utf-8")
        return contents

    @staticmethod
    def render_overview(project: CompilationProject) -> str:
        """Render the read-only project summary (overview.md)."""
        lines = [
            "# Workflow Specification Project",
            "",
            f"- project id: `{project.project_id}`",
            f"- stage: {project.stage.value}",
            f"- spec approval: {project.spec_approval_status.value}",
            "",
            "## Workflows",
        ]
        for spec in project.specs:
            questions = len(spec.unresolved_questions())
            suffix = f" — {questions} open question(s)" if questions else ""
            lines.append(f"- `{spec.slug}.md` — {spec.metadata.name}{suffix}")
        lines += ["", "## Cross-Workflow Dependencies"]
        if project.cross_references:
            for r in project.cross_references:
                status = "confirmed" if r.user_confirmed else "UNCONFIRMED"
                lines.append(
                    f"- {r.source_workflow}.`{r.output_field}` → "
                    f"{r.target_workflow}.`{r.input_field}` ({status})"
                )
        else:
            lines.append("- none")
        if project.warnings:
            lines += ["", "## Warnings"]
            lines += [f"- {w}" for w in project.warnings]
        if project.validation_findings:
            lines += ["", "## Latest Validation Findings"]
            for slug, findings in project.validation_findings.items():
                lines.append(f"### {slug}")
                lines += [f"- {f}" for f in findings] or ["- none"]
        lines += [
            "",
            "## How to proceed",
            "",
            "1. Review and edit each workflow's `<slug>.md` file.",
            "2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).",
            "3. Confirm the cross-workflow dependencies (tick their boxes).",
            "4. Run `workflow-compiler validate <project-id>` to check your edits.",
            "5. Run `workflow-compiler approve-spec <project-id>` to generate the "
            "graphs, Temporal designs, and code.",
        ]
        return "\n".join(lines) + "\n"

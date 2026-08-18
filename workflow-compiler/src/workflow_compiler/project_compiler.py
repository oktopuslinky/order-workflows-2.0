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

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from workflow_compiler.agents.change_spec import ChangeSpecAgent
from workflow_compiler.agents.cvpa import CVPAClassifierAgent
from workflow_compiler.agents.edit_interpreter import EditInterpreterAgent
from workflow_compiler.agents.graph_builder import GraphBuilderAgent
from workflow_compiler.agents.segmentation import WorkflowSegmentationAgent
from workflow_compiler.change.bcr import seed_terms
from workflow_compiler.change.spec_seed import seed_components
from workflow_compiler.checklist import amend as checklist_amend
from workflow_compiler.compiler import (
    ProgressCallback,
    ProgressEvent,
    WorkflowCompiler,
    _emit,
)
from workflow_compiler.dialogue import (
    AnswerOutcome,
    ChatOutcome,
    DialogueEngine,
    SpecChatEngine,
    agenda_fingerprint,
)
from workflow_compiler.exceptions import (
    ApprovalError,
    CompilationError,
    EditPreviewStaleError,
    WorkflowCompilerError,
)
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.kg.grounding import KgGrounder
from workflow_compiler.kg.service import KgService
from workflow_compiler.models import (
    CHANGES_SLUG,
    ApprovalStatus,
    ChangeSpec,
    CompilationProject,
    CompilationStage,
    CrossReference,
    DialogueSession,
    EditPlan,
    EditRecord,
    FactCategory,
    Patch,
    PatchAction,
    ProjectGrounding,
    ProjectStage,
    Provenance,
    ResolvedEdit,
    Severity,
    SpecChatSession,
    SpecFinding,
    SpecItem,
    TriggerMode,
    TriggerNode,
    TriggerOp,
    WiringAction,
    WorkflowFacts,
    WorkflowMetadata,
    WorkflowSegment,
    WorkflowSpec,
    WorkflowState,
    WorkflowTrigger,
    XrefOp,
)
from workflow_compiler.prompts import PromptManager
from workflow_compiler.spec import (
    EditPatchApplier,
    SpecValidator,
    ingest_spec_markdown,
    render_spec,
)
from workflow_compiler.spec.change_ingest import ingest_change_markdown
from workflow_compiler.spec.change_renderer import CHANGES_FILENAME, render_change_spec
from workflow_compiler.spec.change_validator import validate_change_spec
from workflow_compiler.spec.edit_ingest import EditRequestDoc, parse_edit_request
from workflow_compiler.spec.wiring import apply_xref_op
from workflow_compiler.storage.project_store import FileProjectStore, ProjectStore

if TYPE_CHECKING:
    from workflow_compiler.models.change import ChangeRequest

#: Cap on impact-traversal rows handed to the change-spec extraction prompt.
_CHANGE_IMPACT_ROWS = 120


@dataclass(frozen=True)
class EditPreview:
    """Result of :meth:`ProjectCompiler.preview_edit` — nothing was persisted.

    ``project`` is the would-be post-edit project (a deep copy), ``record`` its
    would-be audit entry, and ``resolved`` the replayable LLM artifacts to send
    back via ``edit_specs(resolved=...)`` for an LLM-free confirm.
    """

    project: CompilationProject
    record: EditRecord
    resolved: ResolvedEdit

if TYPE_CHECKING:
    from workflow_compiler.config import Settings

#: Filename of the project-level summary written next to the spec files.
OVERVIEW_FILENAME = "overview.md"

#: Sections owned by the pre-compile gate (:meth:`ProjectCompiler._gate_findings`)
#: plus the graph-review outcome. Findings in these sections are *recomputed* on
#: every validate/approve, so a stale one can never survive a fixed spec.
GATE_SECTIONS = frozenset({"Segmentation", "Open Questions", "Graph review"})


def _nested_progress(
    progress: ProgressCallback | None, label: str
) -> ProgressCallback | None:
    """Relay a sub-pipeline's events as nested steps of ``label``.

    Fact extraction runs a pipeline of its own (discovery, extraction, and the
    review passes inside each) and is by far the longest stage — minutes per
    workflow. Handed no sink it reports nothing at all, which from the outside is
    indistinguishable from a hang.

    Events are re-emitted under the ``review-pass`` phase that consumers already
    render as nested, and prefixed with ``label`` so consecutive workflows stay
    tellable apart. The inner index/total describe the inner pipeline, which is
    exactly what a nested step should show.
    """
    if progress is None:
        return None

    def relay(event: ProgressEvent) -> None:
        _emit(progress, replace(event, phase="review-pass", name=f"{label}:{event.name}"))

    return relay


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
        kg_service: KgService | None = None,
    ) -> None:
        """Wire the front-end collaborators around an inner workflow compiler.

        ``kg_service`` is only needed by knowledge-graph-grounded projects: the
        change-spec validator resolves component paths through it and approval
        re-grounds the Temporal-design prompt. Ungrounded projects never touch it.
        """
        self._llm = llm_provider
        self._kg = kg_service
        self._prompts = prompt_manager or PromptManager()
        self._compiler = workflow_compiler or WorkflowCompiler(
            llm_provider=llm_provider, prompt_manager=self._prompts
        )
        self._projects: ProjectStore = project_store or FileProjectStore()
        self._segmentation = WorkflowSegmentationAgent(
            llm_provider, prompt_manager=self._prompts, review_enabled=segmentation_review
        )
        self._validator = SpecValidator(llm_provider, prompt_manager=self._prompts)
        self._change_agent = ChangeSpecAgent(llm_provider, prompt_manager=self._prompts)
        self._threshold = graph_health_threshold
        # Built lazily: most projects never open a dialogue session.
        self._dialogue: DialogueEngine | None = None
        self._spec_chat: SpecChatEngine | None = None

    @classmethod
    def from_settings(
        cls,
        *,
        llm_provider: BaseLLMProvider | None = None,
        settings: Settings | None = None,
    ) -> ProjectCompiler:
        """Build a fully wired project compiler from application settings."""
        from workflow_compiler.config import get_settings
        from workflow_compiler.kg.store import FileKnowledgeBaseStore
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
            # Read-only use (retrieve / search / impact); no provider factory,
            # because a project compiler never indexes a knowledge base.
            kg_service=KgService(
                FileKnowledgeBaseStore(resolved.state_store_path),
                default_budget=resolved.kg_retrieve_budget,
            ),
        )

    @property
    def workflow_compiler(self) -> WorkflowCompiler:
        """The inner per-workflow compiler (back-end)."""
        return self._compiler

    @property
    def kg_service(self) -> KgService | None:
        """The knowledge-graph service, when this compiler was given one."""
        return self._kg

    def grounder_for(self, project: CompilationProject) -> KgGrounder | None:
        """A grounder bound to the project's knowledge base, or ``None``.

        ``None`` when the project is ungrounded or this compiler has no
        :class:`KgService` — every caller treats that as "compile as before".
        """
        if project.kb_id is None or self._kg is None:
            return None
        return KgGrounder(
            self._kg,
            project.kb_id,
            kb_name=project.grounding.kb_name if project.grounding else "",
        )

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
        grounder: KgGrounder | None = None,
        change_request: ChangeRequest | None = None,
    ) -> CompilationProject:
        """Segment the document and draft one reviewed spec per workflow.

        Stops at the spec gate (``SPEC_DRAFTED``): the caller renders the spec
        files for the user, who edits them and drives ``validate_specs`` /
        ``approve_spec``.

        ``grounder`` (a :class:`~workflow_compiler.kg.KgGrounder` bound to a
        knowledge base) prepends a knowledge-graph context block to the
        segmentation, discovery and fact-extraction prompts and additionally
        extracts a **change spec** (``changes.md``) for the document; ``None``
        compiles exactly as before. ``change_request`` (an approved change
        request whose TDD this document is) seeds that change spec with the
        request's impact rows and restricts its requirement ids; it is only
        honoured together with a grounder.
        """
        if not document_text or not document_text.strip():
            raise CompilationError("Cannot compile an empty document.")

        project = CompilationProject(document_text=document_text)
        if project_id is not None:
            project.project_id = project_id
        if grounder is not None:
            project.kb_id = grounder.kb_id
            project.grounding = ProjectGrounding(kb_name=grounder.kb_name)
            if change_request is not None:
                project.change_request_id = change_request.cr_id
                project.grounding.change_request_title = change_request.title
                project.grounding.requirement_ids = [
                    r.id for r in change_request.requirements if r.id
                ]

        _emit(progress, ProgressEvent(
            phase="agent", name=self._segmentation.name, status="start", index=1, total=2,
        ))
        started = time.perf_counter()
        self._segmentation.set_progress(self._sub_reporter(progress))
        try:
            segments, references, triggers, warnings = await self._segmentation.run(
                document_text,
                kg_context=await self._kg_block(grounder, document_text),
            )
        finally:
            self._segmentation.set_progress(None)
        project.segments = segments
        project.cross_references = references
        project.triggers = triggers
        project.warnings = warnings
        project.stage = ProjectStage.WORKFLOWS_DISCOVERED
        elapsed = time.perf_counter() - started
        self._record_timing(project, self._segmentation.name, elapsed)
        _emit(progress, ProgressEvent(
            phase="agent", name=self._segmentation.name, status="done", index=1, total=2,
            seconds=elapsed, stage=project.stage.value,
        ))

        total = len(segments)
        for index, segment in enumerate(segments, start=1):
            name = f"extract:{segment.slug}"
            _emit(progress, ProgressEvent(
                phase="agent", name=name, status="start", index=index, total=total,
            ))
            seg_started = time.perf_counter()
            state = await self._compiler.extract_facts(
                segment.text,
                project_id=project.project_id,
                progress=_nested_progress(progress, segment.slug),
                kg_context=await self._kg_block(grounder, segment.text),
            )
            project.specs.append(self._build_spec(segment.slug, state))
            elapsed = time.perf_counter() - seg_started
            self._record_timing(project, name, elapsed)
            _emit(progress, ProgressEvent(
                phase="agent", name=name, status="done", index=index, total=total,
                seconds=elapsed, stage=state.stage.value,
            ))

        if grounder is not None:
            await self._extract_change_spec(
                project, document_text, grounder, change_request, progress
            )
            self._record_grounding(project, grounder)

        project.stage = ProjectStage.SPEC_DRAFTED
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    @staticmethod
    async def _kg_block(grounder: KgGrounder | None, text: str) -> str | None:
        """The grounding block for ``text``, or ``None`` when ungrounded."""
        if grounder is None:
            return None
        return await grounder.block_for(text)

    @staticmethod
    def _record_grounding(project: CompilationProject, grounder: KgGrounder) -> None:
        """Copy the grounder's visible provenance onto the project."""
        grounding = project.grounding or ProjectGrounding(kb_name=grounder.kb_name)
        seen = set(grounding.sources)
        grounding.sources.extend(s for s in grounder.sources_seen if s not in seen)
        if grounder.min_coverage is not None:
            grounding.coverage = (
                grounder.min_coverage
                if grounding.coverage is None
                else min(grounding.coverage, grounder.min_coverage)
            )
        grounding.low_confidence = grounding.low_confidence or grounder.any_low_confidence
        project.grounding = grounding

    async def _extract_change_spec(
        self,
        project: CompilationProject,
        document_text: str,
        grounder: KgGrounder,
        change_request: ChangeRequest | None,
        progress: ProgressCallback | None,
    ) -> None:
        """Extract ``changes.md`` (existing vs. proposed per component).

        Seeded from the change request's parsed impact rows when one is linked;
        the deterministic impact traversal over the document's own identifiers
        and the grounding block go into the prompt. A failed extraction never
        fails the compile: the seed rows (or an empty spec) are kept and the
        failure is recorded as a project warning.
        """
        name = "change_spec"
        _emit(progress, ProgressEvent(phase="agent", name=name, status="start", index=1, total=1))
        started = time.perf_counter()
        seeds = seed_components(change_request) if change_request is not None else []
        requirement_ids = (
            [r.id for r in change_request.requirements if r.id]
            if change_request is not None
            else []
        )
        try:
            impact_rows = await grounder.kg.impact(
                grounder.kb_id, seed_terms(document_text, [])[:40], max_hops=2
            )
        except Exception as exc:  # a broken graph degrades, never fails
            impact_rows = []
            project.warnings.append(f"change spec: impact traversal skipped — {exc}")
        kg_context = await grounder.block_for(document_text)
        try:
            spec = await self._change_agent.extract(
                document_text,
                kg_context=kg_context,
                impact_table=impact_rows[:_CHANGE_IMPACT_ROWS],
                seed_components=seeds,
                requirement_ids=requirement_ids,
                sources=list(grounder.sources_seen),
            )
        except WorkflowCompilerError as exc:
            project.warnings.append(
                f"change spec: extraction failed ({exc}); changes.md holds the "
                "change request's impact rows only"
            )
            spec = ChangeSpec(components=seeds, sources=list(grounder.sources_seen))
        project.change_spec = spec
        elapsed = time.perf_counter() - started
        self._record_timing(project, name, elapsed)
        _emit(progress, ProgressEvent(
            phase="agent", name=name, status="done", index=1, total=1, seconds=elapsed,
        ))

    # ------------------------------------------------------------------ #
    # changes.md helpers (the change spec is a second file at the same gate)
    # ------------------------------------------------------------------ #

    @staticmethod
    def render_changes(project: CompilationProject) -> str | None:
        """``changes.md`` for a grounded project, ``None`` when it has no change spec."""
        if project.change_spec is None:
            return None
        grounding = project.grounding
        return render_change_spec(
            project.change_spec,
            kb_id=project.kb_id,
            kb_name=grounding.kb_name if grounding else "",
            change_request_id=project.change_request_id,
            change_request_title=grounding.change_request_title if grounding else "",
        )

    @classmethod
    def spec_markdown(cls, project: CompilationProject) -> dict[str, str]:
        """Every editable file of the project keyed by slug (``__changes__`` last)."""
        files = {
            spec.slug: render_spec(spec, project.cross_references, project.triggers)
            for spec in project.specs
        }
        changes = cls.render_changes(project)
        if changes is not None:
            files[CHANGES_SLUG] = changes
        return files

    def _fold_changes(
        self, project: CompilationProject, markdown: str | None
    ) -> list[SpecFinding]:
        """Fold an edited ``changes.md`` onto the change spec; return ingest findings."""
        findings: list[SpecFinding] = []
        if markdown is None or project.change_spec is None:
            return findings
        result = ingest_change_markdown(project.change_spec, markdown)
        project.change_spec = result.spec
        findings.extend(
            SpecFinding(
                severity=Severity.INFO, workflow=CHANGES_SLUG, section="Ingest", message=c
            )
            for c in result.changes
        )
        findings.extend(
            SpecFinding(
                severity=Severity.WARNING, workflow=CHANGES_SLUG, section="Ingest", message=w
            )
            for w in result.warnings
        )
        return findings

    async def _validate_changes(self, project: CompilationProject) -> list[SpecFinding]:
        """Deterministic change-spec validation (paths, requirement ids, empty proposals)."""
        if project.change_spec is None:
            return []
        requirement_ids = (
            (project.grounding.requirement_ids if project.grounding else [])
            if project.change_request_id
            else None
        )
        return await validate_change_spec(
            project.change_spec,
            kg=self._kg,
            kb_id=project.kb_id,
            requirement_ids=requirement_ids,
        )

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
        findings_by_slug: dict[str, list[SpecFinding]] = {}
        total = len(project.specs)

        for index, spec in enumerate(list(project.specs), start=1):
            name = f"validate:{spec.slug}"
            _emit(progress, ProgressEvent(
                phase="review", name=name, status="start", index=index, total=total,
            ))
            started = time.perf_counter()
            findings: list[SpecFinding] = []
            current = spec
            markdown = (markdown_by_slug or {}).get(spec.slug)
            if markdown is not None:
                result = ingest_spec_markdown(
                    current, markdown, project.document_text,
                    project.cross_references, project.triggers,
                )
                current = result.spec
                project.cross_references = result.cross_references
                project.triggers = result.triggers
                findings.extend(
                    SpecFinding(
                        severity=Severity.INFO, workflow=spec.slug,
                        section="Ingest", message=c,
                    )
                    for c in result.changes
                )
                findings.extend(
                    SpecFinding(
                        severity=Severity.WARNING, workflow=spec.slug,
                        section="Ingest", message=w,
                    )
                    for w in result.warnings
                )
            current, validator_findings, _note = await self._validator.validate(
                current, project.document_text, project.cross_references
            )
            findings.extend(
                SpecFinding(
                    severity=Severity.WARNING, workflow=spec.slug, message=vf
                )
                for vf in validator_findings
            )
            self._replace_spec(project, current)
            # Run the same pre-compile gate approval enforces, so a spec that
            # validates clean is a spec that will compile. Without this, validate
            # is blind to the checklist and reports green on a spec approve skips.
            gate, _state = self._gate_findings(project, current)
            findings.extend(gate)
            findings_by_slug[spec.slug] = findings
            elapsed = time.perf_counter() - started
            self._record_timing(project, name, elapsed)
            _emit(progress, ProgressEvent(
                phase="review", name=name, status="done", index=index, total=total,
                seconds=elapsed,
            ))

        # Deterministic (no-LLM) cross-workflow integrity pass: distribute its
        # findings onto the workflow that owns each trigger / dependency.
        for finding in self._validate_triggers_and_dependencies(project):
            findings_by_slug.setdefault(finding.workflow, []).append(finding)

        if project.change_spec is not None:
            name = f"validate:{CHANGES_SLUG}"
            _emit(progress, ProgressEvent(
                phase="review", name=name, status="start", index=total + 1, total=total + 1,
            ))
            started = time.perf_counter()
            change_findings = self._fold_changes(
                project, (markdown_by_slug or {}).get(CHANGES_SLUG)
            )
            change_findings.extend(await self._validate_changes(project))
            findings_by_slug[CHANGES_SLUG] = change_findings
            elapsed = time.perf_counter() - started
            self._record_timing(project, name, elapsed)
            _emit(progress, ProgressEvent(
                phase="review", name=name, status="done", index=total + 1, total=total + 1,
                seconds=elapsed,
            ))

        project.validation_findings = findings_by_slug
        project.stage = ProjectStage.SPEC_VALIDATED
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    @staticmethod
    def _validate_triggers_and_dependencies(
        project: CompilationProject,
    ) -> list[SpecFinding]:
        """Deterministic cross-workflow integrity checks (no LLM).

        Classifies problems two ways: structural breakage that would make
        generation impossible is ``BLOCKING`` (unknown endpoint, or a referenced
        target input the target explicitly does *not* declare); softer issues the
        human should confirm are ``WARNING`` (unverifiable field, type mismatch,
        unconfirmed predicate, blocking trigger with no result binding).
        """
        specs = {spec.slug: spec for spec in project.specs}

        def fields(slug: str, category: FactCategory) -> set[str]:
            spec = specs.get(slug)
            if spec is None:
                return set()
            return {
                f.statement.strip().lower()
                for f in spec.facts.facts
                if f.category is category
            }

        findings: list[SpecFinding] = []

        def add(
            severity: Severity, workflow: str, message: str, suggestion: str | None = None
        ) -> None:
            findings.append(
                SpecFinding(
                    severity=severity, workflow=workflow, section="Triggers",
                    message=message, suggestion=suggestion,
                )
            )

        for trigger in project.triggers:
            src = trigger.source_workflow
            label = f"trigger to '{trigger.target_workflow}'"
            if trigger.target_workflow not in specs:
                add(
                    Severity.BLOCKING, src,
                    f"{label} targets a workflow that is not in this project",
                    "fix the target name or remove the trigger",
                )
                continue
            target_inputs = fields(trigger.target_workflow, FactCategory.INPUT)
            for binding in trigger.input_map:
                field_key = binding.target_input.strip().lower()
                if target_inputs and field_key not in target_inputs:
                    add(
                        Severity.BLOCKING, src,
                        f"{label} maps to input '{binding.target_input}', which "
                        f"'{trigger.target_workflow}' does not declare",
                        "correct the input name or add it to the target's Inputs",
                    )
                elif not target_inputs:
                    add(
                        Severity.WARNING, src,
                        f"{label} maps to input '{binding.target_input}' but the target "
                        "declares no inputs to verify against",
                        "declare the target's inputs so the hand-off can be checked",
                    )
            if trigger.mode is TriggerMode.BLOCKING and not trigger.result_binding:
                add(
                    Severity.WARNING, src,
                    f"{label} is blocking but has no result binding",
                    "name the variable its result should bind to, or make it fire-and-forget",
                )
            if trigger.condition and not trigger.user_confirmed:
                add(
                    Severity.WARNING, src,
                    f"{label} is conditional on '{trigger.condition}' but is not confirmed",
                    "review and tick its checkbox in the spec file",
                )
            elif not trigger.user_confirmed:
                add(
                    Severity.WARNING, src,
                    f"{label} has not been confirmed",
                    "review and tick its checkbox in the spec file",
                )

        for ref in project.cross_references:
            if ref.target_workflow not in specs:
                findings.append(SpecFinding(
                    severity=Severity.BLOCKING, workflow=ref.source_workflow,
                    section="Cross-Workflow Dependencies",
                    message=(
                        f"dependency feeds '{ref.target_workflow}', which is not in this project"
                    ),
                    suggestion="fix the target name or remove the dependency",
                ))
                continue
            if not ref.user_confirmed:
                # An unconfirmed dependency is a HARD STOP at approval
                # (``approve_spec`` raises rather than warning), but until this
                # finding existed nothing said so: validate reported green and
                # the dialogue, whose agenda is built from findings, never asked.
                # A user could answer every question and still be refused.
                findings.append(SpecFinding(
                    severity=Severity.WARNING, workflow=ref.source_workflow,
                    section="Cross-Workflow Dependencies",
                    message=(
                        f"the dependency '{ref.output_field}' -> "
                        f"'{ref.target_workflow}.{ref.input_field}' was detected "
                        "automatically and has not been confirmed"
                    ),
                    suggestion=(
                        "confirm the hand-off is real, correct it, or remove it — "
                        "approval is refused while it is unconfirmed"
                    ),
                ))
            if ref.output_type != ref.input_type:
                findings.append(SpecFinding(
                    severity=Severity.WARNING, workflow=ref.source_workflow,
                    section="Cross-Workflow Dependencies",
                    message=(
                        f"type mismatch: '{ref.output_field}' is {ref.output_type} but "
                        f"'{ref.target_workflow}.{ref.input_field}' expects {ref.input_type}"
                    ),
                    suggestion="align the output/input types in the spec files",
                ))

        return findings

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
                spec, markdown, project.document_text,
                project.cross_references, project.triggers,
            )
            project.cross_references = result.cross_references
            project.triggers = result.triggers
            self._replace_spec(project, result.spec)
        self._fold_changes(project, markdown_by_slug.get(CHANGES_SLUG))
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    # ------------------------------------------------------------------ #
    # Stage 2a-bis: conversational spec resolution
    # ------------------------------------------------------------------ #

    @property
    def dialogue(self) -> DialogueEngine:
        """The conversational-resolution engine, built lazily on first use."""
        if self._dialogue is None:
            self._dialogue = DialogueEngine(
                self._llm, change_agent=self._change_agent, prompt_manager=self._prompts
            )
        return self._dialogue

    async def prepare_dialogue(
        self, project_id: str, *, persist: bool = True
    ) -> CompilationProject:
        """Draft the dialogue's questions ahead of the user asking for them.

        Runs the same per-spec drafting ``start_dialogue`` would, but stores the
        result on ``project.prepared_dialogue`` instead of opening a session, so
        the Resolve tab opens instantly rather than waiting minutes for the first
        question.

        Drafting takes as long as an LLM call per spec, and the specs can change
        underneath it in that time — the free-form chat and hand edits both write
        to the same project. So the project is **re-loaded** afterwards and the
        agenda is only attached if its fingerprint still describes what is now on
        disk. Saving the in-memory copy instead would silently roll back whatever
        happened during the run. A superseded agenda is discarded, not stored: a
        stale agenda that looks prepared is worse than none.
        """
        project = await self._projects.load(project_id)
        started = time.perf_counter()
        prepared = await self.dialogue.prepare(project)
        elapsed = time.perf_counter() - started
        if prepared is None:
            return project

        current = await self._projects.load(project_id)
        if agenda_fingerprint(current) != prepared.fingerprint:
            return current
        current.prepared_dialogue = prepared
        self._record_timing(current, "dialogue:prepare", elapsed)
        current.touch()
        if persist:
            await self._projects.save(current)
        return current

    async def start_dialogue(
        self, project_id: str, *, persist: bool = True
    ) -> tuple[CompilationProject, DialogueSession]:
        """Open a question-and-answer session over the project's unresolved items.

        Replaces any session already open — the agenda is a snapshot, so a stale
        one would ask about findings that no longer hold.
        """
        project = await self._projects.load(project_id)
        started = time.perf_counter()
        session = await self.dialogue.start(project)
        self._record_timing(project, "dialogue:start", time.perf_counter() - started)
        project.dialogue_session = session
        project.touch()
        if persist:
            await self._projects.save(project)
        return project, session

    async def answer_dialogue(
        self,
        project_id: str,
        answer: str,
        *,
        chosen_option: str | None = None,
        persist: bool = True,
    ) -> tuple[CompilationProject, DialogueSession, AnswerOutcome]:
        """Apply one prose answer to the open session's current question."""
        project = await self._projects.load(project_id)
        session = self._require_session(project)
        started = time.perf_counter()
        outcome = await self.dialogue.answer(
            project, session, answer, chosen_option=chosen_option
        )
        self._record_timing(project, "dialogue:answer", time.perf_counter() - started)
        if session.complete:
            self.dialogue.finish(project, session)
        project.dialogue_session = session
        project.touch()
        if persist:
            await self._projects.save(project)
        return project, session, outcome

    async def skip_dialogue(
        self, project_id: str, *, persist: bool = True
    ) -> tuple[CompilationProject, DialogueSession]:
        """Pass on the current question without changing the spec."""
        project = await self._projects.load(project_id)
        session = self._require_session(project)
        self.dialogue.skip(session)
        if session.complete:
            self.dialogue.finish(project, session)
        project.dialogue_session = session
        project.touch()
        if persist:
            await self._projects.save(project)
        return project, session

    async def end_dialogue(
        self, project_id: str, *, persist: bool = True
    ) -> CompilationProject:
        """Close the open session, keeping every change already applied."""
        project = await self._projects.load(project_id)
        session = self._require_session(project)
        self.dialogue.finish(project, session)
        project.dialogue_session = None
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    @staticmethod
    def _require_session(project: CompilationProject) -> DialogueSession:
        """Return the open session, or explain that there is none."""
        if project.dialogue_session is None:
            raise CompilationError(
                "No dialogue session is open for this project. Start one first."
            )
        return project.dialogue_session

    # ------------------------------------------------------------------ #
    # Stage 2a-ter: free-form spec chat
    # ------------------------------------------------------------------ #
    # The other door to the same gate. Unlike the guided dialogue this needs no
    # prior `validate` — there is no findings agenda, the user simply says what
    # they want changed.

    @property
    def spec_chat(self) -> SpecChatEngine:
        """The free-form spec-editing engine, built lazily on first use."""
        if self._spec_chat is None:
            self._spec_chat = SpecChatEngine(self._llm, prompt_manager=self._prompts)
        return self._spec_chat

    async def start_spec_chat(
        self, project_id: str, *, persist: bool = True
    ) -> tuple[CompilationProject, SpecChatSession]:
        """Open a free-form chat, or return the one already open.

        Idempotent on purpose: the transcript is the value here, so re-opening
        must not discard it (contrast ``start_dialogue``, whose agenda is a
        snapshot and *must* be retaken).
        """
        project = await self._projects.load(project_id)
        if project.spec_chat is None:
            project.spec_chat = self.spec_chat.start(project)
            project.touch()
            if persist:
                await self._projects.save(project)
        return project, project.spec_chat

    async def send_spec_chat(
        self,
        project_id: str,
        message: str,
        *,
        slug: str | None = None,
        chosen_option: str | None = None,
        persist: bool = True,
    ) -> tuple[CompilationProject, SpecChatSession, ChatOutcome]:
        """Send one free-form instruction; the spec is patched in place.

        Opens a session implicitly when none exists — a chat has no setup step
        the user should have to think about.
        """
        project = await self._projects.load(project_id)
        session = project.spec_chat or self.spec_chat.start(project)
        started = time.perf_counter()
        outcome = await self.spec_chat.send(
            project, session, message, slug=slug, chosen_option=chosen_option
        )
        self._record_timing(project, "spec_chat:send", time.perf_counter() - started)
        project.spec_chat = session
        project.touch()
        if persist:
            await self._projects.save(project)
        return project, session, outcome

    async def end_spec_chat(
        self, project_id: str, *, persist: bool = True
    ) -> CompilationProject:
        """Close the chat, keeping every change already applied."""
        project = await self._projects.load(project_id)
        project.spec_chat = None
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    # ------------------------------------------------------------------ #
    # Stage 2b: edit requests against compiled workflows
    # ------------------------------------------------------------------ #

    async def edit_specs(
        self,
        project_id: str,
        edit_document: str,
        *,
        workflows: list[str] | None = None,
        author: str | None = None,
        persist: bool = True,
        progress: ProgressCallback | None = None,
        resolved: ResolvedEdit | None = None,
    ) -> CompilationProject:
        """Apply a workflow edit-request document to the project's specs.

        The document's skeleton is parsed deterministically (fail-fast, before
        any LLM call); each workflow section's entries are interpreted into
        patches by the :class:`EditInterpreterAgent` and applied with human
        authority. The whole edit is **atomic**: any failure leaves the stored
        project untouched. On success the project re-enters the spec gate
        (stage ``SPEC_DRAFTED``, approval ``PENDING``) so the normal
        validate → approve-spec flow re-runs, and an :class:`EditRecord` is
        appended to the audit log.

        Passing ``resolved`` (from :meth:`preview_edit`) confirms a preview:
        the stored plans are applied verbatim with **no LLM calls**. A stale
        blob — the project changed since the preview, or the document's
        sections no longer match — raises :class:`EditPreviewStaleError`.
        """
        project = await self._projects.load(project_id)
        working, _record, _resolved = await self._run_edit_pipeline(
            project,
            edit_document,
            workflows=workflows,
            author=author,
            progress=progress,
            resolved=resolved,
        )
        if persist:
            await self._projects.save(working)
        return working

    async def preview_edit(
        self,
        project_id: str,
        edit_document: str,
        *,
        workflows: list[str] | None = None,
        author: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> EditPreview:
        """Dry-run an edit request: full parse → interpret → apply, nothing stored.

        Returns the would-be project, its audit record, and the
        :class:`ResolvedEdit` blob that :meth:`edit_specs` replays at confirm
        time without re-interpreting (see the fingerprint rule there).
        """
        project = await self._projects.load(project_id)
        working, record, resolved_out = await self._run_edit_pipeline(
            project,
            edit_document,
            workflows=workflows,
            author=author,
            progress=progress,
            resolved=None,
        )
        return EditPreview(project=working, record=record, resolved=resolved_out)

    @staticmethod
    def _record_timing(project: CompilationProject, step: str, seconds: float) -> None:
        """Accumulate a step's wall-clock seconds onto the project (time-saved metric)."""
        project.stage_timings[step] = project.stage_timings.get(step, 0.0) + seconds

    @staticmethod
    def _fingerprint(
        project: CompilationProject, edit_document: str, workflows: list[str] | None
    ) -> str:
        """Bind a preview to (project state, document, filter) — any change invalidates."""
        doc_hash = hashlib.sha256(edit_document.encode("utf-8")).hexdigest()
        payload = "|".join(
            [
                project.project_id,
                project.updated_at.isoformat(),
                doc_hash,
                ",".join(sorted(workflows or [])),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _verify_resolved(
        resolved: ResolvedEdit, expected_fingerprint: str, doc: EditRequestDoc
    ) -> None:
        """Reject a stale or mismatched preview blob before anything is applied."""
        stale = EditPreviewStaleError(
            "The project changed after this preview was generated — run preview again."
        )
        if resolved.fingerprint != expected_fingerprint:
            raise stale
        if set(resolved.plans) != {section.slug for section in doc.workflows}:
            raise stale
        if set(resolved.drafted_workflows) != {
            section.slug for section in doc.add_workflows
        }:
            raise stale
        if (resolved.project_plan is None) == bool(doc.project_bullets):
            raise stale

    async def _run_edit_pipeline(
        self,
        project: CompilationProject,
        edit_document: str,
        *,
        workflows: list[str] | None,
        author: str | None,
        progress: ProgressCallback | None,
        resolved: ResolvedEdit | None,
    ) -> tuple[CompilationProject, EditRecord, ResolvedEdit]:
        """Shared edit pipeline: parse → interpret (or replay) → apply atomically.

        Does **not** persist — ``edit_specs`` saves the result, ``preview_edit``
        returns it untouched. When ``resolved`` is given every LLM touchpoint is
        replaced by the stored artifact; otherwise each artifact is captured
        into the returned :class:`ResolvedEdit`.
        """
        known = {spec.slug for spec in project.specs}
        doc = parse_edit_request(edit_document, known)
        self._enforce_workflow_filter(doc, workflows, known)
        resolved_out = ResolvedEdit(
            fingerprint=self._fingerprint(project, edit_document, workflows)
        )
        if resolved is not None:
            self._verify_resolved(resolved, resolved_out.fingerprint, doc)

        # All mutations happen on a deep copy: one edit document is one human
        # intent, and a partially-applied request would leave a project state
        # the author never described.
        working = project.model_copy(deep=True)
        record = EditRecord(document=edit_document, author=author)
        summary: dict[str, list[str]] = {}

        for slug in doc.remove_workflows:
            summary[slug] = self._remove_workflow(working, slug)
            record.workflows_removed.append(slug)

        total = len(doc.add_workflows) + len(doc.workflows)
        index = 0
        for new_section in doc.add_workflows:
            index += 1
            name = f"edit:add:{new_section.slug}"
            _emit(progress, ProgressEvent(
                phase="agent", name=name, status="start", index=index, total=total,
            ))
            started = time.perf_counter()
            if resolved is not None:
                drafted = resolved.drafted_workflows[new_section.slug].model_copy(deep=True)
            else:
                state = await self._compiler.extract_facts(
                    new_section.body, project_id=working.project_id
                )
                drafted = self._build_spec(new_section.slug, state)
            resolved_out.drafted_workflows[new_section.slug] = drafted.model_copy(deep=True)
            resolved_out.timings[name] = time.perf_counter() - started
            working.specs.append(drafted)
            working.segments.append(
                self._new_segment(working, new_section.slug, drafted, new_section.body)
            )
            # Ground the new workflow: later validate passes compare specs
            # against document_text, so the description must live there too.
            working.document_text += (
                f"\n\n<!-- edit {record.edit_id}: added workflow {new_section.slug} -->\n"
                f"{new_section.body}\n"
            )
            record.workflows_added.append(new_section.slug)
            summary[new_section.slug] = [f"added workflow '{drafted.metadata.name}'"]
            _emit(progress, ProgressEvent(
                phase="agent", name=name, status="done", index=index, total=total,
                seconds=time.perf_counter() - started,
            ))

        # Interpret every section first (LLM), then apply deterministically —
        # an unresolved entry anywhere aborts before anything is applied.
        interpreter = EditInterpreterAgent(self._llm, prompt_manager=self._prompts)
        project_context = self._project_context(working)
        plans: dict[str, EditPlan] = {}
        unresolved: list[str] = []
        for section in doc.workflows:
            index += 1
            name = f"edit:{section.slug}"
            _emit(progress, ProgressEvent(
                phase="agent", name=name, status="start", index=index, total=total,
            ))
            started = time.perf_counter()
            current = working.spec_for(section.slug)
            if current is None:  # pragma: no cover - parser guarantees existence
                raise CompilationError(f"No spec for workflow {section.slug!r}.")
            if resolved is not None:
                # Confirm path: replay the previewed plan — no LLM call.
                plan = resolved.plans[section.slug]
            else:
                plan = await interpreter.interpret(
                    slug=section.slug,
                    edit_section=section.to_markdown(),
                    current_spec=render_spec(
                        current, working.cross_references, working.triggers
                    ),
                    project_context=project_context,
                )
            resolved_out.plans[section.slug] = plan
            resolved_out.timings[name] = time.perf_counter() - started
            unresolved.extend(f"{section.slug}: {entry}" for entry in plan.unresolved)
            if section.entry_count() and not (
                plan.patches or plan.trigger_ops or plan.xref_ops or plan.unresolved
            ):
                raise CompilationError(
                    f"The edit entries for workflow '{section.slug}' produced no "
                    "operations — rephrase them (see docs/EDIT_FORMAT_GUIDE.md)."
                )
            plans[section.slug] = plan
            _emit(progress, ProgressEvent(
                phase="agent", name=name, status="done", index=index, total=total,
                seconds=time.perf_counter() - started,
            ))

        project_plan: EditPlan | None = None
        if doc.project_bullets:
            if resolved is not None and resolved.project_plan is not None:
                project_plan = resolved.project_plan
            else:
                project_plan = await interpreter.interpret(
                    slug="(project)",
                    edit_section="\n".join(f"- {b}" for b in doc.project_bullets),
                    current_spec="(project-level request — no single workflow)",
                    project_context=project_context,
                )
            resolved_out.project_plan = project_plan
            unresolved.extend(f"(project): {entry}" for entry in project_plan.unresolved)
            if project_plan.patches:
                raise CompilationError(
                    "Project-section entries may only change cross-workflow wiring "
                    "(triggers/dependencies). Put content edits under a "
                    "'## Workflow: <slug>' section."
                )

        if unresolved:
            listed = "\n".join(f"  - {entry}" for entry in unresolved)
            raise CompilationError(
                "Some edit entries could not be translated into operations — "
                f"nothing was applied. Rephrase these entries:\n{listed}"
            )

        # Apply patches per workflow (human authority), then wiring ops.
        applier = EditPatchApplier()
        for slug, plan in plans.items():
            if not plan.patches:
                continue
            target_spec = working.spec_for(slug)
            assert target_spec is not None
            new_spec, lines, warnings = applier.apply(
                target_spec, plan.patches, working.document_text
            )
            dropped = self._dropped_count(lines)
            if dropped:
                benign, fatal = self._classify_drops(
                    applier, target_spec, plan.patches, working.document_text
                )
                if fatal:
                    listed = "\n".join(f"  - {entry}" for entry in fatal)
                    raise CompilationError(
                        f"{len(fatal)} operation(s) for workflow '{slug}' could not "
                        "be applied (unknown element id/name, or the current value "
                        "does not match) — nothing was applied. Dropped operations:\n"
                        f"{listed}\n"
                        "Check the edit request against the current spec."
                    )
                # Adds whose value is already in the spec are satisfied, not
                # failed: the requested end-state already holds. Skip them
                # loudly (never silently) and apply the rest.
                lines.extend(f"skipped (already present): {entry}" for entry in benign)
            self._replace_spec(working, new_spec)
            record.resolved_patches[slug] = plan.patches
            entry_lines = summary.setdefault(slug, [])
            entry_lines.extend(lines)
            entry_lines.extend(f"warning: {w}" for w in warnings)
            bumped = self._bump_patch_version(new_spec.metadata.version)
            if bumped is None:
                entry_lines.append(
                    f"version '{new_spec.metadata.version}' is not semver — left unchanged"
                )
            else:
                new_spec.metadata = new_spec.metadata.model_copy(
                    update={"version": bumped}
                )
                self._replace_spec(working, new_spec)
                entry_lines.append(f"version bumped to {bumped}")

        wiring_plans = [p for p in plans.values() if p.trigger_ops or p.xref_ops]
        if project_plan is not None:
            wiring_plans.append(project_plan)
        for plan in wiring_plans:
            for trigger_op in plan.trigger_ops:
                line = self._apply_trigger_op(working, trigger_op)
                summary.setdefault("(project)", []).append(line)
                record.trigger_ops.append(trigger_op)
            for xref_op in plan.xref_ops:
                line = self._apply_xref_op(working, xref_op)
                summary.setdefault("(project)", []).append(line)
                record.xref_ops.append(xref_op)

        record.summary = summary
        working.edit_log.append(record)
        working.spec_approval_status = ApprovalStatus.PENDING
        working.stage = ProjectStage.SPEC_DRAFTED
        # Stale findings would describe the pre-edit specs; validate recomputes
        # everything (including the trigger/xref integrity pass — the safety
        # net for edits that broke wiring).
        working.validation_findings = {}
        # Persist the real durations: on confirm the replay is near-instant, so
        # the preview's measured LLM seconds (carried in the blob) are recorded.
        step_timings = (
            resolved.timings
            if resolved is not None and resolved.timings
            else resolved_out.timings
        )
        for step, seconds in step_timings.items():
            self._record_timing(working, step, seconds)
        working.touch()
        return working, record, resolved_out

    @staticmethod
    def _enforce_workflow_filter(
        doc: EditRequestDoc, workflows: list[str] | None, known: set[str]
    ) -> None:
        """Raise when the edit doc targets workflows outside the ``workflows`` filter."""
        if not workflows:
            return
        allowed = set(workflows)
        unknown = allowed - known
        if unknown:
            raise CompilationError(
                f"--workflow filter names unknown workflow(s): {sorted(unknown)}. "
                f"Known: {sorted(known)}."
            )
        targeted = (
            {section.slug for section in doc.workflows}
            | set(doc.remove_workflows)
            | {section.slug for section in doc.add_workflows}
        )
        outside = targeted - allowed
        if outside:
            raise CompilationError(
                f"The edit request targets workflow(s) outside the --workflow "
                f"filter: {sorted(outside)}. Widen the filter or trim the document."
            )

    @staticmethod
    def _remove_workflow(project: CompilationProject, slug: str) -> list[str]:
        """Drop ``slug``'s spec, segment, and every wire touching it."""
        lines = [f"removed workflow '{slug}'"]
        project.specs = [s for s in project.specs if s.slug != slug]
        project.segments = [s for s in project.segments if s.slug != slug]
        project.workflow_ids.pop(slug, None)
        project.validation_findings.pop(slug, None)
        kept_triggers: list[WorkflowTrigger] = []
        for trigger in project.triggers:
            if slug in (trigger.source_workflow, trigger.target_workflow):
                lines.append(
                    f"dropped trigger {trigger.source_workflow} → {trigger.target_workflow}"
                )
            else:
                kept_triggers.append(trigger)
        project.triggers = kept_triggers
        kept_refs: list[CrossReference] = []
        for ref in project.cross_references:
            if slug in (ref.source_workflow, ref.target_workflow):
                lines.append(
                    f"dropped dependency {ref.source_workflow}.{ref.output_field} → "
                    f"{ref.target_workflow}.{ref.input_field}"
                )
            else:
                kept_refs.append(ref)
        project.cross_references = kept_refs
        return lines

    @staticmethod
    def _new_segment(
        project: CompilationProject, slug: str, spec: WorkflowSpec, body: str
    ) -> WorkflowSegment:
        """Mint a segment for a workflow added by an edit request."""
        existing = {segment.id for segment in project.segments}
        counter = 1
        while f"w{counter}" in existing:
            counter += 1
        return WorkflowSegment(
            id=f"w{counter}",
            slug=slug,
            name=spec.metadata.name,
            purpose=spec.metadata.purpose,
            text=body,
            sliced=True,
        )

    @staticmethod
    def _project_context(project: CompilationProject) -> str:
        """Compact wiring context for the edit-interpreter prompt."""
        lines = ["Workflows: " + ", ".join(sorted(s.slug for s in project.specs))]
        if project.triggers:
            lines.append("Triggers:")
            for t in project.triggers:
                inputs = ", ".join(
                    f"{m.target_input}={m.source.value}:{m.source_ref}"
                    for m in t.input_map
                )
                lines.append(
                    f"- {t.source_workflow} starts {t.target_workflow} "
                    f"({t.mode.value}{', when ' + t.condition if t.condition else ''}"
                    f"{'; inputs: ' + inputs if inputs else ''})"
                )
        if project.cross_references:
            lines.append("Dependencies (output → input):")
            lines.extend(
                f"- {r.source_workflow}.{r.output_field} → "
                f"{r.target_workflow}.{r.input_field}"
                for r in project.cross_references
            )
        return "\n".join(lines)

    @staticmethod
    def _dropped_count(summary_lines: list[str]) -> int:
        """Total dropped-operation count reported by the appliers' notes."""
        return sum(
            int(match.group(1))
            for line in summary_lines
            for match in re.finditer(r"(\d+) dropped", line)
        )

    @classmethod
    def _classify_drops(
        cls,
        applier: EditPatchApplier,
        spec: WorkflowSpec,
        patches: list[Patch],
        document_text: str,
    ) -> tuple[list[str], list[str]]:
        """Attribute drops to individual patches by cumulative single-patch replay.

        Returns ``(benign, fatal)`` descriptions. A drop is benign only when it
        is an ADD whose value already exists in the spec at that point — the
        requested end-state already holds (the interpreter routinely emits
        supporting adds like "ensure this system is listed"). Everything else
        (unknown id, unmatched modify/remove old-value, empty payload) is fatal.

        The appliers are pure, so replaying the same patch sequence one at a
        time reproduces the batch outcome per patch (a patch that referenced a
        not-yet-rebuilt element may diverge in its pruned references, but drop
        attribution — decided before the rebuild — is unaffected).
        """
        benign: list[str] = []
        fatal: list[str] = []
        working = spec
        for patch in patches:
            already_present = patch.action == PatchAction.ADD and cls._add_value_present(
                working, patch
            )
            working, lines, _ = applier.apply(working, [patch], document_text)
            if not cls._dropped_count(lines):
                continue
            payload = json.dumps(patch.payload, ensure_ascii=False, default=str)
            if len(payload) > 160:
                payload = payload[:157] + "..."
            entry = f"{patch.action.value} {patch.target} {payload}"
            (benign if already_present else fatal).append(entry)
        return benign, fatal

    @staticmethod
    def _add_value_present(spec: WorkflowSpec, patch: Patch) -> bool:
        """Whether an ADD patch's value already exists in ``spec`` (case-insensitive).

        Mirrors the duplicate checks in the deterministic appliers: structure
        entities match on their label, scalar facts on the statement within the
        category, metadata list fields on the item value.
        """
        kind = patch.target.partition(":")[0].strip().lower()
        payload = patch.payload

        def _val(*keys: str) -> str:
            for key in keys:
                raw = payload.get(key)
                if isinstance(raw, str) and raw.strip():
                    return raw.strip().lower()
            return ""

        structure = spec.facts.structure
        if kind in ("activity", "decision", "exception", "compensation", "event"):
            label_keys = {"decision": ("question",), "exception": ("reason",)}.get(
                kind, ("name",)
            )
            label = _val(*label_keys, "value")
            if not label:
                return False
            if structure is None:
                # Structureless spec: entity adds degrade to flat facts, so
                # presence is a statement match within the category.
                return any(
                    fact.category.value == kind and fact.statement.lower() == label
                    for fact in spec.facts.facts
                )
            nodes_by_kind: dict[str, list[Any]] = {
                "activity": structure.activities,
                "decision": structure.decisions,
                "exception": structure.exceptions,
                "compensation": structure.compensations,
                "event": structure.events,
            }
            nodes = nodes_by_kind[kind]
            labels = {
                getattr(n, "question", None) or getattr(n, "reason", None)
                or getattr(n, "name", "")
                for n in nodes
            }
            return label in {str(text).lower() for text in labels}
        if kind in ("input", "output", "rule", "api", "system", "timer", "retry"):
            value = _val("value", "statement", "name")
            return bool(value) and any(
                fact.category.value == kind and fact.statement.lower() == value
                for fact in spec.facts.facts
            )
        value = _val("value", "item", "name")
        items = getattr(spec.metadata, kind, None)
        if isinstance(items, list):
            return value in {str(item).lower() for item in items}
        return False

    @staticmethod
    def _bump_patch_version(version: str) -> str | None:
        """``X.Y.Z`` → ``X.Y.(Z+1)``; ``None`` when ``version`` is not semver."""
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
        if match is None:
            return None
        major, minor, patch = match.groups()
        return f"{major}.{minor}.{int(patch) + 1}"

    def _apply_trigger_op(self, project: CompilationProject, op: TriggerOp) -> str:
        """Apply one trigger operation to the project wiring; return a summary line."""
        slugs = {spec.slug for spec in project.specs}
        source, target = op.source_workflow, op.target_workflow
        for endpoint in (source, target):
            if endpoint not in slugs:
                raise CompilationError(
                    f"Trigger operation references unknown workflow '{endpoint}'. "
                    f"Known: {sorted(slugs)}."
                )
        existing_index = next(
            (
                i
                for i, t in enumerate(project.triggers)
                if t.source_workflow == source and t.target_workflow == target
            ),
            -1,
        )
        if op.action is WiringAction.ADD:
            if existing_index != -1:
                raise CompilationError(
                    f"A trigger {source} → {target} already exists — use a modify "
                    "entry instead."
                )
            trigger = self._trigger_payload(op, source, target)
            project.triggers.append(trigger)
            return f"added trigger {source} → {target} ({trigger.mode.value})"
        if existing_index == -1:
            raise CompilationError(
                f"No trigger {source} → {target} to {op.action.value} — check the "
                "edit request against the project's triggers."
            )
        if op.action is WiringAction.REMOVE:
            project.triggers.pop(existing_index)
            return f"removed trigger {source} → {target}"
        trigger = self._trigger_payload(op, source, target)
        project.triggers[existing_index] = trigger
        return f"modified trigger {source} → {target}"

    @staticmethod
    def _trigger_payload(op: TriggerOp, source: str, target: str) -> WorkflowTrigger:
        """The normalized, human-confirmed trigger carried by an add/modify op."""
        if op.trigger is None:
            raise CompilationError(
                f"Trigger {op.action.value} for {source} → {target} carries no "
                "trigger payload."
            )
        return op.trigger.model_copy(
            update={
                "source_workflow": source,
                "target_workflow": target,
                # The human asked for this wiring — it does not need a
                # confirmation checkbox round-trip.
                "user_confirmed": True,
            }
        )

    @staticmethod
    def _apply_xref_op(project: CompilationProject, op: XrefOp) -> str:
        """Apply one cross-reference operation; return a summary line.

        Delegates to :func:`workflow_compiler.spec.wiring.apply_xref_op` so the
        edit path and the conversational path clear an unconfirmed dependency in
        exactly the same way.
        """
        return apply_xref_op(project, op)

    # ------------------------------------------------------------------ #
    # Spec-review diagrams (deterministic preview + on-demand CVPA)
    # ------------------------------------------------------------------ #

    async def build_diagrams(self, project: CompilationProject) -> dict[str, str]:
        """slug → structural Mermaid source, built deterministically (no LLM).

        A preview of the graph approval will build: each spec is seeded into a
        state exactly as :meth:`approve_spec` does (``_seed_state`` injects the
        outgoing triggers), then the deterministic :class:`GraphBuilderAgent`
        renders the diagram. Failures and empty graphs are skipped so callers can
        surface "no diagram yet" per workflow.
        """
        agent = GraphBuilderAgent()
        diagrams: dict[str, str] = {}
        for spec in project.specs:
            try:
                state = await agent.run(self._seed_state(project, spec))
            except WorkflowCompilerError:
                continue
            graph = state.workflow_graph
            diagram = state.mermaid_diagram
            if graph is not None and graph.nodes and diagram is not None:
                diagrams[spec.slug] = diagram.source
        return diagrams

    async def classify_preview(self, project_id: str, slug: str) -> str:
        """CVPA phase-colored Mermaid source for one workflow (LLM, display-only).

        Runs graph build + CVPA classification on a seeded state and returns the
        colored diagram. It is **not** persisted — the authoritative CVPA runs at
        approval; this is a read-only preview for the spec-review UI.
        """
        project = await self._projects.load(project_id)
        spec = next((s for s in project.specs if s.slug == slug), None)
        if spec is None:
            raise CompilationError(f"Project {project_id!r} has no workflow {slug!r}.")
        state = self._seed_state(project, spec)
        state = await GraphBuilderAgent().run(state)
        state = await CVPAClassifierAgent(self._llm, prompt_manager=self._prompts).run(state)
        if state.mermaid_diagram is None:
            raise CompilationError(f"Could not render a diagram for {slug!r}.")
        return state.mermaid_diagram.source

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
                    spec, markdown, project.document_text,
                    project.cross_references, project.triggers,
                )
                project.cross_references = result.cross_references
                project.triggers = result.triggers
                self._replace_spec(project, result.spec)
            self._fold_changes(project, markdown_by_slug.get(CHANGES_SLUG))

        selected = [
            spec
            for spec in project.specs
            if workflows is None or spec.slug in workflows
        ]
        if not selected:
            raise ApprovalError(f"Project {project_id!r} has no matching specs to approve.")

        # The change spec is part of the same gate: a component with no proposed
        # change is a hole the post-approval change outputs cannot fill. Blocking
        # findings stop approval unless the caller accepts incomplete input.
        if project.change_spec is not None:
            change_findings = await self._validate_changes(project)
            project.validation_findings[CHANGES_SLUG] = change_findings
            blocking_changes = [
                f for f in change_findings if f.severity is Severity.BLOCKING
            ]
            if blocking_changes and not accept_incomplete:
                raise ApprovalError(
                    "changes.md has blocking findings — resolve them (or approve with "
                    "accept_incomplete): "
                    + "; ".join(f.message for f in blocking_changes)
                )

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

        # Cross-workflow integrity is recomputed here rather than read back from the
        # last validate: approve must never gate on a finding that a since-edited
        # spec has already fixed.
        cross_blocking: dict[str, list[SpecFinding]] = {}
        if not accept_incomplete:
            for finding in self._validate_triggers_and_dependencies(project):
                if finding.severity is Severity.BLOCKING:
                    cross_blocking.setdefault(finding.workflow, []).append(finding)

        project.spec_approval_status = ApprovalStatus.APPROVED
        project.stage = ProjectStage.COMPILING
        needs_attention = False
        total = len(selected)
        grounder = self.grounder_for(project)

        for index, spec in enumerate(selected, start=1):
            name = f"compile:{spec.slug}"
            _emit(progress, ProgressEvent(
                phase="approve", name=name, status="start", index=index, total=total,
            ))
            started = time.perf_counter()
            # Same gate validate runs, plus this workflow's cross-workflow breakage.
            gate, state = self._gate_findings(
                project, spec, accept_incomplete=accept_incomplete
            )
            blocking = [*cross_blocking.get(spec.slug, []), *gate]
            self._record_gate_findings(project, spec.slug, blocking)
            if blocking:
                # Blocked workflows are skipped, not fatal: the healthy ones still
                # compile. The project ends NEEDS_ATTENTION and every skipped
                # workflow carries the blocking findings that explain why.
                needs_attention = True
                _emit(progress, ProgressEvent(
                    phase="approve", name=name, status="done", index=index, total=total,
                    seconds=time.perf_counter() - started, stage="blocked",
                ))
                continue  # nothing compiled — no timing recorded for this slug
            if grounder is not None:
                # Ground the Temporal-design prompt the same way the extraction
                # prompts were: real module / activity / type names win.
                state.kg_context = await grounder.block_for(state.document_text)
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
                    SpecFinding(
                        severity=Severity.BLOCKING,
                        workflow=spec.slug,
                        section="Graph review",
                        message=(
                            f"graph health {health:.2f} below threshold "
                            f"{self._threshold:.2f} — left pending for manual review"
                            + (f"; issues: {'; '.join(issues)}" if issues else "")
                        ),
                        suggestion="review and approve the graph manually",
                    )
                )
            elapsed = time.perf_counter() - started
            self._record_timing(project, name, elapsed)
            _emit(progress, ProgressEvent(
                phase="approve", name=name, status="done", index=index, total=total,
                seconds=elapsed, stage=state.stage.value,
            ))

        project.stage = (
            ProjectStage.NEEDS_ATTENTION if needs_attention else ProjectStage.COMPLETED
        )
        if grounder is not None:
            self._record_grounding(project, grounder)
        project.touch()
        if persist:
            await self._projects.save(project)
        return project

    def _gate_findings(
        self,
        project: CompilationProject,
        spec: WorkflowSpec,
        *,
        accept_incomplete: bool = False,
    ) -> tuple[list[SpecFinding], WorkflowState]:
        """The pre-compile gate: what stops ``spec`` compiling, and the state it would compile.

        Deterministic and side-effect free (no LLM, no persistence) so **validate and
        approve enforce exactly the same conditions** — a spec that validates clean is
        a spec that will compile. Returns the blocking findings (empty when the spec is
        ready) together with the seeded, checklist-amended state approval hands to the
        back-end, so approval never has to re-derive it.
        """
        findings: list[SpecFinding] = []

        segment = next((s for s in project.segments if s.slug == spec.slug), None)
        if (
            segment is not None
            and not segment.sliced
            and len(project.segments) > 1
            and not accept_incomplete
        ):
            # The segmenter fell back to the full document: this spec merges every
            # workflow's content and would compile to a mega-workflow. Never do that
            # silently — surface it as a blocking finding.
            findings.append(
                SpecFinding(
                    severity=Severity.BLOCKING,
                    workflow=spec.slug,
                    section="Segmentation",
                    message=(
                        "this workflow's document segment could not be isolated "
                        "(the full document was used as its text), so its spec "
                        "merges every workflow's content"
                    ),
                    suggestion=(
                        "fix the section titles / spec content and re-compile, "
                        "or override with accept_incomplete"
                    ),
                )
            )

        state = checklist_amend.apply(
            self._seed_state(project, spec),
            self._answers(spec),
            accept_as_is=accept_incomplete,
        )
        if state.checklist is not None:
            # One finding per unmet item: its evidence names the offending entities and
            # its question states the edit that clears it, so the user is never left
            # guessing which line of the spec to fix.
            findings.extend(
                SpecFinding(
                    severity=Severity.BLOCKING,
                    workflow=spec.slug,
                    section="Open Questions",
                    field=item.id,
                    message=item.evidence or item.requirement,
                    suggestion=item.question
                    or "answer this open question in the spec, or approve with accept_incomplete",
                )
                for item in state.checklist.unmet_required()
            )
        return findings, state

    @staticmethod
    def _record_gate_findings(
        project: CompilationProject, slug: str, findings: list[SpecFinding]
    ) -> None:
        """Replace ``slug``'s gate findings with ``findings`` (never accumulate stale ones)."""
        kept = [
            f
            for f in project.validation_findings.get(slug, [])
            if f.section not in GATE_SECTIONS
        ]
        project.validation_findings[slug] = [*kept, *findings]

    def _seed_state(self, project: CompilationProject, spec: WorkflowSpec) -> WorkflowState:
        """Build the back-end input state from an approved spec.

        The state's ``document_text`` is the **rendered spec**, not the original
        document: downstream stages (Temporal design prompts, checklist,
        grounding) operate on the normalized, human-approved artifact.
        """
        rendered = render_spec(spec, project.cross_references, project.triggers)
        state = WorkflowState(document_text=rendered, project_id=project.project_id)
        state.workflow_metadata = spec.metadata.model_copy(deep=True)
        state.workflow_facts = spec.facts.model_copy(deep=True)
        state.outgoing_triggers = [
            t.model_copy(deep=True) for t in project.triggers_from(spec.slug)
        ]
        # Make the cross-workflow starts visible to the graph/review stages:
        # inject one TriggerNode per outgoing trigger into the structure copy.
        structure = state.workflow_facts.structure
        if state.outgoing_triggers and structure is not None:
            existing = {t.id for t in structure.triggers}
            counter = 1
            for trigger in state.outgoing_triggers:
                while f"t{counter}" in existing:
                    counter += 1
                existing.add(f"t{counter}")
                structure.triggers.append(
                    TriggerNode(
                        id=f"t{counter}",
                        target_workflow=trigger.target_workflow,
                        mode=trigger.mode.value,
                        condition=trigger.condition,
                    )
                )
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
    def _sub_reporter(progress: ProgressCallback | None) -> Callable[..., None]:
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
        # Clear stale files of workflows an edit removed, so nobody edits a
        # spec the project no longer contains.
        current_slugs = {spec.slug for spec in project.specs}
        for record in project.edit_log:
            for removed_slug in record.workflows_removed:
                if removed_slug in current_slugs:
                    continue  # re-added later under the same slug
                stale = root / f"{removed_slug}.md"
                if stale.exists():
                    stale.unlink()
        paths: list[Path] = []
        for spec in project.specs:
            path = root / f"{spec.slug}.md"
            path.write_text(
                render_spec(spec, project.cross_references, project.triggers),
                encoding="utf-8",
            )
            paths.append(path)
        changes = self.render_changes(project)
        if changes is not None:
            path = root / CHANGES_FILENAME
            path.write_text(changes, encoding="utf-8")
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
        if project.change_spec is not None:
            path = root / CHANGES_FILENAME
            if path.is_file():
                contents[CHANGES_SLUG] = path.read_text(encoding="utf-8")
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
        if project.change_spec is not None:
            grounding = project.grounding
            lines += ["", "## Change Spec"]
            questions = len(project.change_spec.unresolved_questions())
            suffix = f" — {questions} open question(s)" if questions else ""
            lines.append(
                f"- `{CHANGES_FILENAME}` — {len(project.change_spec.components)} "
                f"component change(s){suffix}"
            )
            if grounding is not None and grounding.kb_name:
                lines.append(f"- grounded by knowledge base: {grounding.kb_name}")
            if grounding is not None and grounding.change_request_title:
                lines.append(f"- from change request: {grounding.change_request_title}")
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
                lines += [f"- {f.as_string()}" for f in findings] or ["- none"]
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

"""ChangeOutputsEngine — runs the three post-approval stages for a grounded project.

The engine is deterministic glue: it reads the knowledge base's real files,
prepares the prompts' inputs, calls :class:`ChangeOutputsAgent`, verifies each
answer (Mermaid checks, ``ast.parse`` + repair, unified diff, id numbering) and
records the result on ``project.change_outputs``. Stages run in order
``diagrams → code → tests_doc``; each stage is persisted through the
``persist`` callback the moment it completes (and the code stage after every
file), so a timeout in one stage keeps the earlier outputs. Cancellation
propagates untouched — nothing of the in-flight stage is persisted.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from workflow_compiler.agents.change_outputs import ChangeOutputsAgent
from workflow_compiler.change_outputs.code import (
    check_syntax,
    missing_symbols,
    plan_rewrites,
    ruff_check,
    signature_summary,
    unified_diff,
)
from workflow_compiler.change_outputs.diagrams import (
    DiagramRequest,
    assemble_system_flow,
    check_diagram,
    diagram_kind_of,
    expected_states,
    plan_diagrams,
    states_in,
)
from workflow_compiler.change_outputs.models import (
    STAGES,
    ChangedFile,
    ChangeOutputs,
    CodeChangeBundle,
    DiagramDraft,
    DiagramKind,
    DiagramUpdatePlan,
    FileChecks,
    FileStatus,
    StageRecord,
    TestDocUpdate,
    UpdatedDiagram,
)
from workflow_compiler.change_outputs.tests_doc import (
    linked_ids_from_text,
    merge_test_cases,
    next_tc_ids,
    render_addendum,
)
from workflow_compiler.compiler import ProgressCallback, ProgressEvent, _emit
from workflow_compiler.docs_export.xlsx_writer import TC_TYPES, TestCaseRow, read_test_case_rows
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.kg.grounding import KgGrounder
from workflow_compiler.kg.service import KgService
from workflow_compiler.models.change_spec import ChangeSpec, ChangeType, ComponentKind
from workflow_compiler.models.project import CompilationProject
from workflow_compiler.models.state import WorkflowState
from workflow_compiler.models.temporal import TemporalWorkflowDesign
from workflow_compiler.spec.change_renderer import render_change_spec

#: Persist hook: called with the project after each completed unit of work.
PersistCallback = Callable[[CompilationProject], Awaitable[None]]
#: Loads a per-workflow state (the compiler's ``load_state``).
StateLoader = Callable[[str], Awaitable[WorkflowState]]
#: slug → spec mermaid (the compiler's ``build_diagrams``).
DiagramBuilder = Callable[[CompilationProject], Awaitable[dict[str, str]]]

_DOC_EXCERPT_CHARS = 24_000
_TP_EXCERPT_CHARS = 8_000
_CHANGE_ID = re.compile(r"\b(BCR|CR|RFC|CHG)-\d{2,}\b")


class ChangeOutputsError(CompilationError):
    """One or more stages failed (the others' outputs were persisted)."""


@dataclass
class _Context:
    """Everything the stages share, prepared once per run."""

    corpus_files: list[str]
    changes_md: str
    design_summary: str
    spec_summary: str
    document_excerpt: str
    change_title: str
    change_label: str
    kg_context: str = ""
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def design_summary(designs: Iterable[TemporalWorkflowDesign]) -> str:
    """A compact, prompt-friendly outline of the approved Temporal design(s)."""
    lines: list[str] = []
    for design in designs:
        lines.append(f"Workflow {design.workflow_name} (task queue {design.task_queue or '-'})")
        if design.description:
            lines.append(f"  purpose: {design.description}")
        if design.workflow_inputs:
            lines.append(
                "  inputs: " + ", ".join(f"{p.name}: {p.type}" for p in design.workflow_inputs)
            )
        lines.append(f"  result: {design.result_type}")
        for act in design.activities:
            params = ", ".join(f"{p.name}: {p.type}" for p in act.params) or ", ".join(act.inputs)
            retry = act.retry_policy
            policy = (
                f"; retry {retry.maximum_attempts} attempts" if retry is not None else ""
            )
            timeout = f"; timeout {act.timeout_seconds:g}s" if act.timeout_seconds else ""
            lines.append(
                f"  activity {act.name}({params}) -> {act.result_type}{timeout}{policy}"
                + (f" — {act.description}" if act.description else "")
            )
        for comp in design.compensation_activities:
            params = ", ".join(f"{p.name}: {p.type}" for p in comp.params) or ", ".join(comp.inputs)
            lines.append(
                f"  compensation {comp.name}({params}) compensates {comp.compensates or '-'}"
                + (f" — {comp.description}" if comp.description else "")
            )
        for sig in design.signals:
            lines.append(
                f"  signal {sig.name}({', '.join(sig.payload)})"
                + (f" — {sig.description}" if sig.description else "")
            )
        for query in design.queries:
            lines.append(
                f"  query {query.name}() -> {query.returns or '-'}"
                + (f" — {query.description}" if query.description else "")
            )
        for timer in design.timers:
            lines.append(f"  timer {timer.name} {timer.duration_seconds:g}s")
        for step in design.plan[:60]:
            ref = f" {step.ref}" if step.ref else ""
            lines.append(f"  step {step.id}: {step.kind.value}{ref}"
                         + (f" — {step.description}" if step.description else ""))
    return "\n".join(lines) if lines else "(no Temporal design recorded)"


def _matrix_text(rows: Sequence[TestCaseRow]) -> str:
    if not rows:
        return "(no existing matrix found in the knowledge base)"
    out = []
    for r in rows:
        cells = [
            r.tc_id, r.title, r.preconditions, r.steps, r.expected, r.type, r.automated,
            r.linked, r.notes,
        ]
        out.append(" | ".join(c.replace("\n", " / ").replace("|", "¦") for c in cells))
    return "\n".join(out)


def change_label_of(project: CompilationProject) -> str:
    """The business id of the change (``BCR-001``) from the title / document, else the CR id."""
    title = project.grounding.change_request_title if project.grounding else ""
    for text in (title, project.document_text[:20_000]):
        match = _CHANGE_ID.search(text or "")
        if match:
            return match.group(0)
    return (project.change_request_id or "change")[:8]


class ChangeOutputsEngine:
    """Run the change-output stages for one project (see the module docstring)."""

    def __init__(
        self,
        agent: ChangeOutputsAgent,
        kg: KgService,
        *,
        load_state: StateLoader,
        build_diagrams: DiagramBuilder | None = None,
        grounder: KgGrounder | None = None,
        provider_name: str = "",
        model_name: str = "",
    ) -> None:
        self._agent = agent
        self._kg = kg
        self._load_state = load_state
        self._build_diagrams = build_diagrams
        self._grounder = grounder
        self._provider = provider_name
        self._model = model_name

    # ------------------------------------------------------------------ run
    async def run(
        self,
        project: CompilationProject,
        *,
        stages: Sequence[str] | None = None,
        progress: ProgressCallback | None = None,
        persist: PersistCallback | None = None,
    ) -> ChangeOutputs:
        """Run ``stages`` (default: all, in order) and return the outputs.

        Every stage is recorded on ``project.change_outputs`` and persisted when
        it finishes; a failed stage is recorded as failed and the run continues
        with the next one, then :class:`ChangeOutputsError` summarises the
        failures. ``asyncio.CancelledError`` propagates immediately.
        """
        if project.kb_id is None:
            raise CompilationError("Change outputs need a knowledge-base-grounded project.")
        wanted = [s for s in STAGES if stages is None or s in stages]
        if not wanted:
            raise CompilationError(f"No such stage; choose from {', '.join(STAGES)} or 'all'.")
        outputs = project.change_outputs or ChangeOutputs()
        project.change_outputs = outputs
        ctx = await self._prepare(project)
        outputs.warnings = [w for w in outputs.warnings if not w.startswith("grounding:")]
        outputs.warnings.extend(ctx.warnings)
        for source in ctx.sources:
            if source not in outputs.provenance:
                outputs.provenance.append(source)
        failures: list[str] = []
        total = len(wanted)
        for index, name in enumerate(wanted, start=1):
            record = outputs.stage(name)
            record.status = "running"
            record.error = ""
            record.provider = self._provider
            record.model = self._model
            _emit(progress, ProgressEvent(
                phase="change_outputs", name=name, status="start", index=index, total=total,
            ))
            started = time.perf_counter()
            try:
                if name == "diagrams":
                    await self._run_diagrams(project, ctx, outputs)
                elif name == "code":
                    await self._run_code(project, ctx, outputs, persist=persist)
                else:
                    await self._run_tests_doc(project, ctx, outputs)
            except asyncio.CancelledError:
                record.status = "pending" if record.status == "running" else record.status
                raise
            except Exception as exc:  # a stage failure must not lose the others
                record.status = "failed"
                record.error = str(exc) or exc.__class__.__name__
                failures.append(f"{name}: {record.error}")
            else:
                record.status = "done"
            elapsed = time.perf_counter() - started
            record.seconds = elapsed
            record.finished_at = datetime.now(UTC)
            outputs.timings[name] = elapsed
            outputs.generated_at = datetime.now(UTC)
            project.touch()
            if persist is not None:
                await persist(project)
            _emit(progress, ProgressEvent(
                phase="change_outputs", name=name, status="done", index=index, total=total,
                seconds=elapsed, stage=record.status,
            ))
        if failures:
            raise ChangeOutputsError("change outputs: " + "; ".join(failures))
        return outputs

    # -------------------------------------------------------------- prepare
    async def _prepare(self, project: CompilationProject) -> _Context:
        assert project.kb_id is not None
        corpus_files = await self._kg.list_files(project.kb_id)
        spec = project.change_spec
        grounding = project.grounding
        changes_md = (
            render_change_spec(
                spec,
                kb_id=project.kb_id,
                kb_name=grounding.kb_name if grounding else "",
                change_request_id=project.change_request_id,
                change_request_title=grounding.change_request_title if grounding else "",
            )
            if spec is not None
            else "(no change spec)"
        )
        designs: list[TemporalWorkflowDesign] = []
        for workflow_id in project.workflow_ids.values():
            try:
                state = await self._load_state(workflow_id)
            except Exception:
                continue
            if state.temporal_design is not None:
                designs.append(state.temporal_design)
        from workflow_compiler.spec.renderer import render_spec

        spec_parts: list[str] = []
        for wf_spec in project.specs:
            try:
                spec_parts.append(
                    render_spec(wf_spec, project.cross_references, project.triggers)[:6000]
                )
            except Exception:
                continue
        title = (
            grounding.change_request_title
            if grounding and grounding.change_request_title
            else (project.nickname or "the approved change")
        )
        ctx = _Context(
            corpus_files=corpus_files,
            changes_md=changes_md,
            design_summary=design_summary(designs),
            spec_summary="\n\n".join(spec_parts) or "(no workflow spec)",
            document_excerpt=project.document_text[:_DOC_EXCERPT_CHARS],
            change_title=title,
            change_label=change_label_of(project),
        )
        if self._grounder is not None and spec is not None:
            query = " ".join(
                c.name for c in spec.components if c.kind is not ComponentKind.DOC
            )[:2000]
            result = await self._grounder.context_for(query or project.document_text[:2000])
            ctx.kg_context = result.block if not result.empty else ""
            ctx.sources = list(result.sources)
            if result.low_confidence:
                ctx.warnings.append(
                    f"grounding: low retrieval confidence (coverage {result.coverage:.2f})"
                )
        return ctx

    # ------------------------------------------------------------- diagrams
    async def _read_text(self, kb_id: str, path: str) -> str:
        return (await self._kg.read_file(kb_id, path)).text

    async def _run_diagrams(
        self, project: CompilationProject, ctx: _Context, outputs: ChangeOutputs
    ) -> None:
        assert project.kb_id is not None
        kb_id = project.kb_id
        requests = plan_diagrams(project.change_spec, ctx.corpus_files)
        for request in requests:
            if request.source_path:
                request.original = await self._read_text(kb_id, request.source_path)
        state_original = next(
            (r.original for r in requests if r.kind is DiagramKind.STATE and r.original), None
        )
        required = expected_states(project.change_spec, states_in(state_original or ""))
        partial_required = {s for s in required if s not in states_in(state_original or "")}
        original_text = "\n\n".join(
            f"### {r.name} ({r.kind.value}) — {r.source_path}\n```mermaid\n"
            f"{(r.original or '').rstrip()}\n```"
            for r in requests
            if r.original is not None
        ) or "(none)"
        new_text = "\n".join(
            f"- {r.name} ({r.kind.value}) — {'; '.join(r.reasons) or 'new diagram'}"
            for r in requests
            if r.original is None
        ) or "(none)"
        plan = await self._agent.update_diagrams(
            change_title=ctx.change_title,
            change_spec=ctx.changes_md,
            design_summary=ctx.design_summary,
            spec_summary=ctx.spec_summary,
            original_diagrams=original_text,
            new_diagrams=new_text,
            required_states=", ".join(sorted(required)) or "(none)",
            kg_context=ctx.kg_context,
        )
        diagrams = self._diagrams_from(plan, requests, required, partial_required)
        failing = [d for d in diagrams if d.checks]
        if failing:
            note = "\n".join(
                f"- {d.name}: {'; '.join(d.checks)}" for d in failing
            )
            repaired = await self._agent.update_diagrams(
                change_title=ctx.change_title,
                change_spec=ctx.changes_md,
                design_summary=ctx.design_summary,
                spec_summary=ctx.spec_summary,
                original_diagrams=original_text,
                new_diagrams=new_text,
                required_states=", ".join(sorted(required)) or "(none)",
                kg_context=ctx.kg_context,
                repair_note=(
                    "\nYOUR PREVIOUS ANSWER FAILED THESE CHECKS — fix them this time:\n"
                    + note + "\n"
                ),
            )
            second = {
                d.name.lower(): d
                for d in self._diagrams_from(repaired, requests, required, partial_required)
            }
            for i, diagram in enumerate(diagrams):
                other = second.get(diagram.name.lower())
                if other is not None and (
                    len(other.checks) < len(diagram.checks) or not diagram.updated.strip()
                ):
                    diagrams[i] = other
        for diagram in diagrams:
            if diagram.checks:
                outputs.warnings.append(f"diagram {diagram.name}: {'; '.join(diagram.checks)}")
        workflow_diagrams: dict[str, str] = {}
        if self._build_diagrams is not None:
            try:
                workflow_diagrams = await self._build_diagrams(project)
            except Exception as exc:  # the spec diagram is a bonus, never fatal
                outputs.warnings.append(f"workflow diagram: {exc}")
        for slug, mermaid in workflow_diagrams.items():
            diagrams.append(
                UpdatedDiagram(
                    name=f"{slug}-workflow.mmd",
                    kind=DiagramKind.WORKFLOW,
                    original=None,
                    updated=mermaid,
                    notes="Structural diagram of the approved workflow specification.",
                )
            )
        flow_path = next(
            (p for p in ctx.corpus_files if p.lower().endswith("system-flow-diagram.md")), None
        ) or next(
            (
                p for p in ctx.corpus_files
                if "/diagrams/" in p.lower() and p.lower().endswith(".md")
            ),
            None,
        )
        flow_original = await self._read_text(kb_id, flow_path) if flow_path else None
        outputs.system_flow_md = assemble_system_flow(
            flow_original,
            [d for d in diagrams if d.kind is not DiagramKind.WORKFLOW],
            workflow_diagrams,
            change_title=f"{ctx.change_label} — {ctx.change_title}"
            if ctx.change_label not in ctx.change_title
            else ctx.change_title,
        )
        outputs.diagrams = diagrams
        for request in requests:
            if request.source_path and request.source_path not in outputs.provenance:
                outputs.provenance.append(request.source_path)
        if flow_path and flow_path not in outputs.provenance:
            outputs.provenance.append(flow_path)

    @staticmethod
    def _diagrams_from(
        plan: DiagramUpdatePlan,
        requests: Sequence[DiagramRequest],
        required: set[str],
        partial_required: set[str],
    ) -> list[UpdatedDiagram]:
        by_name: dict[str, DiagramDraft] = {
            d.name.strip().lower(): d for d in plan.diagrams if d.name.strip()
        }
        by_kind: dict[str, list[DiagramDraft]] = {}
        for item in plan.diagrams:
            by_kind.setdefault(item.kind.strip().lower(), []).append(item)
        diagrams: list[UpdatedDiagram] = []
        taken: set[int] = set()
        for request in requests:
            draft: DiagramDraft | None = by_name.get(request.name.lower())
            if draft is None:
                candidates = [
                    d for d in by_kind.get(request.kind.value, []) if id(d) not in taken
                ]
                draft = candidates[0] if candidates else None
            updated = draft.mermaid.strip() if draft is not None else ""
            if draft is not None:
                taken.add(id(draft))
            diagram = UpdatedDiagram(
                name=request.name,
                kind=request.kind,
                original=request.original,
                updated=(_strip_fence(updated) + "\n") if updated else "",
                notes=draft.notes.strip() if draft is not None else "",
                source_path=request.source_path,
            )
            if not updated:
                diagram.checks = ["model returned no diagram"]
                if request.original:
                    diagram.updated = request.original
                    diagram.notes = "Kept the original: the model returned no update."
            else:
                need = required if request.kind is DiagramKind.STATE else (
                    partial_required if request.kind is DiagramKind.STATE_PARTIAL else set()
                )
                diagram.checks = check_diagram(diagram, required_states=need)
            diagrams.append(diagram)
        # Extra diagrams the model volunteered under a new name are kept too.
        for draft in plan.diagrams:
            if id(draft) in taken or not draft.name.strip() or not draft.mermaid.strip():
                continue
            name = draft.name.strip()
            if not name.lower().endswith(".mmd"):
                name += ".mmd"
            diagram = UpdatedDiagram(
                name=name,
                kind=diagram_kind_of(name, draft.mermaid),
                original=None,
                updated=_strip_fence(draft.mermaid.strip()) + "\n",
                notes=draft.notes.strip(),
            )
            diagram.checks = check_diagram(diagram)
            diagrams.append(diagram)
        return diagrams

    # ----------------------------------------------------------------- code
    async def _run_code(
        self,
        project: CompilationProject,
        ctx: _Context,
        outputs: ChangeOutputs,
        *,
        persist: PersistCallback | None,
    ) -> None:
        assert project.kb_id is not None
        kb_id = project.kb_id
        py_files = [p for p in ctx.corpus_files if p.endswith(".py")]
        texts: dict[str, str] = {}
        for path in py_files:
            texts[path] = await self._read_text(kb_id, path)
        spec = project.change_spec
        plan = plan_rewrites(spec, texts)
        bundle = CodeChangeBundle(
            order=list(plan.order), import_root=plan.import_root or "src", code_root=plan.code_root,
        )
        # Start from unchanged copies of everything so a partial run is still a bundle.
        files: dict[str, ChangedFile] = {
            path: ChangedFile(path=path, status=FileStatus.UNCHANGED, original=text, updated=text)
            for path, text in texts.items()
        }
        removed = self._removed_files(spec, plan.order)
        for path in removed:
            files[path] = ChangedFile(
                path=path, status=FileStatus.REMOVED, original=texts[path], updated="",
                unified_diff=unified_diff(path, texts[path], ""),
                reason="removed by the change spec",
            )
        bundle.files = [files[p] for p in texts]
        outputs.code = bundle
        rewritten: dict[str, str] = {}
        for path in plan.order:
            if path in removed:
                continue
            components = plan.components_by_file.get(path, [])
            comp_text = "\n".join(
                f"- {c.kind.value} `{c.name}` ({c.change_type.value}): "
                f"EXISTING: {c.existing.strip() or '—'} → PROPOSED: {c.proposed.strip() or '—'}"
                for c in components
            ) or "- (none named directly; this file depends on a rewritten module)"
            siblings = "\n\n".join(
                f"### {p}\n{signature_summary(code)}" for p, code in rewritten.items()
            ) or "(none yet — this is the first file)"
            reason = "; ".join(plan.reasons.get(path, [])) or "named by the change spec"
            result = await self._agent.rewrite_file(
                path=path,
                reason=reason,
                components=comp_text,
                current_content=texts[path],
                sibling_signatures=siblings,
                change_spec=ctx.changes_md,
                design_summary=ctx.design_summary,
                document_excerpt=ctx.document_excerpt,
                import_root=plan.import_root or "src",
                kg_context=ctx.kg_context,
            )
            entry = files[path]
            entry.reason = reason
            checks = FileChecks(truncated=result.truncated)
            if not result.found:
                entry.status = FileStatus.UNCHANGED
                entry.notes = "The model returned no code; the original file was kept."
                outputs.warnings.append(f"code {path}: model returned no code")
                entry.checks = checks
                rewritten[path] = texts[path]
                if persist is not None:
                    await persist(project)
                continue
            code = result.code
            ok, err = check_syntax(code)
            if ok and not result.closed:
                ok, err = False, "the answer was cut off before the closing fence"
            problem = "" if ok else f"SyntaxError: {err}"
            if ok:
                required = self._required_symbols(components)
                missing = missing_symbols(code, required)
                if missing:
                    problem = (
                        "The file must define / use these change-spec symbols but does not: "
                        + ", ".join(missing)
                    )
                else:
                    ruff_ok, ruff_out = ruff_check(code)
                    checks.ruff_ok = ruff_ok
                    checks.ruff_output = ruff_out
                    if ruff_ok is False and "F821" in ruff_out:
                        problem = "ruff found undefined names:\n" + ruff_out
            if problem:
                fixed = await self._agent.repair_file(path=path, code=code, error=problem)
                checks.repaired = True
                if fixed.found and fixed.code.strip():
                    ok2, err2 = check_syntax(fixed.code)
                    if ok2 or not ok:
                        code = fixed.code
                        ok, err = ok2, err2
                ruff_ok, ruff_out = ruff_check(code) if ok else (None, "")
                checks.ruff_ok = ruff_ok
                checks.ruff_output = ruff_out
            checks.ast_ok = ok
            checks.ast_error = "" if ok else err
            if not ok:
                outputs.warnings.append(f"code {path}: does not parse after repair ({err})")
            entry.checks = checks
            entry.updated = code
            entry.status = FileStatus.MODIFIED if code != texts[path] else FileStatus.UNCHANGED
            entry.unified_diff = unified_diff(path, texts[path], code)
            entry.notes = result.notes
            rewritten[path] = code
            if persist is not None:
                await persist(project)
        for path in texts:
            if path not in outputs.provenance:
                outputs.provenance.append(path)

    @staticmethod
    def _removed_files(spec: ChangeSpec | None, order: Sequence[str]) -> set[str]:
        """Files the change spec removes outright (a ``module`` component with ``remove``)."""
        if spec is None:
            return set()
        from workflow_compiler.change_outputs.code import resolve_component_file

        removed: set[str] = set()
        for component in spec.components:
            if component.kind is not ComponentKind.MODULE:
                continue
            if component.change_type is not ChangeType.REMOVE:
                continue
            target = resolve_component_file(component, list(order))
            if target is not None:
                removed.add(target)
        return removed

    @staticmethod
    def _required_symbols(components: Iterable[object]) -> list[str]:
        """Change-spec identifiers that must appear in the rewritten file.

        Names of added / modified activities, types, signals and queries (plain
        identifiers only; test-case ids and file paths are not symbols).
        """
        required: list[str] = []
        for component in components:
            kind = getattr(component, "kind", None)
            change = getattr(component, "change_type", None)
            name = str(getattr(component, "name", "")).strip().strip("`")
            if change is ChangeType.REMOVE or change is ChangeType.VERIFY:
                continue
            if kind not in (
                ComponentKind.ACTIVITY, ComponentKind.TYPE, ComponentKind.SIGNAL,
                ComponentKind.QUERY, ComponentKind.WORKFLOW,
            ):
                continue
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and name not in required:
                required.append(name)
        return required

    # ------------------------------------------------------------ tests_doc
    async def _run_tests_doc(
        self, project: CompilationProject, ctx: _Context, outputs: ChangeOutputs
    ) -> None:
        assert project.kb_id is not None
        kb_id = project.kb_id
        matrix_path = ""
        rows: list[TestCaseRow] = []
        for path in ctx.corpus_files:
            if not path.lower().endswith(".xlsx"):
                continue
            try:
                found = read_test_case_rows(await self._kg.read_bytes(kb_id, path))
            except Exception:
                continue
            if found:
                matrix_path, rows = path, found
                break
        tp_path = next(
            (
                p for p in ctx.corpus_files
                if p.lower().endswith(".docx")
                and ("test-plan" in p.lower() or "/tp-" in p.lower() or "testplan" in p.lower())
            ),
            None,
        )
        tp_text = await self._read_text(kb_id, tp_path) if tp_path else ""
        tests_summary = "\n\n".join(
            f"### {f.path}\n{signature_summary(f.updated)}"
            for f in outputs.code.files
            if f.status is FileStatus.MODIFIED
            and f.path.rsplit("/", 1)[-1].startswith("test")
        ) or "(the code stage has not produced updated tests yet)"
        catalog_ids: list[str] = []
        try:
            catalog_ids = list((await self._kg.catalog(kb_id)).test_cases)
        except Exception:
            catalog_ids = []
        next_id = next_tc_ids([*catalog_ids, *(r.tc_id for r in rows)], 1)[0]
        plan = await self._agent.update_test_cases(
            change_title=ctx.change_title,
            change_request_id=ctx.change_label,
            change_spec=ctx.changes_md,
            existing_matrix=_matrix_text(rows),
            test_plan_excerpt=tp_text[:_TP_EXCERPT_CHARS] or "(no test plan found)",
            tests_summary=tests_summary,
            design_summary=ctx.design_summary,
            next_tc_id=next_id,
            tc_types=", ".join(TC_TYPES),
            kg_context=ctx.kg_context,
        )
        merged, changed, new_ids = merge_test_cases(
            rows, plan.new_cases, plan.updated_cases,
            start_hint=next_id, change_note=f"{ctx.change_label}: new scenario",
        )
        ids = linked_ids_from_text(tp_text)
        doc_ids = linked_ids_from_text(project.document_text[:20_000])
        linked_tdd = doc_ids.get("TDD", ids.get("TDD", ""))
        linked_epic = doc_ids.get("EPIC", ids.get("EPIC", ""))
        tests_file = next(
            (
                f.path for f in outputs.code.files
                if f.path.rsplit("/", 1)[-1].startswith("test_")
            ),
            "tests/",
        )
        update = TestDocUpdate(
            test_cases=merged,
            changed_ids=changed,
            new_ids=new_ids,
            linked_tdd=linked_tdd,
            linked_epic=linked_epic,
            test_plan_id=ids.get("TP", ""),
            change_request_id=ctx.change_label,
            matrix_source=matrix_path,
            notes=[
                f"Test plan addendum amends {ids.get('TP', 'the test plan')}"
                + (f" ({tp_path})" if tp_path else "") + ".",
            ],
        )
        update.test_plan_addendum_md = render_addendum(
            plan.addendum,
            test_plan_id=update.test_plan_id,
            change_request_id=ctx.change_label,
            change_title=ctx.change_title,
            linked_tdd=linked_tdd,
            linked_epic=linked_epic,
            changed_ids=changed,
            new_ids=new_ids,
            rows=merged,
            tests_file=tests_file,
        )
        outputs.tests_doc = update
        for path in (matrix_path, tp_path or ""):
            if path and path not in outputs.provenance:
                outputs.provenance.append(path)
        if not rows:
            outputs.warnings.append("tests_doc: no existing test-case matrix found; new rows only")


def _strip_fence(text: str) -> str:
    """Drop a stray Markdown fence the model may have wrapped a diagram in."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    return stripped.strip("\n")


__all__ = [
    "ChangeOutputsEngine",
    "ChangeOutputsError",
    "PersistCallback",
    "StageRecord",
    "change_label_of",
    "design_summary",
]

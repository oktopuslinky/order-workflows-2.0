"""``workflow-compiler cr …`` — change requests from the command line.

    cr create <kb-id> <bcr.docx|.md|.txt> [--title] [--provider] [--model]
    cr list
    cr show <cr-id>
    cr draft <cr-id> <impact|epic|stories|tdd> [--auto] [--out FILE]
    cr approve <cr-id> <step>
    cr export <cr-id> <step> [--version N] [--out FILE]
    cr delete <cr-id>

``cr draft --auto`` runs the whole step unattended: starts the wizard if
needed, drafts the clarifying questions, answers each with its first suggested
option (or skips it when there is none), then drafts the artifact — the
scripted path the live E2E uses. Same file store as the API
(``<state-root>/change_requests``); like the rest of the CLI it bypasses auth.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from workflow_compiler.change.service import ChangeRequestService
    from workflow_compiler.models.change import ChangeRequest

cr_app = typer.Typer(
    name="cr",
    help="Change requests: BCR + knowledge base → guided wizard → Impact/EPIC/Stories/TDD.",
    no_args_is_help=True,
)
console = Console()


def _domain_errors[**P, T](
    fn: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        from workflow_compiler.exceptions import WorkflowCompilerError

        try:
            return await fn(*args, **kwargs)
        except WorkflowCompilerError as exc:
            console.print(str(exc), style="red", markup=False, highlight=False)
            raise typer.Exit(1) from None

    return wrapper


def _service(timeout: float = 400.0) -> ChangeRequestService:
    from workflow_compiler.change.service import ChangeRequestService
    from workflow_compiler.cli.kb import _provider_factory
    from workflow_compiler.cli.kb import _service as kg_service
    from workflow_compiler.config import get_settings
    from workflow_compiler.storage.change_store import FileChangeRequestStore

    settings = get_settings()
    return ChangeRequestService(
        FileChangeRequestStore(settings.state_store_path),
        kg_service(timeout),
        _provider_factory(timeout),
        kg_budget=settings.change_kg_budget,
    )


def _say(text: str, style: str | None = None) -> None:
    console.print(text, style=style, markup=False, highlight=False)


# ------------------------------------------------------------------ create


@cr_app.command(name="create")
def create_cmd(
    kb_id: str = typer.Argument(..., help="Knowledge base id to ground the change request in."),
    document: Path = typer.Argument(..., exists=True, help="BCR document (.docx/.md/.txt/.pdf)."),
    title: str | None = typer.Option(None, "--title", help="Override the parsed title."),
    provider: str | None = typer.Option(None, "--provider", help="LLM provider for the wizard."),
    model: str | None = typer.Option(None, "--model", help="Model override for the wizard."),
) -> None:
    """Register a change request (parses metadata/requirements deterministically)."""
    asyncio.run(_run_create(kb_id, document, title, provider, model))


@_domain_errors
async def _run_create(
    kb_id: str, document: Path, title: str | None, provider: str | None, model: str | None
) -> None:
    service = _service()
    cr = await service.create(
        kb_id,
        data=document.read_bytes(),
        filename=document.name,
        title=title,
        provider=provider,
        model=model,
    )
    _say(f"Created change request {cr.cr_id}", "bold")
    _print_cr(cr)


# -------------------------------------------------------------- list/show


@cr_app.command(name="list")
def list_cmd() -> None:
    """List change requests."""
    asyncio.run(_run_list())


@_domain_errors
async def _run_list() -> None:
    items = await _service().list_all()
    if not items:
        _say("No change requests yet.", "dim")
        return
    table = Table(title="Change requests")
    for col in ("cr_id", "doc", "title", "kb", "stage", "step", "updated"):
        table.add_column(col)
    for cr in items:
        current = cr.wizard.current
        table.add_row(
            cr.cr_id,
            cr.bcr_meta.doc_id or "",
            cr.title,
            cr.kb_name or cr.kb_id,
            cr.stage.value,
            current.kind.value if current else "done",
            cr.updated_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@cr_app.command(name="show")
def show_cmd(cr_id: str = typer.Argument(..., help="Change request id.")) -> None:
    """Show a change request's wizard state and artifact versions."""
    asyncio.run(_run_show(cr_id))


@_domain_errors
async def _run_show(cr_id: str) -> None:
    _print_cr(await _service().get(cr_id))


# ------------------------------------------------------------------ draft


@cr_app.command(name="draft")
def draft_cmd(
    cr_id: str = typer.Argument(..., help="Change request id."),
    step: str = typer.Argument(..., help="impact | epic | stories | tdd"),
    auto: bool = typer.Option(
        False, "--auto", help="Answer every question with its first suggested option, then draft."
    ),
    out: Path | None = typer.Option(None, "--out", help="Write the drafted markdown here."),
    timeout: float = typer.Option(400.0, "--timeout", help="Per-request LLM timeout (s)."),
) -> None:
    """Draft one wizard step (use --auto for the unattended, scripted flow)."""
    asyncio.run(_run_draft(cr_id, step, auto, out, timeout))


@_domain_errors
async def _run_draft(cr_id: str, step: str, auto: bool, out: Path | None, timeout: float) -> None:
    from workflow_compiler.models.change import STEP_LABELS, ArtifactKind, StepStatus

    kind = ArtifactKind(step)
    service = _service(timeout)
    cr = await service.get(cr_id)
    if cr.wizard.started_at is None:
        cr = await service.start(cr_id)
        _say(
            f"Started wizard: {cr.ids.epic_id}, {cr.ids.tdd_id}; "
            f"{len(cr.impact_table)} impact rows",
            "dim",
        )
    wizard_step = cr.wizard.step(kind)
    current = cr.wizard.current
    if auto and current is not None and current.kind == kind:
        if wizard_step.status == StepStatus.PENDING and not wizard_step.questions:
            _say(f"Drafting {STEP_LABELS[kind].lower()} questions…", "dim")
            cr = await service.start_questions(cr_id, kind)
            wizard_step = cr.wizard.step(kind)
        for question in wizard_step.questions:
            if question.status != "pending":
                continue
            _say(f"Q: {question.text}")
            if question.options:
                answer = question.options[0].label
                _say(f"A: {answer}", "cyan")
                cr, outcome = await service.answer(cr_id, answer, option=answer)
                if outcome.followup:
                    q = outcome.question
                    followup_answer = (
                        q.prompt_options[0].label
                        if q.prompt_options
                        else "Use your best judgement."
                    )
                    _say(f"Q: {q.prompt}")
                    _say(f"A: {followup_answer}", "cyan")
                    cr, _ = await service.answer(cr_id, followup_answer)
            else:
                _say("A: (skipped)", "dim")
                cr = await service.skip(cr_id)

    def progress(message: str, done: int, total: int) -> None:
        _say(f"  {message}" + (f" ({done}/{total})" if total else ""), "dim")

    cr = await service.draft(cr_id, kind, progress=progress)
    artifact = cr.artifacts.get(kind)
    _say(f"Drafted {STEP_LABELS[kind]} v{artifact.version} ({artifact.history[-1].note})", "bold")
    if out is not None:
        out.write_text(artifact.markdown, encoding="utf-8")
        _say(f"Wrote {out}")
    else:
        console.print(artifact.markdown, markup=False, highlight=False)


# ---------------------------------------------------------- approve/export


@cr_app.command(name="approve")
def approve_cmd(
    cr_id: str = typer.Argument(..., help="Change request id."),
    step: str = typer.Argument(..., help="impact | epic | stories | tdd"),
) -> None:
    """Approve a drafted artifact (advances the wizard)."""
    asyncio.run(_run_approve(cr_id, step))


@_domain_errors
async def _run_approve(cr_id: str, step: str) -> None:
    from workflow_compiler.models.change import ArtifactKind

    cr = await _service().approve(cr_id, ArtifactKind(step))
    current = cr.wizard.current
    _say(f"Approved {step}; next step: {current.kind.value if current else 'none (complete)'}")


@cr_app.command(name="export")
def export_cmd(
    cr_id: str = typer.Argument(..., help="Change request id."),
    step: str | None = typer.Argument(
        None, help="impact | epic | stories | tdd (omit with --format zip)"
    ),
    fmt: str = typer.Option(
        "md", "--format", "-f", help="md | docx | xlsx (impact only) | zip (whole change request)"
    ),
    version: int | None = typer.Option(
        None, "--version", help="Artifact version (markdown only; default latest)"
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write here (default: stdout for markdown, else the export's filename)",
    ),
) -> None:
    """Export an artifact (markdown / Word / TC preview) or the whole change request as a zip.

    Word/Excel exports are deterministic renders of the artifact's latest version, labelled
    ``DRAFT vN — not approved`` (and suffixed ``-DRAFT``) when the artifact was not approved.
    """
    asyncio.run(_run_export(cr_id, step, fmt, version, out))


@_domain_errors
async def _run_export(
    cr_id: str, step: str | None, fmt: str, version: int | None, out: Path | None
) -> None:
    from workflow_compiler.models.change import ArtifactKind

    fmt = fmt.lower().lstrip(".")
    service = _service()
    if fmt == "zip":
        export = await service.export_bundle(cr_id)
    else:
        if step is None:
            raise typer.BadParameter("STEP is required unless --format zip is used.")
        if fmt not in ("md", "docx", "xlsx"):
            raise typer.BadParameter("--format must be md, docx, xlsx or zip.")
        if fmt == "md":
            _cr, artifact, entry = await service.artifact(
                cr_id, ArtifactKind(step), version=version
            )
            markdown = entry.markdown if entry is not None else artifact.markdown
            if out is not None:
                out.write_text(markdown, encoding="utf-8")
                _say(f"Wrote {out}")
            else:
                console.print(markdown, markup=False, highlight=False)
            return
        if version is not None:
            raise typer.BadParameter("--version applies to markdown exports only.")
        export = await service.export(cr_id, ArtifactKind(step), fmt)
    target = out if out is not None else Path(export.filename)
    if target.is_dir():
        target = target / export.filename
    target.write_bytes(export.data)
    _say(f"Wrote {target} ({len(export.data)} bytes)")


@cr_app.command(name="delete")
def delete_cmd(cr_id: str = typer.Argument(..., help="Change request id.")) -> None:
    """Delete a change request."""
    asyncio.run(_run_delete(cr_id))


@_domain_errors
async def _run_delete(cr_id: str) -> None:
    await _service().delete(cr_id)
    _say(f"Deleted {cr_id}")


# ------------------------------------------------------------------ print


def _print_cr(cr: ChangeRequest) -> None:
    from workflow_compiler.models.change import STEP_LABELS

    _say(f"{cr.bcr_meta.doc_id or 'CR'} — {cr.title}", "bold")
    _say(f"  id: {cr.cr_id}   kb: {cr.kb_name} ({cr.kb_id})   stage: {cr.stage.value}")
    _say(f"  provider: {cr.wizard.provider or 'default'}   requirements: {len(cr.requirements)}")
    if cr.ids.epic_id:
        _say(
            f"  ids: {cr.ids.epic_id}, {cr.ids.tdd_id}"
            + (f", stories {', '.join(cr.ids.story_ids)}" if cr.ids.story_ids else "")
        )
    for step in cr.wizard.steps:
        artifact = cr.artifacts.get(step.kind)
        marker = "▶" if cr.wizard.current is step else " "
        answered = sum(1 for q in step.questions if q.status == "answered")
        _say(
            f"  {marker} {STEP_LABELS[step.kind]:<18} {step.status.value:<9} "
            f"questions {answered}/{len(step.questions)}  artifact v{artifact.version} "
            f"({artifact.status.value})"
        )
    for warning in cr.warnings:
        _say(f"  ! {warning}", "yellow")

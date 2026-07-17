"""Typer command-line interface for workflow-compiler.

One pipeline: ``compile <doc> --spec-dir`` writes editable spec files, the user
iterates ``validate`` until satisfied, and ``approve-spec`` compiles every
workflow through to Temporal code. ``approve`` / ``reject`` remain as the manual
override for workflows whose graph health fell below the auto-approve threshold,
and ``show`` displays a stored workflow state.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console

from workflow_compiler import __version__

if TYPE_CHECKING:
    from workflow_compiler.compiler import ProgressCallback, ReviewConfig
    from workflow_compiler.interfaces.llm import BaseLLMProvider
    from workflow_compiler.project_compiler import ProjectCompiler
    from workflow_compiler.storage import FileStateStore

app = typer.Typer(
    name="workflow-compiler",
    help="Compile business workflow documents into canonical artifacts.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"workflow-compiler {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """workflow-compiler command-line interface."""


@app.command()
def compile(
    document: Path = typer.Argument(..., exists=True, readable=True, help="Path to the document."),
    provider: str = typer.Option(
        None, "--provider", help="Override the LLM provider (e.g. 'mock'). Defaults to .env."
    ),
    model: str = typer.Option(None, "--model", help="Override the model id."),
    timeout: float = typer.Option(120.0, "--timeout", help="Per-request timeout in seconds."),
    persist: bool = typer.Option(True, help="Persist the resulting project state."),
    review: bool = typer.Option(
        True,
        "--review/--no-review",
        help="Sequential review passes on the LLM stages (on by default).",
    ),
    spec_dir: Path = typer.Option(
        Path("./specs"),
        "--spec-dir",
        help="Discover every workflow in the document, write one editable spec file "
        "per workflow to this directory, and stop at the spec gate (resume with "
        "'validate' / 'approve-spec').",
    ),
) -> None:
    """Compile a workflow document into editable spec files (stops at the spec gate)."""
    import asyncio

    asyncio.run(
        _run_compile_spec(document, provider, model, timeout, spec_dir, review, persist)
    )


@app.command(name="validate")
def validate_cmd(
    project_id: str = typer.Argument(..., help="Project id from 'compile --spec-dir'."),
    spec_dir: Path = typer.Option(
        Path("./specs"), "--spec-dir", exists=True, file_okay=False,
        help="Directory holding the edited spec files.",
    ),
    provider: str = typer.Option(None, "--provider", help="Override the LLM provider."),
    model: str = typer.Option(None, "--model", help="Override the model id."),
    timeout: float = typer.Option(120.0, "--timeout", help="Per-request timeout in seconds."),
) -> None:
    """Fold edited spec files back in and run the spec validator passes."""
    import asyncio

    asyncio.run(_run_validate(project_id, spec_dir, provider, model, timeout))


@app.command(name="edit")
def edit_cmd(
    project_id: str = typer.Argument(..., help="Project id from 'compile --spec-dir'."),
    edit_file: Path = typer.Argument(
        ..., exists=True, readable=True, dir_okay=False,
        help="Edit-request Markdown file (see docs/EDIT_FORMAT_GUIDE.md).",
    ),
    workflow: list[str] = typer.Option(
        None, "--workflow", help="Only allow edits to these workflow slug(s)."
    ),
    author: str = typer.Option(None, "--author", help="Author recorded in the edit log."),
    spec_dir: Path = typer.Option(
        Path("./specs"), "--spec-dir",
        help="Re-write the updated spec files to this directory.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Preview the edit (parse + interpret + summary) without applying anything.",
    ),
    provider: str = typer.Option(None, "--provider", help="Override the LLM provider."),
    model: str = typer.Option(None, "--model", help="Override the model id."),
    timeout: float = typer.Option(120.0, "--timeout", help="Per-request timeout in seconds."),
) -> None:
    """Apply a workflow edit-request document, then re-enter the spec gate."""
    import asyncio

    asyncio.run(
        _run_edit(
            project_id, edit_file, list(workflow or []), author, spec_dir,
            provider, model, timeout, dry_run=dry_run,
        )
    )


@app.command(name="approve-spec")
def approve_spec_cmd(
    project_id: str = typer.Argument(..., help="Project id from 'compile --spec-dir'."),
    spec_dir: Path = typer.Option(
        Path("./specs"), "--spec-dir", exists=True, file_okay=False,
        help="Directory holding the edited spec files.",
    ),
    workflow: list[str] = typer.Option(
        None, "--workflow", help="Approve only these workflow slug(s); default: all."
    ),
    reviewer: str = typer.Option(None, "--reviewer", help="Reviewer name to record."),
    out_dir: Path = typer.Option(
        Path("./generated"), "--out-dir",
        help="Root for generated output; code lands in <out-dir>/<project-id>/<slug>/.",
    ),
    accept_incomplete: bool = typer.Option(
        False, "--accept-incomplete",
        help="Proceed even when required open questions remain unanswered.",
    ),
    allow_unconfirmed: bool = typer.Option(
        False, "--allow-unconfirmed",
        help="Proceed without confirming the cross-workflow dependencies.",
    ),
    provider: str = typer.Option(None, "--provider", help="Override the LLM provider."),
    model: str = typer.Option(None, "--model", help="Override the model id."),
    timeout: float = typer.Option(120.0, "--timeout", help="Per-request timeout in seconds."),
) -> None:
    """Approve the specs and compile every workflow through graph → code."""
    import asyncio

    asyncio.run(
        _run_approve_spec(
            project_id, spec_dir, list(workflow or []), reviewer, out_dir,
            accept_incomplete, allow_unconfirmed, provider, model, timeout,
        )
    )


@app.command()
def approve(
    workflow_id: str = typer.Argument(..., help="Workflow id to approve."),
    reviewer: str = typer.Option(None, help="Reviewer identity."),
    provider: str = typer.Option(None, "--provider", help="Override the LLM provider."),
    model: str = typer.Option(None, "--model", help="Override the model id."),
    timeout: float = typer.Option(120.0, "--timeout", help="Per-request timeout in seconds."),
    out: Path = typer.Option(
        None, "--out", help="Write the CVPA-colored Mermaid diagram to this file."
    ),
    out_dir: Path = typer.Option(
        Path("./generated"), "--out-dir",
        help="Root for generated output; code lands in <out-dir>/<workflow-id>/.",
    ),
) -> None:
    """Approve a graph and produce CVPA + Temporal artifacts."""
    import asyncio

    asyncio.run(_run_approve(workflow_id, reviewer, provider, model, timeout, out, out_dir))


@app.command()
def reject(
    workflow_id: str = typer.Argument(..., help="Workflow id to reject."),
    reviewer: str = typer.Option(None, help="Reviewer identity."),
    reason: str = typer.Option(None, help="Reason for rejection."),
) -> None:
    """Reject a generated workflow graph (no LLM required)."""
    import asyncio

    asyncio.run(_run_reject(workflow_id, reviewer, reason))


@app.command(name="show")
def show(
    workflow_id: str = typer.Argument(..., help="Workflow id to load and display."),
) -> None:
    """Load and display a stored workflow state (no LLM required)."""
    import asyncio

    asyncio.run(_run_show(workflow_id))


@app.command()
def models() -> None:
    """List the models the local eGPU gateway currently exposes."""
    import asyncio

    from workflow_compiler.config import get_settings
    from workflow_compiler.exceptions import (
        LLMProviderError,
        ProviderConnectionError,
        ProviderTimeoutError,
    )
    from workflow_compiler.llm.factory import build_local_provider

    async def _run() -> list[str]:
        provider = build_local_provider(get_settings())
        try:
            return await provider.list_models()
        finally:
            await provider.aclose()

    try:
        available = asyncio.run(_run())
    except (ProviderConnectionError, ProviderTimeoutError):
        console.print("[red]Local eGPU gateway is not reachable.[/] Check LLM_API_BASE / the box.")
        raise typer.Exit(1) from None
    except LLMProviderError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from None

    if not available:
        console.print("[yellow]The gateway reported no models.[/]")
        return
    console.print("[bold]Local gateway models:[/]")
    for model_id in available:
        console.print(f"  • {model_id}")


def _clean_domain_errors[**P, T](
    fn: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Print domain errors as a clean message and exit 1 instead of a traceback.

    Domain failures (a malformed edit request, an unknown project id, a provider
    outage) carry actionable messages — the stack trace adds nothing for a CLI
    user. ``typer.Exit`` raised inside the runner passes through untouched.
    """

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        from workflow_compiler.exceptions import WorkflowCompilerError

        try:
            return await fn(*args, **kwargs)
        except WorkflowCompilerError as exc:
            # markup=False: messages quote spec text that rich would misparse.
            console.print(str(exc), style="red", markup=False, highlight=False)
            raise typer.Exit(1) from None

    return wrapper


def _build_provider(
    provider_name: str | None, model: str | None, timeout: float
) -> BaseLLMProvider:
    """Construct an LLM provider from CLI overrides or settings (.env)."""
    from workflow_compiler.config import get_settings
    from workflow_compiler.llm import ProviderFactory
    from workflow_compiler.llm.factory import build_fallback_provider, build_local_provider

    settings = get_settings()
    name = provider_name or settings.llm_provider
    factory = ProviderFactory()
    if name == "mock":
        return factory.create("mock")
    # For the local gateway, --model overrides the *local* model, and generic
    # kwargs (which carry the Nemotron model) must not leak onto it.
    if name == "local-fallback":
        return build_fallback_provider(settings, local_model_override=model, timeout=timeout)
    if name == "local":
        return build_local_provider(settings, model_override=model, timeout=timeout)
    return factory.create(name, model=model or settings.llm_model, timeout=timeout)


def _file_store() -> FileStateStore:
    """Build the file-backed state store rooted at the configured path."""
    from workflow_compiler.config import get_settings
    from workflow_compiler.storage import FileStateStore

    return FileStateStore(get_settings().state_store_path)


def _make_progress() -> ProgressCallback:
    """Return a progress sink that prints each pipeline step with a timestamp.

    Gives a live, timed view of what stage is running and how long each takes —
    e.g. ``12:34:58 ✓ temporal-generator  1.42s → temporal_designed``.
    """
    from datetime import datetime

    def on_event(event) -> None:  # type: ignore[no-untyped-def]
        timestamp = datetime.now().strftime("%H:%M:%S")
        position = f"[dim]{event.index}/{event.total}[/]"
        # Nested sub-steps (e.g. the review pipeline's generate + 3 passes) are
        # indented under their parent agent and use a quieter marker.
        nested = getattr(event, "phase", None) == "review-pass"
        indent = "       " if nested else "  "
        if event.status == "start":
            marker = "[dim]>[/]" if nested else "[cyan]>>[/]"
            console.print(
                f"{indent}[dim]{timestamp}[/] {marker} {position} {event.name} [dim]...[/]"
            )
        else:
            marker = "[dim]ok[/]" if nested else "[green]OK[/]"
            stage = f" [dim]-> {event.stage}[/]" if event.stage else ""
            console.print(
                f"{indent}[dim]{timestamp}[/] {marker} {position} {event.name}  "
                f"[bold]{event.seconds:.2f}s[/]{stage}"
            )

    return on_event


async def _aclose(provider: object) -> None:
    aclose = getattr(provider, "aclose", None)
    if aclose is not None:
        await aclose()


def _write_diagram(state: object, out: Path | None) -> None:
    """Write the state's Mermaid diagram to ``out`` if both are present."""
    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)
    if out is None or state.mermaid_diagram is None:
        return
    out.write_text(state.mermaid_diagram.source, encoding="utf-8")
    console.print(f"[green]Mermaid diagram written to[/] {out}")


def _write_code(
    state: object, out_dir: Path | None, *, package_dir_name: str | None = None
) -> None:
    """Write the generated Temporal code bundle into ``out_dir`` if present.

    ``package_dir_name`` overrides the design's LLM-chosen package name as the
    directory — project mode passes the deterministic workflow slug so two
    workflows whose designs picked the same name can never overwrite each other.
    """
    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)
    if out_dir is None or state.temporal_code is None:
        return
    package_dir = out_dir / (package_dir_name or state.temporal_code.package_name)
    for generated in state.temporal_code.files:
        path = package_dir / generated.path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = generated.content
        if not content.endswith("\n"):
            content += "\n"
        path.write_text(content, encoding="utf-8")
    console.print(
        f"[green]Temporal code written to[/] {package_dir} "
        f"({len(state.temporal_code.files)} files)"
    )


def _review_config(enabled_flag: bool) -> ReviewConfig:
    """Build a ReviewConfig from settings, applying the CLI --review/--no-review override."""
    from workflow_compiler.compiler import ReviewConfig
    from workflow_compiler.config import get_settings

    return ReviewConfig.from_settings(get_settings(), enabled=enabled_flag)


def _project_compiler(provider: BaseLLMProvider, review: bool) -> ProjectCompiler:
    """Build a ProjectCompiler wired to the configured file stores."""
    from workflow_compiler.compiler import WorkflowCompiler
    from workflow_compiler.config import get_settings
    from workflow_compiler.project_compiler import ProjectCompiler
    from workflow_compiler.storage.project_store import FileProjectStore

    settings = get_settings()
    inner = WorkflowCompiler(
        llm_provider=provider,
        state_store=_file_store(),
        review=_review_config(review),
    )
    return ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=FileProjectStore(settings.state_store_path),
        segmentation_review=review,
        graph_health_threshold=settings.graph_health_threshold,
    )


def _print_project(project: object, spec_dir: Path) -> None:
    """Print the project's workflows, dependencies, warnings, and findings."""
    from workflow_compiler.models import CompilationProject

    assert isinstance(project, CompilationProject)
    console.print(f"\n[bold green]project_id[/]: {project.project_id}")
    console.print(f"[bold]stage[/]: {project.stage.value}")
    console.print(f"[bold]workflows[/] ({len(project.specs)}):")
    for spec in project.specs:
        open_questions = len(spec.unresolved_questions())
        note = f"  [yellow]{open_questions} open question(s)[/]" if open_questions else ""
        console.print(f"  - [cyan]{spec_dir / (spec.slug + '.md')}[/] — {spec.metadata.name}{note}")
    for reference in project.cross_references:
        status = "[green]confirmed[/]" if reference.user_confirmed else "[yellow]UNCONFIRMED[/]"
        console.print(
            f"  dependency: {reference.source_workflow}.{reference.output_field} -> "
            f"{reference.target_workflow}.{reference.input_field} ({status})"
        )
    for warning in project.warnings:
        console.print(f"  [yellow]warning[/]: {warning}")
    from workflow_compiler.models import Severity

    colors = {
        Severity.BLOCKING: "bold red",
        Severity.WARNING: "yellow",
        Severity.INFO: "dim",
    }
    for slug, findings in project.validation_findings.items():
        for finding in findings:
            color = colors.get(finding.severity, "yellow")
            loc = f" {finding.location}" if finding.location else ""
            suffix = f" ([italic]{finding.suggestion}[/])" if finding.suggestion else ""
            console.print(
                f"  [{color}]{finding.tag}[/] [cyan]{slug}[/]{loc}: {finding.message}{suffix}"
            )


@_clean_domain_errors
async def _run_compile_spec(
    document: Path,
    provider_name: str | None,
    model: str | None,
    timeout: float,
    spec_dir: Path,
    review: bool,
    persist: bool,
) -> None:
    from workflow_compiler.ingestion import DocumentParserFactory

    console.print(f"[bold]Ingesting[/] {document} ...")
    content = DocumentParserFactory().parse(document)
    provider = _build_provider(provider_name, model, timeout)
    console.print(f"[bold]Provider[/]: {provider.name}")
    compiler = _project_compiler(provider, review)
    try:
        console.print("[bold]Compiling to specification[/] (segment → per-workflow facts) ...")
        project = await compiler.compile_document(
            content.text, persist=persist, progress=_make_progress()
        )
    finally:
        await _aclose(provider)

    compiler.write_spec_files(project, spec_dir)
    _print_project(project, spec_dir)
    console.print(
        f"\nReview and edit the spec files in [cyan]{spec_dir}[/], then run:\n"
        f"  [cyan]workflow-compiler validate {project.project_id} --spec-dir {spec_dir}[/]\n"
        f"  [cyan]workflow-compiler approve-spec {project.project_id} "
        f"--spec-dir {spec_dir}[/]"
    )


@_clean_domain_errors
async def _run_validate(
    project_id: str,
    spec_dir: Path,
    provider_name: str | None,
    model: str | None,
    timeout: float,
) -> None:
    provider = _build_provider(provider_name, model, timeout)
    console.print(f"[bold]Provider[/]: {provider.name}")
    compiler = _project_compiler(provider, review=True)
    try:
        project = await compiler.load_project(project_id)
        edited = compiler.read_spec_files(project, spec_dir)
        console.print(
            f"[bold]Validating[/] {len(project.specs)} spec(s) "
            f"({len(edited)} file(s) read from {spec_dir}) ..."
        )
        project = await compiler.validate_specs(
            project_id, markdown_by_slug=edited, progress=_make_progress()
        )
    finally:
        await _aclose(provider)

    compiler.write_spec_files(project, spec_dir)
    _print_project(project, spec_dir)
    if project.has_blocking_findings():
        console.print(
            "\n[bold red]Blocking findings must be resolved before generation.[/] "
            "Fix the [bold red]BLOCK[/] items above in the spec files and re-run validate."
        )
        raise typer.Exit(code=1)
    console.print(
        "\nSpec files re-written with the validator's fixes. Review the findings, "
        "edit again if needed, then run "
        f"[cyan]workflow-compiler approve-spec {project_id} --spec-dir {spec_dir}[/]"
    )


@_clean_domain_errors
async def _run_edit(
    project_id: str,
    edit_file: Path,
    workflows: list[str],
    author: str | None,
    spec_dir: Path,
    provider_name: str | None,
    model: str | None,
    timeout: float,
    *,
    dry_run: bool = False,
) -> None:
    provider = _build_provider(provider_name, model, timeout)
    console.print(f"[bold]Provider[/]: {provider.name}")
    compiler = _project_compiler(provider, review=True)
    edit_document = edit_file.read_text(encoding="utf-8")
    try:
        verb = "Previewing" if dry_run else "Applying"
        console.print(f"[bold]{verb} edit request[/] {edit_file} ...")
        if dry_run:
            preview = await compiler.preview_edit(
                project_id,
                edit_document,
                workflows=workflows or None,
                author=author,
                progress=_make_progress(),
            )
            project, record = preview.project, preview.record
        else:
            project = await compiler.edit_specs(
                project_id,
                edit_document,
                workflows=workflows or None,
                author=author,
                progress=_make_progress(),
            )
            record = project.edit_log[-1]
    finally:
        await _aclose(provider)

    if dry_run:
        console.print("\n[bold yellow]Preview only — nothing was applied.[/]")
    else:
        compiler.write_spec_files(project, spec_dir)
        console.print(f"\n[bold green]Edit applied[/] (edit id {record.edit_id})")
    for slug, lines in record.summary.items():
        console.print(f"  [cyan]{slug}[/]:")
        for line in lines:
            console.print(f"    - {line}")
    if dry_run:
        console.print(
            "\nRe-run without [cyan]--dry-run[/] to apply these changes."
        )
        return
    _print_project(project, spec_dir)
    console.print(
        f"\nSpec files re-written to [cyan]{spec_dir}[/]. The project is back at "
        "the spec gate — review the changes, then run:\n"
        f"  [cyan]workflow-compiler validate {project_id} --spec-dir {spec_dir}[/]\n"
        f"  [cyan]workflow-compiler approve-spec {project_id} --spec-dir {spec_dir}[/]"
    )


@_clean_domain_errors
async def _run_approve_spec(
    project_id: str,
    spec_dir: Path,
    workflows: list[str],
    reviewer: str | None,
    out_dir: Path | None,
    accept_incomplete: bool,
    allow_unconfirmed: bool,
    provider_name: str | None,
    model: str | None,
    timeout: float,
) -> None:
    provider = _build_provider(provider_name, model, timeout)
    console.print(f"[bold]Provider[/]: {provider.name}")
    compiler = _project_compiler(provider, review=True)
    try:
        project = await compiler.load_project(project_id)
        edited = compiler.read_spec_files(project, spec_dir)
        console.print("[bold]Approving specs[/] and compiling each workflow ...")
        project = await compiler.approve_spec(
            project_id,
            workflows=workflows or None,
            reviewer=reviewer,
            markdown_by_slug=edited,
            accept_incomplete=accept_incomplete,
            allow_unconfirmed_references=allow_unconfirmed,
            progress=_make_progress(),
        )
        await _write_project_code(compiler, project, out_dir)
    finally:
        await _aclose(provider)

    compiler.write_spec_files(project, spec_dir)
    _print_project(project, spec_dir)
    from workflow_compiler.models import ProjectStage

    if project.stage is ProjectStage.NEEDS_ATTENTION:
        skipped = [s.slug for s in project.specs if s.slug not in project.workflow_ids]
        if skipped:
            console.print(
                f"\n[bold red]No code generated for[/]: {', '.join(skipped)} — "
                "blocked by the findings above."
            )
        console.print(
            "\n[bold yellow]Some workflows need attention[/] — see the findings above. "
            "Fix the spec files and re-run approve-spec, or approve individual "
            "workflows with [cyan]workflow-compiler approve <workflow-id>[/]."
        )
    else:
        console.print("\n[bold green]All workflows compiled.[/]")


async def _write_project_code(compiler: object, project: object, out_dir: Path | None) -> None:
    """Write each workflow's code bundle + Mermaid diagram under ``out_dir/<slug>/``.

    The directory is keyed by the deterministic workflow *slug* (never the
    design's LLM-chosen package name), so two workflows can never overwrite each
    other. The diagram is written even when the workflow did not complete —
    seeing the flow is exactly what the user needs to fix a pending graph.
    """
    from workflow_compiler.models import CompilationProject, CompilationStage
    from workflow_compiler.project_compiler import ProjectCompiler

    assert isinstance(compiler, ProjectCompiler)
    assert isinstance(project, CompilationProject)
    if out_dir is None:
        return
    # Everything nests under <out-dir>/<project-id>/ so repeated runs never
    # litter the working directory with loose bundle folders.
    root = out_dir / project.project_id
    designs = {}
    for slug, workflow_id in project.workflow_ids.items():
        state = await compiler.workflow_compiler.load_state(workflow_id)
        package_dir_name = slug.replace("-", "_")
        workflow_dir = root / package_dir_name
        if state.mermaid_diagram is not None:
            workflow_dir.mkdir(parents=True, exist_ok=True)
            _write_diagram(state, workflow_dir / "diagram.mmd")
        if state.stage is CompilationStage.COMPLETED:
            _write_code(state, root, package_dir_name=package_dir_name)
            if state.temporal_design is not None:
                designs[slug] = state.temporal_design
        else:
            console.print(f"  [yellow]{slug}[/]: not completed, no code written")

    # Project glue: shared contracts + trigger topology next to the bundles.
    if len(designs) > 1 or project.triggers:
        from workflow_compiler.codegen.temporal.project_generator import (
            generate_project_files,
        )

        root.mkdir(parents=True, exist_ok=True)
        for generated in generate_project_files(designs, project.triggers):
            (root / generated.path).write_text(generated.content, encoding="utf-8")
        console.print(
            f"  [green]project[/]: wrote contracts.py + README.md to {root}"
        )


@_clean_domain_errors
async def _run_approve(
    workflow_id: str,
    reviewer: str | None,
    provider_name: str | None,
    model: str | None,
    timeout: float,
    out: Path | None = None,
    out_dir: Path | None = None,
) -> None:
    from workflow_compiler.compiler import WorkflowCompiler

    provider = _build_provider(provider_name, model, timeout)
    compiler = WorkflowCompiler(llm_provider=provider, state_store=_file_store())
    try:
        console.print(f"[bold]Approving[/] {workflow_id} (CVPA → Temporal → code) ...")
        state = await compiler.approve_graph(
            workflow_id, reviewer=reviewer, progress=_make_progress()
        )
    finally:
        await _aclose(provider)

    _print_cvpa(state)
    _print_temporal(state)
    _print_temporal_code(state)
    console.print(
        f"\n[bold green]Approved[/] {state.workflow_id}  stage={state.stage.value}"
    )
    _write_diagram(state, out)
    _write_code(state, None if out_dir is None else out_dir / state.workflow_id)


@_clean_domain_errors
async def _run_reject(workflow_id: str, reviewer: str | None, reason: str | None) -> None:
    from workflow_compiler.compiler import WorkflowCompiler

    compiler = WorkflowCompiler(state_store=_file_store())
    state = await compiler.reject_graph(workflow_id, reviewer=reviewer, reason=reason)
    console.print(
        f"[bold red]Rejected[/] {state.workflow_id}  "
        f"approval={state.approval_status.value}"
    )
    if reason:
        console.print(f"  reason: {reason}")


@_clean_domain_errors
async def _run_show(workflow_id: str) -> None:
    from workflow_compiler.compiler import WorkflowCompiler

    compiler = WorkflowCompiler(state_store=_file_store())
    state = await compiler.load_state(workflow_id)
    _print_summary(state)
    _print_review(state)
    _print_cvpa(state)
    _print_temporal(state)
    _print_temporal_code(state)
    console.print(
        f"\n[bold]stage[/]: {state.stage.value}  "
        f"[bold]approval[/]: {state.approval_status.value}"
    )


def _print_summary(state: object) -> None:
    from rich.panel import Panel
    from rich.table import Table

    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)

    metadata = state.workflow_metadata
    if metadata is not None:
        table = Table(title="Workflow Metadata", show_header=False)
        table.add_row("Name", metadata.name)
        table.add_row("Purpose", metadata.purpose or "-")
        table.add_row("Actors", ", ".join(metadata.actors) or "-")
        table.add_row("Systems", ", ".join(metadata.systems) or "-")
        table.add_row("Triggers", ", ".join(metadata.trigger_events) or "-")
        table.add_row("Start states", ", ".join(metadata.start_states) or "-")
        table.add_row("End states", ", ".join(metadata.end_states) or "-")
        console.print(table)

    if state.workflow_facts is not None:
        counts: dict[str, int] = {}
        for fact in state.workflow_facts.facts:
            counts[fact.category.value] = counts.get(fact.category.value, 0) + 1
        fact_table = Table(title="Facts by Category")
        fact_table.add_column("Category")
        fact_table.add_column("Count", justify="right")
        for category, count in sorted(counts.items()):
            fact_table.add_row(category, str(count))
        console.print(fact_table)

    _print_structure(state)

    graph = state.workflow_graph
    if graph is not None:
        console.print(f"[bold]Graph[/]: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    scores = state.confidence_scores
    if scores is not None:
        console.print(
            f"[bold]Confidence[/]: metadata={scores.metadata} "
            f"facts={scores.facts} graph={scores.graph}"
        )

    if state.mermaid_diagram is not None:
        console.print(
            Panel(state.mermaid_diagram.source, title="Mermaid (paste into mermaid.live)")
        )


def _print_structure(state: object) -> None:
    """Render the structural IR (relational fact structure) if one was extracted.

    This is the *first* of the two IRs — the id-referenced control/relation graph
    produced before the mermaid diagram, from which the diagram is wired.
    """
    from rich.table import Table

    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)
    facts = state.workflow_facts
    structure = facts.structure if facts is not None else None
    if structure is None or structure.is_empty():
        return

    table = Table(title="Structural IR (relational fact structure, pre-diagram)")
    table.add_column("Kind")
    table.add_column("Id")
    table.add_column("Detail")
    table.add_column("Links")
    for a in structure.activities:
        group = f"parallel_group={a.parallel_group}" if a.parallel_group else "-"
        table.add_row("activity", a.id, a.name, group)
    for d in structure.decisions:
        table.add_row(
            "decision", d.id, d.question, f"after={d.after} yes={d.yes_target} no={d.no_target}"
        )
    for e in structure.exceptions:
        table.add_row("exception", e.id, e.reason, f"raised_by={e.raised_by}")
    for c in structure.compensations:
        table.add_row("compensation", c.id, c.name, f"compensates={c.compensates}")
    for ev in structure.events:
        table.add_row("event", ev.id, ev.name, f"emitted_by={ev.emitted_by}")
    for t in structure.transitions:
        table.add_row("transition", "-", f"{t.source} -> {t.target}", f"trigger={t.trigger or '-'}")
    console.print(table)


def _print_plan(design: object) -> None:
    """Render the execution IR (the Temporal plan) as an indented step tree.

    This is the *second* IR — the ordered control/data-flow plan the code
    generator walks. ASCII-only markers keep output safe when piped on Windows.
    """
    from workflow_compiler.models import BindingSource, TemporalStep, TemporalWorkflowDesign

    assert isinstance(design, TemporalWorkflowDesign)
    if not design.plan:
        console.print(
            "[dim]Execution IR (plan): none provided — the generator will "
            "synthesize a linear plan from declarations + graph order.[/]"
        )
        return

    console.print("[bold]Execution IR[/] (Temporal plan, drives code generation):")

    def render(steps: list[TemporalStep], depth: int) -> None:
        pad = "  " * depth
        for step in steps:
            detail = step.ref or step.signal or step.timer or step.predicate or ""
            line = f"{pad}- [{step.kind.value}] {step.id}"
            if detail:
                line += f" -> {detail}"
            if step.result_name:
                line += f"  (=> {step.result_name})"
            console.print(f"  {line}")
            for binding in step.bindings:
                src = (
                    binding.source.value
                    if isinstance(binding.source, BindingSource)
                    else binding.source
                )
                console.print(
                    f"  {pad}    input {binding.param} <= {src}:{binding.ref or '-'}"
                )
            for i, lane in enumerate(step.lanes):
                console.print(f"  {pad}    lane[{i}]:")
                render(lane, depth + 3)

    render(design.plan, 0)


def _print_review(state: object) -> None:
    from rich.table import Table

    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)
    report = state.review_report
    if report is None:
        return
    console.print(
        f"[bold]Review[/]: health={report.health_score} confidence={report.confidence} "
        f"({len(report.errors)} errors, {len(report.warnings)} warnings)"
    )
    if report.issues:
        table = Table(title="Review Issues")
        table.add_column("Severity")
        table.add_column("Message")
        table.add_column("Where")
        for issue in report.issues:
            table.add_row(issue.severity.value, issue.message, issue.location or "-")
        console.print(table)


def _print_cvpa(state: object) -> None:
    from rich.table import Table

    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)
    cvpa = state.cvpa_classification
    if cvpa is None:
        return
    table = Table(title="CVPA Classification")
    table.add_column("Node")
    table.add_column("Phase")
    table.add_column("Confidence", justify="right")
    table.add_column("Rationale")
    for assignment in cvpa.assignments:
        table.add_row(
            assignment.node_id,
            assignment.phase.value,
            f"{assignment.confidence:.2f}",
            assignment.rationale or "-",
        )
    console.print(table)


def _print_temporal(state: object) -> None:
    from rich.table import Table

    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)
    design = state.temporal_design
    if design is None:
        return
    console.print(
        f"[bold]Temporal design[/]: workflow=[cyan]{design.workflow_name}[/] "
        f"task_queue={design.task_queue}"
    )
    table = Table(title="Temporal Components")
    table.add_column("Kind")
    table.add_column("Names")
    table.add_row("Activities", ", ".join(a.name for a in design.activities) or "-")
    table.add_row("Signals", ", ".join(s.name for s in design.signals) or "-")
    table.add_row("Queries", ", ".join(q.name for q in design.queries) or "-")
    table.add_row("Child workflows", ", ".join(c.name for c in design.child_workflows) or "-")
    table.add_row("Timers", ", ".join(t.name for t in design.timers) or "-")
    table.add_row(
        "Compensations", ", ".join(c.name for c in design.compensation_activities) or "-"
    )
    console.print(table)
    _print_plan(design)


def _print_temporal_code(state: object) -> None:
    from rich.table import Table

    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)
    bundle = state.temporal_code
    if bundle is None:
        return
    console.print(
        f"[bold]Temporal code[/]: target=[cyan]{bundle.target}[/] "
        f"package=[cyan]{bundle.package_name}[/]"
    )
    table = Table(title="Generated Files")
    table.add_column("File")
    table.add_column("Lines", justify="right")
    for generated in bundle.files:
        table.add_row(generated.path, str(generated.content.count("\n") + 1))
    console.print(table)


if __name__ == "__main__":
    app()

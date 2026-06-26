"""Typer command-line interface for workflow-compiler.

Commands are scaffolded: they parse arguments and render output via Rich, but
defer to the compiler, whose business logic is not implemented yet.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from workflow_compiler import __version__

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
    auto_approve: bool = typer.Option(
        False, "--auto-approve", help="Run the full pipeline end-to-end without the human gate."
    ),
    persist: bool = typer.Option(True, help="Persist the resulting workflow state."),
    out: Path = typer.Option(
        None, "--out", help="Write the Mermaid diagram to this file (CVPA-colored if approved)."
    ),
    out_dir: Path = typer.Option(
        None, "--out-dir", help="Write generated Temporal code to this directory (auto-approve)."
    ),
) -> None:
    """Compile a workflow document into a review-ready state."""
    import asyncio

    asyncio.run(
        _run_compile(document, provider, model, timeout, auto_approve, persist, out, out_dir)
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
        None, "--out-dir", help="Write the generated Temporal code to this directory."
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


def _build_provider(provider_name: str | None, model: str | None, timeout: float):
    """Construct an LLM provider from CLI overrides or settings (.env)."""
    from workflow_compiler.config import get_settings
    from workflow_compiler.llm import ProviderFactory

    settings = get_settings()
    name = provider_name or settings.llm_provider
    factory = ProviderFactory()
    if name == "mock":
        return factory.create("mock")
    return factory.create(name, model=model or settings.llm_model, timeout=timeout)


def _file_store():
    """Build the file-backed state store rooted at the configured path."""
    from workflow_compiler.config import get_settings
    from workflow_compiler.storage import FileStateStore

    return FileStateStore(get_settings().state_store_path)


def _make_progress():
    """Return a progress sink that prints each pipeline step with a timestamp.

    Gives a live, timed view of what stage is running and how long each takes —
    e.g. ``12:34:58 ✓ temporal-generator  1.42s → temporal_designed``.
    """
    from datetime import datetime

    def on_event(event) -> None:  # type: ignore[no-untyped-def]
        timestamp = datetime.now().strftime("%H:%M:%S")
        position = f"[dim]{event.index}/{event.total}[/]"
        if event.status == "start":
            console.print(f"  [dim]{timestamp}[/] [cyan]>>[/] {position} {event.name} [dim]...[/]")
        else:
            stage = f" [dim]-> {event.stage}[/]" if event.stage else ""
            console.print(
                f"  [dim]{timestamp}[/] [green]OK[/] {position} {event.name}  "
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


def _write_code(state: object, out_dir: Path | None) -> None:
    """Write the generated Temporal code bundle into ``out_dir`` if present."""
    from workflow_compiler.models import WorkflowState

    assert isinstance(state, WorkflowState)
    if out_dir is None or state.temporal_code is None:
        return
    package_dir = out_dir / state.temporal_code.package_name
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


async def _run_compile(
    document: Path,
    provider_name: str | None,
    model: str | None,
    timeout: float,
    auto_approve: bool,
    persist: bool,
    out: Path | None = None,
    out_dir: Path | None = None,
) -> None:
    from workflow_compiler.compiler import WorkflowCompiler
    from workflow_compiler.ingestion import DocumentParserFactory

    console.print(f"[bold]Ingesting[/] {document} ...")
    content = DocumentParserFactory().parse(document)
    console.print(
        f"  format={content.document_format.value} chars={content.metadata.char_count}"
    )

    provider = _build_provider(provider_name, model, timeout)
    console.print(f"[bold]Provider[/]: {provider.name}")
    compiler = WorkflowCompiler(llm_provider=provider, state_store=_file_store())
    try:
        console.print("[bold]Compiling[/] (discover → facts → graph → review) ...")
        state = await compiler.compile_document(
            content.text,
            review_mode=not auto_approve,
            persist=persist,
            progress=_make_progress(),
        )
    finally:
        await _aclose(provider)

    _print_summary(state)
    _print_review(state)
    if auto_approve:
        _print_cvpa(state)
        _print_temporal(state)
        _print_temporal_code(state)
    console.print(f"\n[bold green]workflow_id[/]: {state.workflow_id}")
    console.print(
        f"[bold]stage[/]: {state.stage.value}  "
        f"[bold]approval[/]: {state.approval_status.value}"
    )
    if not auto_approve:
        console.print(
            f"Review the graph, then run: "
            f"[cyan]workflow-compiler approve {state.workflow_id}[/]"
        )
    _write_diagram(state, out)
    _write_code(state, out_dir)


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
    _write_code(state, out_dir)


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


@app.command(name="inspect")
def inspect(
    document: Path = typer.Argument(
        ..., exists=True, readable=True, help="Path to a business workflow document."
    ),
    provider: str = typer.Option(
        None,
        "--provider",
        help="Override the LLM provider (e.g. 'mock'). Defaults to settings (.env).",
    ),
    model: str = typer.Option(
        None, "--model", help="Override the model id. Defaults to settings (.env)."
    ),
    timeout: float = typer.Option(
        120.0, "--timeout", help="Per-request timeout in seconds."
    ),
    out: Path = typer.Option(
        None, "--out", help="Write the generated Mermaid diagram to this file."
    ),
) -> None:
    """Preview the pipeline: ingest -> discover -> facts -> graph (no approval).

    Runs the implemented stages end-to-end so the generated graph and Mermaid
    diagram can be inspected before downstream stages are built. Uses the
    configured LLM provider (Nemotron via NVIDIA_API_KEY in .env by default).
    """
    import asyncio

    asyncio.run(_run_inspect(document, provider, model, timeout, out))


async def _run_inspect(
    document: Path,
    provider_name: str | None,
    model: str | None,
    timeout: float,
    out: Path | None,
) -> None:
    from workflow_compiler.agents import (
        FactExtractionAgent,
        GraphBuilderAgent,
        WorkflowDiscoveryAgent,
    )
    from workflow_compiler.config import get_settings
    from workflow_compiler.ingestion import DocumentParserFactory
    from workflow_compiler.llm import ProviderFactory
    from workflow_compiler.models import WorkflowState

    console.print(f"[bold]Ingesting[/] {document} ...")
    content = DocumentParserFactory().parse(document)
    state = WorkflowState(document_text=content.text)
    console.print(
        f"  format={content.document_format.value} "
        f"chars={content.metadata.char_count} sections={len(content.sections)}"
    )

    settings = get_settings()
    name = provider_name or settings.llm_provider
    factory = ProviderFactory()
    if name == "mock":
        provider = factory.create("mock")
    else:
        provider = factory.create(name, model=model or settings.llm_model, timeout=timeout)
    chosen_model = getattr(getattr(provider, "config", None), "model", "-")
    console.print(f"[bold]Provider[/]: {provider.name} (model={chosen_model})")

    try:
        console.print("[bold]Discovering metadata[/] ...")
        state = await WorkflowDiscoveryAgent(provider).run(state)
        console.print("[bold]Extracting facts[/] ...")
        state = await FactExtractionAgent(provider).run(state)
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()

    console.print("[bold]Building graph[/] (deterministic) ...")
    state = await GraphBuilderAgent().run(state)

    _print_summary(state)

    if out is not None and state.mermaid_diagram is not None:
        out.write_text(state.mermaid_diagram.source, encoding="utf-8")
        console.print(f"[green]Mermaid diagram written to[/] {out}")


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

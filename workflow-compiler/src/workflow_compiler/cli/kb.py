"""``workflow-compiler kb …`` — knowledge bases from the command line.

    kb init <zip-or-folder> [--name] [--enrich/--no-enrich] [--provider] [--model]
    kb list
    kb show <kb-id>
    kb ask <kb-id> "<prompt>" [--budget] [--hops] [--json]
    kb impact <kb-id> <seed> [<seed> ...] [--hops]
    kb search <kb-id> "<query>"
    kb delete <kb-id>

Uses the same file store as the API (``<state-root>/knowledge_bases``), so a
knowledge base created here shows up in the UI and vice versa. Like the rest of
the CLI it bypasses auth (``owner_id`` stays ``None``).
"""

from __future__ import annotations

import asyncio
import functools
import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from workflow_compiler.interfaces.llm import BaseLLMProvider
    from workflow_compiler.kg.service import KgService

kb_app = typer.Typer(
    name="kb",
    help="Create and query knowledge bases (corpus → Context Hub graph).",
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


def _provider_factory(timeout: float) -> Callable[[str | None, str | None], BaseLLMProvider]:
    """CLI provider factory: ``--provider``/``--model`` win, else the ``.env`` default."""

    def build(name: str | None, model: str | None) -> BaseLLMProvider:
        from workflow_compiler.cli.main import _build_provider

        return _build_provider(name, model, timeout)

    return build


def _service(timeout: float = 400.0) -> KgService:
    from workflow_compiler.config import get_settings
    from workflow_compiler.kg.service import KgService
    from workflow_compiler.kg.store import FileKnowledgeBaseStore

    settings = get_settings()
    return KgService(
        FileKnowledgeBaseStore(settings.state_store_path),
        _provider_factory(timeout),
        max_upload_bytes=settings.kg_max_upload_mb * 1024 * 1024,
        default_budget=settings.kg_retrieve_budget,
        enrich_call_timeout=timeout,
    )


# ------------------------------------------------------------------ commands


@kb_app.command(name="init")
def init_cmd(
    source: Path = typer.Argument(..., exists=True, help="A corpus zip or a folder."),
    name: str | None = typer.Option(None, "--name", help="Display name (default: file name)."),
    enrich: bool | None = typer.Option(
        None, "--enrich/--no-enrich", help="LLM enrichment (default: .env kg_enrich_default)."
    ),
    provider: str | None = typer.Option(None, "--provider", help="LLM provider for enrichment."),
    model: str | None = typer.Option(None, "--model", help="Model override for enrichment."),
    kb_id: str | None = typer.Option(None, "--id", help="Fixed id instead of a random one."),
    timeout: float = typer.Option(400.0, "--timeout", help="Per-request LLM timeout (s)."),
) -> None:
    """Create a knowledge base from a zip or folder and index it."""
    asyncio.run(_run_init(source, name, enrich, provider, model, kb_id, timeout))


@_domain_errors
async def _run_init(
    source: Path,
    name: str | None,
    enrich: bool | None,
    provider: str | None,
    model: str | None,
    kb_id: str | None,
    timeout: float,
) -> None:
    from workflow_compiler.config import get_settings

    service = _service(timeout)
    label = name or source.stem
    if source.is_dir():
        kb = await service.create_from_path(label, source, kb_id=kb_id)
    else:
        kb = await service.create_from_zip(
            label, source.read_bytes(), filename=source.name, kb_id=kb_id
        )
    do_enrich = get_settings().kg_enrich_default if enrich is None else enrich
    console.print(f"Created knowledge base [bold]{kb.kb_id}[/bold] ({kb.stats.files} files)")

    last: dict[str, str] = {}

    def progress(message: str, done: int, total: int) -> None:
        line = f"  {message} ({done}/{total})" if total else f"  {message}"
        if last.get("line") != line:
            console.print(line, style="dim", markup=False, highlight=False)
            last["line"] = line

    kb = await service.index(
        kb.kb_id, enrich=do_enrich, provider=provider, model=model, progress=progress
    )
    _print_kb(kb)


@kb_app.command(name="list")
def list_cmd() -> None:
    """List knowledge bases."""
    asyncio.run(_run_list())


@_domain_errors
async def _run_list() -> None:
    items = await _service().list_all()
    if not items:
        console.print("No knowledge bases yet. Create one with `workflow-compiler kb init`.")
        return
    table = Table(title="Knowledge bases")
    for col in ("id", "name", "status", "nodes", "edges", "enriched", "indexed"):
        table.add_column(col)
    for kb in items:
        table.add_row(
            kb.kb_id,
            kb.name,
            kb.status,
            str(kb.stats.nodes),
            str(kb.stats.edges),
            "yes" if kb.llm_enriched else "no",
            kb.indexed_at.strftime("%Y-%m-%d %H:%M") if kb.indexed_at else "-",
        )
    console.print(table)


@kb_app.command(name="show")
def show_cmd(kb_id: str = typer.Argument(..., help="Knowledge base id.")) -> None:
    """Show one knowledge base (stats by type, catalog, warnings)."""
    asyncio.run(_run_show(kb_id))


@_domain_errors
async def _run_show(kb_id: str) -> None:
    _print_kb(await _service().get(kb_id))


@kb_app.command(name="ask")
def ask_cmd(
    kb_id: str = typer.Argument(..., help="Knowledge base id."),
    prompt: str = typer.Argument(..., help="What to ground."),
    budget: int | None = typer.Option(None, "--budget", help="Token budget for the packet."),
    hops: int = typer.Option(2, "--hops", help="Traversal depth."),
    as_json: bool = typer.Option(False, "--json", help="Print the packet as JSON."),
) -> None:
    """Retrieve a grounded context packet and print it."""
    asyncio.run(_run_ask(kb_id, prompt, budget, hops, as_json))


@_domain_errors
async def _run_ask(kb_id: str, prompt: str, budget: int | None, hops: int, as_json: bool) -> None:
    packet = await _service().retrieve(kb_id, prompt, budget=budget, max_hops=hops)
    if as_json:
        console.print_json(packet.model_dump_json())
        return
    console.print(packet.rendered, markup=False, highlight=False)
    console.print()
    console.print(
        f"seeds: {', '.join(packet.seeds) or '-'} · tokens: {packet.total_tokens} · "
        f"coverage: {packet.coverage:.2f}"
        + (" · LOW CONFIDENCE" if packet.low_confidence else ""),
        style="dim",
        markup=False,
    )
    for ref in packet.files:
        spans = ", ".join(f"{a}-{b}" for a, b in ref.spans) or "-"
        console.print(f"  {ref.path}  [{ref.band}]  lines {spans}", style="dim", markup=False)


@kb_app.command(name="impact")
def impact_cmd(
    kb_id: str = typer.Argument(..., help="Knowledge base id."),
    seeds: list[str] = typer.Argument(..., help="Node ids or search terms."),
    hops: int = typer.Option(2, "--hops", help="Traversal depth."),
) -> None:
    """Deterministic impact table from the seeds."""
    asyncio.run(_run_impact(kb_id, seeds, hops))


@_domain_errors
async def _run_impact(kb_id: str, seeds: list[str], hops: int) -> None:
    rows = await _service().impact(kb_id, seeds, max_hops=hops)
    table = Table(title=f"Impact of {', '.join(seeds)} (≤{hops} hops)")
    for col in ("hops", "type", "node", "path", "via"):
        table.add_column(col)
    for row in rows:
        table.add_row(str(row.hops), row.type, row.node_id, row.path or "", row.via)
    console.print(table)


@kb_app.command(name="search")
def search_cmd(
    kb_id: str = typer.Argument(..., help="Knowledge base id."),
    query: str = typer.Argument(..., help="Search terms."),
    k: int = typer.Option(10, "--k", help="Number of hits."),
) -> None:
    """BM25 anchor candidates for a query."""
    asyncio.run(_run_search(kb_id, query, k))


@_domain_errors
async def _run_search(kb_id: str, query: str, k: int) -> None:
    hits = await _service().search(kb_id, query, k=k)
    table = Table(title=f"Anchors for {query!r}")
    for col in ("score", "type", "node", "path"):
        table.add_column(col)
    for hit in hits:
        table.add_row(f"{hit.score:.2f}", hit.type, hit.node_id, hit.path or "")
    console.print(table)


@kb_app.command(name="delete")
def delete_cmd(kb_id: str = typer.Argument(..., help="Knowledge base id.")) -> None:
    """Delete a knowledge base (record, corpus and graph)."""
    asyncio.run(_run_delete(kb_id))


@_domain_errors
async def _run_delete(kb_id: str) -> None:
    service = _service()
    await service.get(kb_id)  # 404-style error if missing
    await service.delete(kb_id)
    console.print(f"Deleted knowledge base {kb_id}.")


# ------------------------------------------------------------------ printing


def _print_kb(kb: Any) -> None:
    console.print(f"[bold]{kb.name}[/bold]  ({kb.kb_id})  status: {kb.status}")
    if kb.error:
        console.print(f"  error: {kb.error}", style="red", markup=False)
    console.print(
        f"  nodes {kb.stats.nodes} · edges {kb.stats.edges} · files {kb.stats.files} · "
        f"enriched: {'yes (' + str(kb.provider_used) + ')' if kb.llm_enriched else 'no'}"
    )
    if kb.stats.by_type:
        console.print("  by type: " + json.dumps(kb.stats.by_type), markup=False)
    catalog = kb.catalog
    for label, ids in (
        ("epics", catalog.epics),
        ("stories", catalog.stories),
        ("test cases", catalog.test_cases),
        ("requirements", catalog.requirements),
    ):
        if ids:
            console.print(f"  {label}: {', '.join(ids)}", markup=False)
    for warning in kb.warnings:
        console.print(f"  ! {warning}", style="yellow", markup=False)

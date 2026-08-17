"""CLI smoke: ``kb init`` (folder + zip) → ``kb list/show/ask/impact/search/delete``."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner, Result

from workflow_compiler.cli import kb as kb_cli
from workflow_compiler.cli.main import app
from workflow_compiler.config import get_settings
from workflow_compiler.kg.ingest import zip_folder

from .test_kg_service import build_corpus

runner = CliRunner()


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "state"
    monkeypatch.setattr(get_settings(), "state_store_path", str(root))
    # A wide console so rich tables do not truncate the ids we assert on.
    monkeypatch.setattr(kb_cli, "console", Console(width=300))
    return root


def _ok(result: Result) -> str:
    assert result.exit_code == 0, result.output
    return result.output


def test_kb_cli_round_trip(tmp_path: Path, state_root: Path) -> None:
    corpus = build_corpus(tmp_path / "kb_mini")
    out = _ok(runner.invoke(app, ["kb", "init", str(corpus), "--no-enrich", "--id", "mini"]))
    assert "Created knowledge base mini" in out
    assert "status: ready" in out
    assert (state_root / "knowledge_bases" / "mini.json").is_file()

    zip_path = tmp_path / "kb_mini.zip"
    zip_path.write_bytes(zip_folder(corpus))
    out = _ok(runner.invoke(app, ["kb", "init", str(zip_path), "--no-enrich", "--id", "minizip"]))
    assert "status: ready" in out

    out = _ok(runner.invoke(app, ["kb", "list"]))
    assert "mini" in out and "minizip" in out

    out = _ok(runner.invoke(app, ["kb", "show", "mini"]))
    assert "US-001" in out

    out = _ok(
        runner.invoke(app, ["kb", "ask", "mini", "how does dispatch compensate provisioning"])
    )
    assert "coverage" in out

    out = _ok(runner.invoke(app, ["kb", "ask", "mini", "validate order", "--json"]))
    assert '"rendered"' in out

    out = _ok(runner.invoke(app, ["kb", "impact", "mini", "mod:src/orders/activities.py"]))
    assert "mod:src/orders/workflow.py" in out

    out = _ok(runner.invoke(app, ["kb", "search", "mini", "release_provisioning"]))
    assert "activities.py" in out or "workflow.py" in out

    _ok(runner.invoke(app, ["kb", "delete", "mini"]))
    result = runner.invoke(app, ["kb", "show", "mini"])
    assert result.exit_code == 1
    assert "No knowledge base" in result.output


def test_kb_cli_enrich_with_mock_provider(tmp_path: Path, state_root: Path) -> None:
    corpus = build_corpus(tmp_path / "kb_mini")
    out = _ok(
        runner.invoke(
            app, ["kb", "init", str(corpus), "--enrich", "--provider", "mock", "--id", "rich"]
        )
    )
    # the scripted mock answers with prose, so files are skipped but the run completes
    assert "status: ready" in out
    assert "enriched: yes (mock)" in out

"""CLI smoke: ``cr create`` → ``cr draft --auto`` (mock provider) → approve → export."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner, Result

from workflow_compiler.cli import cr as cr_cli
from workflow_compiler.cli import kb as kb_cli
from workflow_compiler.cli.main import app
from workflow_compiler.config import get_settings

from .test_change_wizard import BCR_TEXT
from .test_kg_service import build_corpus

runner = CliRunner()


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "state"
    monkeypatch.setattr(get_settings(), "state_store_path", str(root))
    monkeypatch.setattr(kb_cli, "console", Console(width=300))
    monkeypatch.setattr(cr_cli, "console", Console(width=300))
    return root


def _ok(result: Result) -> str:
    assert result.exit_code == 0, result.output
    return result.output


def test_cr_cli_round_trip(tmp_path: Path, state_root: Path) -> None:
    corpus = build_corpus(tmp_path / "kb_mini")
    _ok(runner.invoke(app, ["kb", "init", str(corpus), "--no-enrich", "--id", "mini"]))
    bcr = tmp_path / "BCR-001-partial-shipment.md"
    bcr.write_text(BCR_TEXT, encoding="utf-8")

    out = _ok(runner.invoke(app, ["cr", "create", "mini", str(bcr), "--provider", "mock"]))
    assert "Created change request" in out and "BCR-001" in out
    cr_id = next(line for line in out.splitlines() if "id:" in line).split("id:")[1].split()[0]
    assert (state_root / "change_requests" / f"{cr_id}.json").is_file()

    out = _ok(runner.invoke(app, ["cr", "list"]))
    assert cr_id[:8] in out and "impact" in out

    target = tmp_path / "impact.md"
    out = _ok(runner.invoke(app, ["cr", "draft", cr_id, "impact", "--auto", "--out", str(target)]))
    assert "Started wizard" in out and "Drafted Impact analysis v1" in out
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# Impact Analysis — BCR-001") and "## Sources" in text

    out = _ok(runner.invoke(app, ["cr", "approve", cr_id, "impact"]))
    assert "next step: epic" in out
    out = _ok(runner.invoke(app, ["cr", "show", cr_id]))
    assert "approved" in out and "EPIC-001" in out

    out = _ok(runner.invoke(app, ["cr", "export", cr_id, "impact", "--version", "1"]))
    assert "# Impact Analysis" in out
    assert runner.invoke(app, ["cr", "export", cr_id, "impact", "--version", "9"]).exit_code == 1

    # Word / Excel / zip exports (deterministic; the impact analysis is approved here).
    docx_target = tmp_path / "impact.docx"
    out = _ok(
        runner.invoke(
            app, ["cr", "export", cr_id, "impact", "--format", "docx", "--out", str(docx_target)]
        )
    )
    assert "Wrote" in out and docx_target.stat().st_size > 0
    from docx import Document

    paragraphs = [p.text for p in Document(str(docx_target)).paragraphs]
    assert paragraphs[0] == "Impact Analysis" and any(
        p.startswith("Export: Approved v1") for p in paragraphs
    )
    _ok(
        runner.invoke(
            app, ["cr", "export", cr_id, "impact", "--format", "xlsx", "--out", str(tmp_path)]
        )
    )
    assert (tmp_path / "TC-preview-BCR-001.xlsx").is_file()
    _ok(
        runner.invoke(
            app, ["cr", "export", cr_id, "--format", "zip", "--out", str(tmp_path / "cr.zip")]
        )
    )
    import zipfile

    with zipfile.ZipFile(tmp_path / "cr.zip") as zf:
        names = zf.namelist()
    assert "Impact-Analysis-BCR-001.docx" in names and "MANIFEST.txt" in names
    assert (
        runner.invoke(app, ["cr", "export", cr_id, "--format", "docx"]).exit_code != 0
    )  # step required
    assert (
        runner.invoke(app, ["cr", "export", cr_id, "epic", "--format", "docx"]).exit_code == 1
    )  # empty

    _ok(runner.invoke(app, ["cr", "delete", cr_id]))
    assert "No change requests yet" in _ok(runner.invoke(app, ["cr", "list"]))

"""Export the change outputs as a zip (deterministic, no model calls).

Layout follows the corpus README (``src/`` for the code package, ``tests/``,
``docs/diagrams/``, ``docs/test-cases/``) rather than the checkout's
``existing_Codebase/`` folder, so the bundle imports as the code expects
(``from src.shared.types …``) and the generated tests run as-is. ``CHANGES.md``
indexes everything; ``changes.patch`` is the combined unified diff.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass

from workflow_compiler.change_outputs.models import ChangeOutputs, DiagramKind, FileStatus
from workflow_compiler.change_outputs.tests_doc import (
    addendum_filename,
    export_addendum_docx,
    export_matrix_xlsx,
)
from workflow_compiler.docs_export.artifacts import safe_filename_part

_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class ExportEntry:
    """One zip member."""

    path: str
    data: bytes


def zip_code_path(path: str, *, code_root: str, import_root: str) -> str:
    """Corpus path → zip path (``existing_Codebase/x`` → ``src/x``; tests as-is)."""
    normalised = path.replace("\\", "/").lstrip("/")
    if code_root and normalised.startswith(code_root.rstrip("/") + "/"):
        rest = normalised[len(code_root.rstrip("/")) + 1:]
        return f"{import_root or 'src'}/{rest}"
    return normalised


def diagram_zip_path(name: str, kind: DiagramKind) -> str:
    return f"docs/diagrams/mermaid/{name}"


def changes_index(outputs: ChangeOutputs, *, project_id: str, label: str = "") -> str:
    """``CHANGES.md`` — what is in the bundle, with checks and provenance."""
    lines: list[str] = [
        f"# Change outputs — {label or project_id}",
        "",
        f"Generated {outputs.generated_at.isoformat(timespec='seconds')} "
        f"for project `{project_id}`.",
        "",
        "## Stages",
        "",
        "| Stage | Status | Seconds | Provider |",
        "|---|---|---|---|",
    ]
    for name, record in outputs.stages.items():
        seconds = f"{record.seconds:.0f}" if record.seconds is not None else "—"
        prov = f"{record.provider} {record.model}".strip() or "—"
        status = record.status + (f" — {record.error}" if record.error else "")
        lines.append(f"| {name} | {status} | {seconds} | {prov} |")
    lines += ["", "## Diagrams (`docs/diagrams/`)", ""]
    if outputs.diagrams:
        lines += ["| File | Kind | Original | Checks | Notes |", "|---|---|---|---|---|"]
        for d in outputs.diagrams:
            original = d.source_path or ("—" if d.original is None else "yes")
            checks = "; ".join(d.checks) or "ok"
            lines.append(
                f"| {d.name} | {d.kind.value} | {original} | {checks} | "
                f"{d.notes.replace('|', '¦').replace(chr(10), ' ')} |"
            )
        if outputs.system_flow_md:
            lines.append("")
            lines.append("`docs/diagrams/system-flow-diagram.md` embeds every diagram above.")
    else:
        lines.append("_Not generated._")
    code = outputs.code
    lines += ["", "## Code (`src/`, `tests/`)", ""]
    if code.files:
        lines += [
            "| Corpus path | Bundle path | Status | ast | ruff | Reason |",
            "|---|---|---|---|---|---|",
        ]
        for f in code.files:
            zpath = zip_code_path(f.path, code_root=code.code_root, import_root=code.import_root)
            ast_ok = "ok" if f.checks.ast_ok else f"FAIL: {f.checks.ast_error}"
            ruff = {True: "ok", False: "findings", None: "—"}[f.checks.ruff_ok]
            extra = " (repaired)" if f.checks.repaired else ""
            lines.append(
                f"| {f.path} | {zpath if f.status is not FileStatus.REMOVED else '(removed)'} | "
                f"{f.status.value}{extra} | {ast_ok} | {ruff} | {f.reason.replace('|', '¦')} |"
            )
        lines.append("")
        lines.append(
            f"Rewrite order: {' → '.join(code.order) or '—'}. Combined diff: `changes.patch`."
        )
    else:
        lines.append("_Not generated._")
    tests = outputs.tests_doc
    lines += ["", "## Test documents (`docs/test-cases/`)", ""]
    if tests.test_cases:
        lines.append(
            f"- Matrix rows: {len(tests.test_cases)} (source `{tests.matrix_source or '—'}`)"
        )
        lines.append(f"- New: {', '.join(tests.new_ids) or '—'}")
        lines.append(f"- Updated: {', '.join(tests.changed_ids) or '—'}")
        lines.append(f"- Test-plan addendum: `{addendum_filename(tests)}` (+ markdown)")
    else:
        lines.append("_Not generated._")
    lines += ["", "## Sources (knowledge base)", ""]
    lines += [f"- `{s}`" for s in outputs.provenance] or ["- —"]
    if outputs.warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in outputs.warnings]
    return "\n".join(lines) + "\n"


def combined_patch(outputs: ChangeOutputs) -> str:
    return "".join(f.unified_diff for f in outputs.code.files if f.unified_diff)


def export_entries(
    outputs: ChangeOutputs, *, project_id: str, label: str = ""
) -> list[ExportEntry]:
    """Every member of the export zip, in a stable order."""
    entries: list[ExportEntry] = []
    code = outputs.code
    for f in code.files:
        if f.status is FileStatus.REMOVED:
            continue
        zpath = zip_code_path(f.path, code_root=code.code_root, import_root=code.import_root)
        entries.append(ExportEntry(zpath, f.updated.encode("utf-8")))
    for d in outputs.diagrams:
        if d.updated.strip():
            entries.append(ExportEntry(diagram_zip_path(d.name, d.kind), d.updated.encode("utf-8")))
    if outputs.system_flow_md:
        entries.append(
            ExportEntry(
                "docs/diagrams/system-flow-diagram.md", outputs.system_flow_md.encode("utf-8")
            )
        )
    tests = outputs.tests_doc
    if tests.test_cases:
        matrix_name = tests.matrix_source.rsplit("/", 1)[-1] if tests.matrix_source else ""
        if not matrix_name.lower().endswith(".xlsx"):
            matrix_name = "TC-matrix.xlsx"
        entries.append(
            ExportEntry(f"docs/test-cases/{matrix_name}", export_matrix_xlsx(tests, label=label))
        )
        entries.append(
            ExportEntry(
                f"docs/test-cases/{addendum_filename(tests)}",
                export_addendum_docx(tests, label=label),
            )
        )
        entries.append(
            ExportEntry(
                f"docs/test-cases/{addendum_filename(tests)[:-5]}.md",
                tests.test_plan_addendum_md.encode("utf-8"),
            )
        )
    patch = combined_patch(outputs)
    if patch:
        entries.append(ExportEntry("changes.patch", patch.encode("utf-8")))
    entries.append(
        ExportEntry(
            "CHANGES.md",
            changes_index(outputs, project_id=project_id, label=label).encode("utf-8"),
        )
    )
    return entries


def export_zip(outputs: ChangeOutputs, *, project_id: str, label: str = "") -> bytes:
    """The export bundle as zip bytes (byte-stable for identical outputs)."""
    return zip_entries(export_entries(outputs, project_id=project_id, label=label))


def zip_entries(entries: Sequence[ExportEntry]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            info = zipfile.ZipInfo(entry.path, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, entry.data)
    return buffer.getvalue()


def export_filename(project_id: str, label: str = "") -> str:
    tag = safe_filename_part(label or "change", fallback="change")
    return f"{tag}-{safe_filename_part(project_id[:8], fallback='project')}-change-outputs.zip"

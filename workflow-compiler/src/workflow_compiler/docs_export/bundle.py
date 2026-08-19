"""``export_change_request(cr) -> zip``: every artifact of a change request as
Word/Excel plus the markdown sources and a manifest.

Layout of the zip::

    Impact-Analysis-BCR-001.docx
    EPIC-002-<slug>.docx
    US-008-<slug>.docx … (one per story)
    TDD-ORD-002-<slug>.docx
    TC-preview-BCR-001.xlsx            (affected test cases, from the impact analysis)
    markdown/BCR-001-impact-analysis.md
    markdown/EPIC-002.md
    markdown/EPIC-002-user-stories.md
    markdown/TDD-ORD-002.md
    MANIFEST.txt

Artifacts that were never drafted are skipped and listed as such in the
manifest; unapproved ones carry the ``-DRAFT`` suffix and label.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass

from workflow_compiler.models.change import (
    WIZARD_ORDER,
    ArtifactKind,
    ChangeRequest,
)

from .artifacts import (
    ArtifactExport,
    export_artifact,
    export_label,
    safe_filename_part,
    zip_bytes,
)
from .xlsx_writer import TestCaseRow


@dataclass(frozen=True)
class BundleEntry:
    name: str
    size: int
    kind: str  # docx | xlsx | md | manifest


def bundle_entries(
    cr: ChangeRequest, *, existing_test_cases: Sequence[TestCaseRow] = ()
) -> tuple[list[ArtifactExport], list[str]]:
    """The files of the bundle (without the manifest) and the manifest's notes."""
    files: list[ArtifactExport] = []
    notes: list[str] = []
    for kind in WIZARD_ORDER:
        artifact = cr.artifacts.get(kind)
        if not artifact.markdown:
            notes.append(f"{kind.value}: not drafted — skipped")
            continue
        label = export_label(artifact)
        docx = export_artifact(cr, kind, "docx", existing_test_cases=existing_test_cases)
        if kind == ArtifactKind.STORIES:
            # Unpack the per-story zip so the bundle holds US-00N-<slug>.docx directly.
            with zipfile.ZipFile(io.BytesIO(docx.data)) as zf:
                for info in zf.infolist():
                    files.append(ArtifactExport(info.filename, "", zf.read(info)))
                    notes.append(f"{info.filename}: {kind.value} — {label}")
        else:
            files.append(docx)
            notes.append(f"{docx.filename}: {kind.value} — {label}")
        if kind == ArtifactKind.IMPACT:
            xlsx = export_artifact(cr, kind, "xlsx", existing_test_cases=existing_test_cases)
            files.append(xlsx)
            notes.append(f"{xlsx.filename}: affected test cases preview — {label}")
        md = export_artifact(cr, kind, "md")
        files.append(ArtifactExport(f"markdown/{md.filename}", md.media_type, md.data))
        notes.append(f"markdown/{md.filename}: {kind.value} source — {label}")
    return files, notes


def manifest_lines(cr: ChangeRequest, notes: Sequence[str]) -> list[str]:
    lines = [
        f"Change request: {cr.title}",
        f"CR id: {cr.cr_id}",
        f"BCR: {cr.bcr_meta.doc_id or '-'}   Knowledge base: {cr.kb_name or cr.kb_id}",
        f"Assigned ids: {cr.ids.epic_id or '-'} / {cr.ids.tdd_id or '-'} / "
        f"stories {', '.join(cr.ids.story_ids) or '-'}",
        f"Stage: {cr.stage.value}",
        "",
        "Files:",
        *[f"  - {note}" for note in notes],
        "",
        "Markdown is the source of truth; the Word/Excel files are deterministic renders",
        "of the listed versions (DRAFT = the artifact was not approved when exported).",
    ]
    return lines


def export_change_request(
    cr: ChangeRequest, *, existing_test_cases: Sequence[TestCaseRow] = ()
) -> bytes:
    """The whole change request as one zip (see module docstring)."""
    files, notes = bundle_entries(cr, existing_test_cases=existing_test_cases)
    manifest = "\n".join(manifest_lines(cr, notes)) + "\n"
    files.append(ArtifactExport("MANIFEST.txt", "text/plain", manifest.encode("utf-8")))
    return zip_bytes(files)


def bundle_filename(cr: ChangeRequest) -> str:
    tag = safe_filename_part(cr.bcr_meta.doc_id or "change-request", fallback="change-request")
    return f"{tag}-{safe_filename_part(cr.cr_id[:8], fallback='cr')}-export.zip"

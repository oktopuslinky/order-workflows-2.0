"""Artifact → ``.docx`` / ``.xlsx`` / ``.md`` exporters (deterministic).

Each exporter consumes the *parsed* document (:mod:`workflow_compiler.change.parse`)
and lays it out like the reference document of the same kind (digest §5):

* **Impact analysis** — BCR-style: title "Impact Analysis", subtitle
  ``<CR id> — <title>``, numbered Heading 1 sections, the KG appendix and Sources
  as trailing Heading 1 annexes.
* **EPIC** — title ``EPIC-002``, subtitle = epic title, unnumbered Heading 1s.
* **User story** — one document per story: title ``US-00N: Title``, metadata,
  Heading 2 only (Story / Acceptance Criteria / Notes), ``☐`` acceptance lines.
* **TDD** — title "Technical Design Document (TDD)", subtitle = the TDD title,
  ``N. Title`` Heading 1s with ``4.x`` Heading 2s; *Existing* / *Proposed* as
  Heading 3 under each.

Every export states what it is: an ``Export:`` metadata line reads
``Approved vN`` or ``DRAFT vN — not approved`` (drafts also carry it in the
subtitle and a ``-DRAFT`` filename suffix). Markdown stays the source of truth;
free-text bodies go through :func:`render_markdown`.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass

from workflow_compiler.change.parse import (
    parse_epic,
    parse_impact,
    parse_stories,
    parse_tdd,
)
from workflow_compiler.change.render import KG_APPENDIX_HEADING, SOURCES_HEADING
from workflow_compiler.models.change import (
    Artifact,
    ArtifactKind,
    ArtifactStatus,
    ChangeRequest,
    EpicDoc,
    ImpactDoc,
    SourceRef,
    StoriesDoc,
    StoryDoc,
    TddDoc,
)

from .docx_writer import DocxWriter, Span, parse_inline
from .markdown_to_docx import render_markdown
from .xlsx_writer import TestCaseRow, TestCaseSummary, write_test_case_matrix

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP_MEDIA = "application/zip"
MD_MEDIA = "text/markdown; charset=utf-8"

IMPACT_TITLE = "Impact Analysis"
TDD_TITLE = "Technical Design Document (TDD)"
STORIES_TITLE = "User Stories"
DRAFT_SUFFIX = "-DRAFT"
_TC_ID = re.compile(r"\bTC-\d+\b")


@dataclass(frozen=True)
class ArtifactExport:
    """One downloadable file."""

    filename: str
    media_type: str
    data: bytes


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def slugify(text: str, *, max_len: int = 40) -> str:
    """Kebab-case ASCII slug (``Partial Shipment Support`` → ``partial-shipment-support``)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0] or slug[:max_len]
    return slug or "untitled"


def export_label(artifact: Artifact) -> str:
    """``Approved vN`` | ``DRAFT vN — not approved`` (what the export is)."""
    if artifact.status == ArtifactStatus.APPROVED:
        when = f" ({artifact.approved_at:%Y-%m-%d})" if artifact.approved_at else ""
        return f"Approved v{artifact.version}{when}"
    return f"DRAFT v{artifact.version} — not approved"


def is_approved(artifact: Artifact) -> bool:
    return artifact.status == ArtifactStatus.APPROVED


def _suffix(approved: bool) -> str:
    return "" if approved else DRAFT_SUFFIX


def _subtitle(text: str, approved: bool, label: str) -> str:
    return text if approved else f"{text} — {label}" if text else label


def _write_sources(writer: DocxWriter, sources: Sequence[SourceRef]) -> None:
    writer.heading(SOURCES_HEADING, 1)
    if not sources:
        writer.paragraph("No knowledge-base sources were retrieved for this artifact.", italic=True)
        return
    writer.sources((src.path, ", ".join(f"lines {a}-{b}" for a, b in src.spans)) for src in sources)


def _bullets(writer: DocxWriter, items: Sequence[str]) -> None:
    if not items:
        writer.paragraph("None.", italic=True)
    for item in items:
        writer.bullet(item)


def _table(writer: DocxWriter, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    if not rows:
        writer.paragraph("None.", italic=True)
        return
    writer.table(columns, rows)


# --------------------------------------------------------------------------- #
# Impact analysis
# --------------------------------------------------------------------------- #


def export_impact(doc: ImpactDoc, *, label: str = "", approved: bool = True) -> bytes:
    writer = DocxWriter()
    writer.title(IMPACT_TITLE)
    writer.subtitle(_subtitle(" — ".join(p for p in (doc.cr_id, doc.title) if p), approved, label))
    writer.rule()
    for key, value in (
        ("Change Request", doc.cr_id),
        ("Target Workflow", doc.target_workflow),
        ("Knowledge Base", doc.kb_name),
        ("Status", doc.status),
        ("Export", label),
    ):
        if value:
            writer.meta(key, value)
    writer.rule()
    if doc.coverage_note:
        writer.note(doc.coverage_note)
    writer.heading("1. Change Summary", 1)
    render_markdown(writer, doc.summary, heading_offset=1)
    writer.heading("2. Requirements Assessment", 1)
    _table(
        writer,
        ("Req ID", "Requirement", "Impact"),
        [(r.req_id, r.requirement, r.impact) for r in doc.requirements],
    )
    writer.heading("3. Affected Components", 1)
    _table(
        writer,
        ("Kind", "Component", "Change", "Rationale", "KG reference"),
        [(a.kind, a.ref, a.change_type, a.rationale, a.kg_ref) for a in doc.affected],
    )
    writer.heading("4. Impact on Existing Design", 1)
    _bullets(writer, doc.design_impacts)
    writer.heading("5. Risks & Assumptions", 1)
    _bullets(writer, doc.risks)
    writer.heading("6. Open Decisions", 1)
    if not doc.open_decisions:
        writer.paragraph("None.", italic=True)
    for item in doc.open_decisions:
        writer.checklist_item(item, False)
    writer.heading(KG_APPENDIX_HEADING, 1)
    _table(
        writer,
        ("Hops", "Type", "Node", "Path", "Via"),
        [(str(r.hops), r.type, r.name, r.path or "", r.via) for r in doc.kg_rows],
    )
    _write_sources(writer, doc.sources)
    return writer.bytes()


def impact_filename(doc: ImpactDoc, *, approved: bool = True, ext: str = "docx") -> str:
    return f"Impact-Analysis-{doc.cr_id or 'CR'}{_suffix(approved)}.{ext}"


# --------------------------------------------------------------------------- #
# EPIC
# --------------------------------------------------------------------------- #


def export_epic(doc: EpicDoc, *, label: str = "", approved: bool = True) -> bytes:
    writer = DocxWriter()
    writer.title(doc.id or "EPIC")
    writer.subtitle(_subtitle(doc.title, approved, label))
    writer.rule()
    for key, value in (
        ("Epic Owner", doc.owner),
        ("Linked BRD", doc.linked_brd),
        ("Linked BCR", doc.linked_bcr),
        ("Status", doc.status),
        ("Target Release", doc.target_release),
        ("Export", label),
    ):
        if value:
            writer.meta(key, value)
    writer.rule()
    if doc.coverage_note:
        writer.note(doc.coverage_note)
    writer.heading("Epic Statement", 1)
    statement = doc.statement.strip()
    if statement and "\n" not in statement and not statement.startswith(("-", "|", "```")):
        writer.callout(statement)
    else:
        render_markdown(writer, doc.statement, heading_offset=1)
    writer.heading("Business Value", 1)
    _bullets(writer, doc.value)
    writer.heading("In-Scope Capabilities", 1)
    _bullets(writer, doc.capabilities)
    writer.heading("Definition of Done", 1)
    if not doc.dod:
        writer.paragraph("None.", italic=True)
    for i, item in enumerate(doc.dod):
        writer.checklist_item(item, bool(doc.dod_done[i]) if i < len(doc.dod_done) else False)
    writer.heading("Story Map", 1)
    _table(
        writer,
        ("Story ID", "Title", "Status", "Doc"),
        [(s.id, s.title, s.status, s.doc) for s in doc.story_map],
    )
    writer.heading("Non-Functional Requirements", 1)
    _table(writer, ("NFR", "Target"), [(n.nfr, n.target) for n in doc.nfrs])
    writer.heading("Dependencies", 1)
    _bullets(writer, doc.dependencies)
    writer.heading("Risks", 1)
    _table(writer, ("Risk", "Mitigation"), [(r.risk, r.mitigation) for r in doc.risks])
    _write_sources(writer, doc.sources)
    return writer.bytes()


def epic_filename(doc: EpicDoc, *, approved: bool = True, ext: str = "docx") -> str:
    return f"{doc.id or 'EPIC'}-{slugify(doc.title)}{_suffix(approved)}.{ext}"


# --------------------------------------------------------------------------- #
# User stories
# --------------------------------------------------------------------------- #

_STORY_PREFIXES = ("As ", "I want to ", "I want ", "So that ", "so that ")


def _story_line(text: str) -> list[Span]:
    """``As a fulfilment operator,`` → plain prefix + bold subject + plain punctuation."""
    for prefix in _STORY_PREFIXES:
        if text.startswith(prefix):
            rest = text[len(prefix) :]
            tail = ""
            while rest and rest[-1] in ",.;":
                tail = rest[-1] + tail
                rest = rest[:-1]
            spans = [Span(prefix), *parse_inline(rest, bold=True)]
            if tail:
                spans.append(Span(tail))
            return spans
    return parse_inline(text)


def export_story(
    story: StoryDoc,
    *,
    epic_title: str = "",
    label: str = "",
    approved: bool = True,
    sources: Sequence[SourceRef] = (),
) -> bytes:
    writer = DocxWriter()
    writer.title(f"{story.id}: {story.title}" if story.id else story.title)
    if not approved:
        writer.subtitle(label)
    writer.rule()
    epic = story.epic or epic_title
    for key, value in (
        ("Epic", epic),
        ("Status", story.status),
        ("Story Points", str(story.points) if story.points else ""),
        ("Implements", ", ".join(story.implements)),
        ("Export", label),
    ):
        if value:
            writer.meta(key, value)
    writer.rule()
    writer.heading("Story", 2)
    for line in (story.as_a, story.i_want, story.so_that):
        if line:
            writer.paragraph(line, spans=_story_line(line))
    writer.heading("Acceptance Criteria", 2)
    if not story.acceptance:
        writer.paragraph("None.", italic=True)
    for item in story.acceptance:
        writer.checklist_item(item, False)
    writer.heading("Notes", 2)
    render_markdown(writer, story.notes, heading_offset=2)
    if sources:
        writer.heading(SOURCES_HEADING, 2)
        writer.sources(
            (src.path, ", ".join(f"lines {a}-{b}" for a, b in src.spans)) for src in sources
        )
    return writer.bytes()


def story_filename(story: StoryDoc, *, approved: bool = True, ext: str = "docx") -> str:
    return f"{story.id or 'US'}-{slugify(story.title)}{_suffix(approved)}.{ext}"


def export_stories(
    doc: StoriesDoc, *, label: str = "", approved: bool = True
) -> list[ArtifactExport]:
    """One ``US-00N-<slug>.docx`` per story (the reference keeps one file per story)."""
    epic = " — ".join(p for p in (doc.epic_id, doc.epic_title) if p)
    return [
        ArtifactExport(
            filename=story_filename(story, approved=approved),
            media_type=DOCX_MEDIA,
            data=export_story(
                story, epic_title=epic, label=label, approved=approved, sources=doc.sources
            ),
        )
        for story in doc.stories
    ]


def stories_zip_filename(doc: StoriesDoc, *, approved: bool = True) -> str:
    return f"{doc.epic_id or 'EPIC'}-user-stories{_suffix(approved)}.zip"


# --------------------------------------------------------------------------- #
# TDD
# --------------------------------------------------------------------------- #


def export_tdd(doc: TddDoc, *, label: str = "", approved: bool = True) -> bytes:
    writer = DocxWriter()
    writer.title(TDD_TITLE)
    writer.subtitle(_subtitle(doc.title, approved, label))
    writer.rule()
    for key, value in (
        ("Document ID", doc.id),
        ("Linked EPIC", doc.linked_epic),
        ("Supersedes", doc.supersedes),
        ("Version", doc.version),
        ("Status", doc.status),
        ("Author", doc.author),
        ("Export", label),
    ):
        if value:
            writer.meta(key, value)
    writer.rule()
    if doc.coverage_note:
        writer.note(doc.coverage_note)
    container_open = False
    for section in doc.sections:
        is_sub = "." in section.number
        if is_sub and not container_open:
            writer.heading("4. Workflow Design", 1)
            container_open = True
        if is_sub:
            writer.heading(f"{section.number} {section.title}", 2)
        else:
            writer.heading(f"{section.number}. {section.title}", 1)
        writer.heading("Existing", 3)
        render_markdown(writer, section.existing or "_To be determined._", heading_offset=3)
        writer.heading("Proposed", 3)
        render_markdown(writer, section.proposed or "_To be determined._", heading_offset=3)
    if doc.diagrams_needed:
        writer.heading("Diagrams Needed", 1)
        _bullets(writer, doc.diagrams_needed)
    _write_sources(writer, doc.sources)
    return writer.bytes()


def tdd_filename(doc: TddDoc, *, approved: bool = True, ext: str = "docx") -> str:
    return f"{doc.id or 'TDD'}-{slugify(doc.title)}{_suffix(approved)}.{ext}"


# --------------------------------------------------------------------------- #
# Test-case preview (xlsx)
# --------------------------------------------------------------------------- #


def preview_test_case_rows(
    doc: ImpactDoc, existing: Sequence[TestCaseRow] = ()
) -> list[TestCaseRow]:
    """The affected test cases as matrix rows.

    Existing rows from the knowledge base (when supplied) provide Title /
    Preconditions / Steps / Expected / Type / Automated; the impact analysis
    supplies the change note and the linked requirements. Without existing rows
    the Title is the impact rationale and the detail columns stay empty.
    """
    by_id = {row.tc_id.strip().upper(): row for row in existing}
    linked: dict[str, list[str]] = {}
    for req in doc.requirements:
        for tc_id in _TC_ID.findall(req.impact):
            linked.setdefault(tc_id.upper(), []).append(req.req_id)
    rows: list[TestCaseRow] = []
    seen: set[str] = set()
    for item in doc.affected:
        ids = (
            _TC_ID.findall(item.ref)
            if "test" in item.kind.lower() or _TC_ID.search(item.ref)
            else []
        )
        for tc_id in ids:
            key = tc_id.upper()
            if key in seen:
                continue
            seen.add(key)
            base = by_id.get(key)
            note = f"{item.change_type}: {item.rationale}".strip(": ")
            if item.kg_ref:
                note += f" [{item.kg_ref}]"
            if base is not None:
                rows.append(
                    base.model_copy(
                        update={
                            "tc_id": tc_id,
                            "linked": base.linked or ", ".join(linked.get(key, [])),
                            "notes": (base.notes + " | " if base.notes else "") + note,
                        }
                    )
                )
            else:
                rows.append(
                    TestCaseRow(
                        tc_id=tc_id,
                        title=item.rationale,
                        type="",
                        automated="Planned" if item.change_type == "add" else "",
                        linked=", ".join(linked.get(key, [])),
                        notes=note,
                    )
                )
    rows.sort(key=lambda r: (len(r.tc_id), r.tc_id))
    return rows


def export_test_case_preview(
    doc: ImpactDoc,
    *,
    existing: Sequence[TestCaseRow] = (),
    label: str = "",
    linked_tdd: str = "",
    linked_epic: str = "",
) -> bytes:
    rows = preview_test_case_rows(doc, existing)
    merged = sum(1 for r in rows if r.tc_id.upper() in {e.tc_id.upper() for e in existing})
    notes = [
        f"Preview generated from the impact analysis of {doc.cr_id or 'the change request'}"
        + (f" ({label})" if label else "")
        + " — affected test cases only; the updated matrix is produced after the design"
        " is approved.",
    ]
    if existing:
        notes.append(
            f"{merged} row(s) carry the knowledge base's original Title/Preconditions/Steps/"
            "Expected Result; the change note is appended in Notes."
        )
    else:
        notes.append(
            "No original test-case matrix was found in the knowledge base; "
            "Title carries the impact rationale."
        )
    summary = TestCaseSummary(
        title=f"Test Case Matrix — {doc.title or doc.cr_id} (preview)",
        linked_tdd=linked_tdd,
        linked_epic=linked_epic,
        automation="preview — tests are generated after approval",
        notes=notes,
    )
    return write_test_case_matrix(rows, summary)


def test_case_preview_filename(doc: ImpactDoc, *, approved: bool = True) -> str:
    return f"TC-preview-{doc.cr_id or 'CR'}{_suffix(approved)}.xlsx"


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

MARKDOWN_NAMES: dict[ArtifactKind, str] = {
    ArtifactKind.IMPACT: "{cr}-impact-analysis",
    ArtifactKind.EPIC: "{epic}",
    ArtifactKind.STORIES: "{epic}-user-stories",
    ArtifactKind.TDD: "{tdd}",
}


def markdown_filename(cr: ChangeRequest, kind: ArtifactKind, *, approved: bool = True) -> str:
    stem = MARKDOWN_NAMES[kind].format(
        cr=cr.bcr_meta.doc_id or "CR",
        epic=cr.ids.epic_id or "EPIC",
        tdd=cr.ids.tdd_id or "TDD",
    )
    return f"{stem}{_suffix(approved)}.md"


def zip_bytes(entries: Sequence[ArtifactExport]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            info = zipfile.ZipInfo(entry.filename, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, entry.data)
    return buffer.getvalue()


def export_artifact(
    cr: ChangeRequest,
    kind: ArtifactKind | str,
    fmt: str = "docx",
    *,
    existing_test_cases: Sequence[TestCaseRow] = (),
) -> ArtifactExport:
    """Export one artifact of ``cr`` as ``docx`` | ``md`` | ``xlsx``.

    ``docx`` for the stories artifact is a zip of per-story documents; ``xlsx``
    is only defined for the impact analysis (the affected test cases preview).
    Raises :class:`ValueError` for an empty artifact or an unsupported format.
    """
    kind = ArtifactKind(kind)
    artifact = cr.artifacts.get(kind)
    if not artifact.markdown:
        raise ValueError(f"The {kind.value} artifact has not been drafted yet.")
    approved = is_approved(artifact)
    label = export_label(artifact)
    if fmt == "md":
        return ArtifactExport(
            markdown_filename(cr, kind, approved=approved),
            MD_MEDIA,
            artifact.markdown.encode("utf-8"),
        )
    if fmt == "xlsx":
        if kind != ArtifactKind.IMPACT:
            raise ValueError("Only the impact analysis exports a test-case preview (.xlsx).")
        doc = parse_impact(artifact.markdown)
        data = export_test_case_preview(
            doc,
            existing=existing_test_cases,
            label=label,
            linked_tdd=cr.ids.tdd_id,
            linked_epic=cr.ids.epic_id,
        )
        return ArtifactExport(test_case_preview_filename(doc, approved=approved), XLSX_MEDIA, data)
    if fmt != "docx":
        raise ValueError(f"Unsupported export format {fmt!r} (expected docx, md or xlsx).")
    if kind == ArtifactKind.IMPACT:
        idoc = parse_impact(artifact.markdown)
        return ArtifactExport(
            impact_filename(idoc, approved=approved),
            DOCX_MEDIA,
            export_impact(idoc, label=label, approved=approved),
        )
    if kind == ArtifactKind.EPIC:
        edoc = parse_epic(artifact.markdown)
        return ArtifactExport(
            epic_filename(edoc, approved=approved),
            DOCX_MEDIA,
            export_epic(edoc, label=label, approved=approved),
        )
    if kind == ArtifactKind.STORIES:
        sdoc = parse_stories(artifact.markdown)
        files = export_stories(sdoc, label=label, approved=approved)
        return ArtifactExport(
            stories_zip_filename(sdoc, approved=approved), ZIP_MEDIA, zip_bytes(files)
        )
    tdoc = parse_tdd(artifact.markdown)
    return ArtifactExport(
        tdd_filename(tdoc, approved=approved),
        DOCX_MEDIA,
        export_tdd(tdoc, label=label, approved=approved),
    )

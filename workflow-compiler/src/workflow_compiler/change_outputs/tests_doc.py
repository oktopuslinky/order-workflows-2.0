"""Deterministic half of the test-document stage.

The model proposes new test-case rows and updates to existing ones (plus a
structured test-plan addendum); this module numbers the new rows from the
knowledge base's catalog (``TC-18``…), merges updates onto the original matrix
rows without losing anything the model did not mention, renders the addendum
markdown, and produces the Excel matrix / addendum Word document through the
Phase 2 writers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from workflow_compiler.change_outputs.models import (
    TestCaseDraft,
    TestCaseUpdate,
    TestDocUpdate,
    TestPlanAddendumDraft,
)
from workflow_compiler.docs_export.artifacts import safe_filename_part
from workflow_compiler.docs_export.docx_writer import DocxWriter
from workflow_compiler.docs_export.markdown_to_docx import render_markdown
from workflow_compiler.docs_export.xlsx_writer import (
    TC_TYPES,
    TestCaseRow,
    TestCaseSummary,
    write_test_case_matrix,
)

_TC_ID = re.compile(r"\bTC-(\d+)\b")
_DOC_ID = re.compile(r"\b(TP|TDD|EPIC)-[A-Z0-9-]*\d\b")


def next_tc_ids(existing_ids: Iterable[str], count: int, *, start_hint: str = "") -> list[str]:
    """``count`` consecutive ids after the highest existing ``TC-NN`` (or ``start_hint``)."""
    best = 0
    width = 2
    for value in existing_ids:
        match = _TC_ID.search(value or "")
        if match:
            best = max(best, int(match.group(1)))
            width = len(match.group(1))
    if start_hint:
        match = _TC_ID.search(start_hint)
        if match:
            best = max(best, int(match.group(1)) - 1)
            width = max(width, len(match.group(1)))
    return [f"TC-{best + 1 + i:0{width}d}" for i in range(count)]


def normalise_type(value: str) -> str:
    """Snap a type onto the reference vocabulary when it is a case/spacing variant."""
    text = " / ".join(part.strip() for part in re.split(r"\s*/\s*", value.strip()) if part.strip())
    if not text:
        return "Functional"
    for known in TC_TYPES:
        if known.lower() == text.lower():
            return known
    return text


def normalise_automated(value: str) -> str:
    text = value.strip()
    lowered = text.lower()
    if lowered in ("yes", "y", "true", "automated"):
        return "Yes"
    if lowered.startswith("manual"):
        return text if "(" in text else "Manual"
    if lowered in ("planned", "todo", "later"):
        return "Planned"
    return text or "Yes"


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", text.strip())


def merge_test_cases(
    existing: Sequence[TestCaseRow],
    new_cases: Sequence[TestCaseDraft],
    updates: Sequence[TestCaseUpdate],
    *,
    start_hint: str = "",
    change_note: str = "",
) -> tuple[list[TestCaseRow], list[str], list[str]]:
    """Apply updates to the original rows and append the numbered new rows.

    Returns ``(rows, changed_ids, new_ids)``. An update only replaces the fields
    it fills; a filled ``notes`` is *appended* to the original note (the original
    matrix is human-approved — nothing is dropped). New rows get ids from
    :func:`next_tc_ids`; a duplicate new title (case-insensitive) is skipped.
    """
    rows = [row.model_copy() for row in existing]
    by_id = {row.tc_id.strip().upper(): row for row in rows}
    changed: list[str] = []
    for update in updates:
        key = update.tc_id.strip().upper()
        row = by_id.get(key)
        if row is None:
            continue
        touched = False
        for name in ("title", "preconditions", "steps", "expected", "type", "automated", "linked"):
            value = getattr(update, name).strip()
            if not value:
                continue
            if name == "type":
                value = normalise_type(value)
            if name == "automated":
                value = normalise_automated(value)
            if value != getattr(row, name):
                setattr(row, name, value)
                touched = True
        note = _clean(update.notes)
        if note and note.lower() not in row.notes.lower():
            row.notes = (row.notes + " | " if row.notes else "") + note
            touched = True
        if touched and row.tc_id not in changed:
            changed.append(row.tc_id)
    titles = {row.title.strip().lower() for row in rows}
    fresh: list[TestCaseDraft] = []
    for case in new_cases:
        title = case.title.strip()
        if not title or title.lower() in titles:
            continue
        titles.add(title.lower())
        fresh.append(case)
    ids = next_tc_ids((r.tc_id for r in rows), len(fresh), start_hint=start_hint)
    new_ids: list[str] = []
    for tc_id, case in zip(ids, fresh, strict=True):
        note = _clean(case.notes)
        if change_note and change_note.lower() not in note.lower():
            note = (note + " | " if note else "") + change_note
        rows.append(
            TestCaseRow(
                tc_id=tc_id,
                title=case.title.strip(),
                preconditions=_clean(case.preconditions),
                steps=_clean(case.steps),
                expected=_clean(case.expected),
                type=normalise_type(case.type),
                automated=normalise_automated(case.automated),
                linked=case.linked.strip(),
                notes=note,
            )
        )
        new_ids.append(tc_id)
    return rows, changed, new_ids


# --------------------------------------------------------------------------- #
# Test-plan addendum
# --------------------------------------------------------------------------- #

ADDENDUM_TITLE = "Test Plan — Addendum"


def _bullets(items: Sequence[str]) -> list[str]:
    return [f"- {item.strip()}" for item in items if item.strip()]


def render_addendum(
    draft: TestPlanAddendumDraft,
    *,
    test_plan_id: str,
    change_request_id: str,
    change_title: str,
    linked_tdd: str,
    linked_epic: str,
    changed_ids: Sequence[str],
    new_ids: Sequence[str],
    rows: Sequence[TestCaseRow],
    tests_file: str = "tests/test_order_workflow.py",
) -> str:
    """The addendum as markdown (numbered H2s mirroring the test-plan sections)."""
    by_id = {r.tc_id: r for r in rows}
    out: list[str] = [
        f"# {test_plan_id or 'Test Plan'} — Addendum — {change_request_id or 'change'}"
        + (f" — {change_title}" if change_title else ""),
        "",
        f"**Amends:** {test_plan_id or 'the test plan'}",
        "",
        f"**Change Request:** {change_request_id or '—'}",
        "",
        f"**Linked TDD:** {linked_tdd or '—'}",
        "",
        f"**Linked Epic:** {linked_epic or '—'}",
        "",
        "**Status:** Draft — generated after design approval",
        "",
        "## 1. Purpose",
        "",
        f"This addendum extends {test_plan_id or 'the test plan'} with the scenarios "
        f"introduced by {change_request_id or 'the change request'}"
        + (f" ({change_title})" if change_title else "")
        + ". It is applied on top of the original plan; sections not listed here are unchanged.",
        "",
        "## 2. Scope changes",
        "",
        "### 3.2 Out of Scope — removed",
        "",
        *(_bullets(draft.out_of_scope_removed) or ["- _None._"]),
        "",
        "### 3.1 In Scope — added",
        "",
        *(_bullets(draft.in_scope_added) or ["- _None._"]),
        "",
        "## 3. Test strategy changes",
        "",
        "### 4.2 Test Types Covered — added",
        "",
        *(_bullets(draft.test_types_added) or ["- _None._"]),
        "",
        "### 4.4 Test Data — added",
        "",
        *(_bullets(draft.test_data_added) or ["- _None._"]),
        "",
        "## 4. Test cases",
        "",
        "### New test cases",
        "",
    ]
    if new_ids:
        out.append("| TC ID | Title | Type | Automated | Linked Story/Req |")
        out.append("|---|---|---|---|---|")
        for tc_id in new_ids:
            row = by_id.get(tc_id)
            if row is None:
                continue
            out.append(
                f"| {row.tc_id} | {row.title} | {row.type} | {row.automated} | {row.linked} |"
            )
    else:
        out.append("- _None._")
    out += ["", "### Updated test cases", ""]
    if changed_ids:
        out.append("| TC ID | Title | Change |")
        out.append("|---|---|---|")
        for tc_id in changed_ids:
            row = by_id.get(tc_id)
            if row is None:
                continue
            note = row.notes.rsplit(" | ", 1)[-1] if row.notes else ""
            out.append(f"| {row.tc_id} | {row.title} | {note} |")
    else:
        out.append("- _None._")
    out += [
        "",
        "## 5. Deliverables — added",
        "",
        *(
            _bullets(draft.deliverables_added)
            or [f"- Updated `{tests_file}` (generated code stage)."]
        ),
        "",
        "## 6. Exit criteria — added",
        "",
        *(_bullets(draft.exit_criteria_added) or ["- _None._"]),
        "",
        "## 7. Risks to the test effort — added",
        "",
        *(_bullets(draft.risks_added) or ["- _None._"]),
        "",
    ]
    if draft.notes:
        out += ["## 8. Notes", "", *_bullets(draft.notes), ""]
    return "\n".join(out).rstrip("\n") + "\n"


def parse_addendum_meta(markdown: str) -> dict[str, str]:
    """``**Label:** value`` lines of an addendum (round-trip helper for tests)."""
    meta: dict[str, str] = {}
    for match in re.finditer(r"^\*\*([^*]+):\*\*\s*(.*)$", markdown, re.M):
        meta[match.group(1).strip()] = match.group(2).strip()
    return meta


def export_addendum_docx(update: TestDocUpdate, *, label: str = "") -> bytes:
    """The addendum as a Word document in the reference test-plan look."""
    writer = DocxWriter()
    writer.title(ADDENDUM_TITLE)
    subtitle = f"{update.test_plan_id or 'Test Plan'} — {update.change_request_id or 'Change'}"
    writer.subtitle(subtitle + (f" — {label}" if label else ""))
    writer.rule()
    for key, value in (
        ("Amends", update.test_plan_id),
        ("Change Request", update.change_request_id),
        ("Linked TDD", update.linked_tdd),
        ("Linked Epic", update.linked_epic),
        ("Status", "Draft — generated after design approval"),
    ):
        if value:
            writer.meta(key, value)
    writer.rule()
    body = re.sub(r"^# .*\n(?:\n?\*\*[^*]+:\*\* .*\n)*", "", update.test_plan_addendum_md, count=1)
    render_markdown(writer, body, heading_offset=0)
    return writer.bytes()


def export_matrix_xlsx(update: TestDocUpdate, *, label: str = "") -> bytes:
    """The full updated matrix (existing rows + updated notes + new rows)."""
    notes = [
        f"Updated for {update.change_request_id or 'the change request'}"
        + (f" ({label})" if label else "")
        + f": {len(update.new_ids)} new row(s) {', '.join(update.new_ids) or '—'}; "
        + f"{len(update.changed_ids)} updated row(s) {', '.join(update.changed_ids) or '—'}.",
        *update.notes,
    ]
    summary = TestCaseSummary(
        title="Test Case Matrix — Order Lifecycle Workflow"
        if not update.change_request_id
        else f"Test Case Matrix — updated for {update.change_request_id}",
        linked_tdd=update.linked_tdd,
        linked_epic=update.linked_epic,
        automation="tests/test_order_workflow.py",
        notes=notes,
    )
    return write_test_case_matrix(update.test_cases, summary)


def addendum_filename(update: TestDocUpdate) -> str:
    plan = safe_filename_part(update.test_plan_id or "TP", fallback="TP")
    cr = safe_filename_part(update.change_request_id or "change", fallback="change")
    return f"{plan}-addendum-{cr}.docx"


def linked_ids_from_text(text: str) -> dict[str, str]:
    """``{"TP": "TP-ORD-001", "TDD": …, "EPIC": …}`` ids mentioned in ``text``."""
    found: dict[str, str] = {}
    for match in _DOC_ID.finditer(text):
        found.setdefault(match.group(1), match.group(0))
    return found

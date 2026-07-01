"""Render the checklist as an editable markdown 'form' and parse answers back.

The report is the user-facing surface of the gate. It lists what was discovered
(so the author can confirm/correct the workflow and facts) and the checklist
itself, with an ``ANSWER:`` line under each item that still needs input. The
author edits those lines and re-runs ``workflow-compiler checklist``; :func:`parse`
reads the filled-in answers back out.
"""

from __future__ import annotations

import re

from workflow_compiler.models import FactCategory, WorkflowState

#: Matches an item heading, capturing the item id: ``### [ ] R1-trigger (REQUIRED) — MISSING``.
_HEADING = re.compile(r"^###\s+\[.\]\s+(\S+)")
#: Matches an answer line, capturing whatever follows the colon.
_ANSWER = re.compile(r"^ANSWER:(.*)$")


def render(state: WorkflowState) -> str:
    """Render ``state.checklist`` (plus a discovery summary) as a markdown form."""
    checklist = state.checklist
    name = state.workflow_metadata.name if state.workflow_metadata else "(unnamed workflow)"
    lines: list[str] = [
        f"# Workflow readiness checklist: {name}",
        "",
        f"- workflow_id: `{state.workflow_id}`",
        f"- stage: `{state.stage.value}`",
        "",
        "This file is a form. For each item marked **NEEDS INPUT**, write your answer on its",
        "`ANSWER:` line, then re-run:",
        "",
        f"```\nworkflow-compiler checklist {state.workflow_id} --answers <this-file>\n```",
        "",
        "Add `--accept-as-is` to that command to proceed while accepting any remaining gaps.",
        "",
    ]
    lines += _discovery_summary(state)

    if checklist is None:
        lines += ["", "_(No checklist has been computed for this workflow.)_"]
        return "\n".join(lines) + "\n"

    lines += ["", "## Checklist", ""]
    for item in checklist.items:
        cleared = item.is_cleared()
        box = "x" if cleared else " "
        sev = item.severity.value.upper()
        flag = item.status.value.upper() if cleared else "NEEDS INPUT"
        lines.append(f"### [{box}] {item.id} ({sev}) — {flag}")
        lines.append(f"- Requirement: {item.requirement}")
        if item.evidence:
            lines.append(f"- Evidence: {item.evidence}")
        if not cleared and item.question:
            lines.append(f"- Question: {item.question}")
            lines.append(f"ANSWER:{(' ' + item.answer) if item.answer else ''}")
        lines.append("")

    blocking = checklist.unmet_required()
    if blocking:
        ids = ", ".join(i.id for i in blocking)
        lines += [
            "---",
            "",
            f"**{len(blocking)} required item(s) still block generation:** {ids}.",
            "Answer them (or use `--accept-as-is`) and re-run the `checklist` command.",
        ]
    else:
        lines += ["---", "", "**All required items are satisfied — generation may proceed.**"]
    return "\n".join(lines) + "\n"


def parse(text: str) -> dict[str, str]:
    """Read filled-in answers back out of a rendered report.

    Returns a mapping of ``item_id -> answer`` for every item whose ``ANSWER:``
    line was filled in (blank answers are skipped).
    """
    answers: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = _HEADING.match(line.strip())
        if heading:
            current = heading.group(1)
            continue
        match = _ANSWER.match(line.strip())
        if match and current is not None:
            value = match.group(1).strip()
            if value:
                answers[current] = value
            current = None
    return answers


def _discovery_summary(state: WorkflowState) -> list[str]:
    """A compact 'here is what we discovered — confirm or correct' section."""
    lines = ["## Discovered workflow (confirm or correct)", ""]
    meta = state.workflow_metadata
    if meta is not None:
        lines.append(f"- Name: {meta.name}")
        lines.append(f"- Trigger(s): {', '.join(meta.trigger_events) or '—'}")
        lines.append(f"- Actors: {', '.join(meta.actors) or '—'}")
        lines.append(f"- Systems: {', '.join(meta.systems) or '—'}")

    facts = state.workflow_facts
    if facts is not None:
        inputs = [f.statement for f in facts.by_category(FactCategory.INPUT)]
        outputs = [f.statement for f in facts.by_category(FactCategory.OUTPUT)]
        lines.append(f"- Inputs: {', '.join(inputs) or '—'}")
        lines.append(f"- Outputs: {', '.join(outputs) or '—'}")
        structure = facts.structure
        if structure is not None:
            lines.append(f"- Activities: {', '.join(a.name for a in structure.activities) or '—'}")
            if structure.decisions:
                lines.append(
                    "- Decisions: "
                    + "; ".join(f"{d.id}={d.question}" for d in structure.decisions)
                )
            if structure.compensations:
                lines.append(
                    "- Compensations: "
                    + "; ".join(f"{c.name}->{c.compensates}" for c in structure.compensations)
                )
    return lines

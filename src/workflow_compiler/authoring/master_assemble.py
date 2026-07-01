"""Assemble per-workflow ideal sections into one editable master document.

The master document has a preamble (editing instructions), a ``## Notes to the
compiler`` two-way channel, a ``## Workflows detected`` index, then one ideal-format
section per workflow — each trailed by ``### Guidance`` (per-workflow notes to the
compiler), ``### Open questions``, and ``### Readiness gaps`` helper blocks. Only
per-workflow titles use ``# `` (H1) so the document can be split back into clean
per-workflow documents.
"""

from __future__ import annotations

from workflow_compiler.models import WorkflowChecklist, WorkflowSegment

_PREAMBLE = """<!--
MASTER WORKFLOW DOCUMENT — edit me, then re-run.

How to edit:
  * Each `# Heading` below is ONE workflow. Add a workflow you noticed by adding a
    new `# Name` section in the same shape; delete one by removing its section.
  * Fix any facts, steps, inputs, retries, or compensations directly in the prose.
  * Use "## Notes to the compiler" (global) and each "### Guidance" block (per
    workflow) to talk to the compiler: list missing flows, corrections, or priorities.
    These notes GUIDE the compiler on the next `reauthor` and are never compiled into
    code.
  * To make workflow A call workflow B, add a Process line:
    "The workflow invokes `B` as a child workflow."

Two ways to re-run:
  * Refine the document (another review round, reads your notes):
      workflow-compiler reauthor <this-file> --out <this-file>
  * Compile every workflow to a diagram + Temporal code:
      workflow-compiler compile-authored <this-file> --out-dir generated/
-->
"""

_NOTES_PLACEHOLDER = (
    "<!-- Global notes to the compiler. List workflows you saw that are missing, "
    "corrections, or priorities. Read on `reauthor`. -->\n_(no notes yet)_"
)
_GUIDANCE_PLACEHOLDER = (
    "<!-- Notes to the compiler about THIS workflow. Read on `reauthor`. -->\n_(none)_"
)


def _notes_section(global_notes: str | None) -> str:
    body = (global_notes or "").strip() or _NOTES_PLACEHOLDER
    return f"## Notes to the compiler\n\n{body}"


def _index(segments: list[WorkflowSegment], clarifications: list[str]) -> str:
    lines = ["## Workflows detected", ""]
    for seg in segments:
        summary = f" — {seg.summary}" if seg.summary else ""
        lines.append(f"- **{seg.name}**{summary}")
        if seg.invokes:
            lines.append(f"  - invokes: {', '.join(seg.invokes)}")
    if clarifications:
        lines += ["", "### Document-level open questions", ""]
        lines += [f"- {q}" for q in clarifications]
    return "\n".join(lines)


def _readiness_gaps(checklist: WorkflowChecklist | None) -> str:
    if checklist is None:
        return "_(readiness not evaluated)_"
    unmet = [item for item in checklist.items if not item.is_cleared()]
    if not unmet:
        return "_All readiness checks satisfied._"
    lines: list[str] = []
    for item in unmet:
        prompt = item.question or item.requirement
        lines.append(f"- **{item.id}** ({item.severity.value}): {prompt}")
    return "\n".join(lines)


def assemble_master(
    *,
    segments: list[WorkflowSegment],
    sections: dict[str, str],
    checklists: dict[str, WorkflowChecklist | None],
    clarifications: list[str],
    global_notes: str | None = None,
    guidance: dict[str, str] | None = None,
    open_questions: dict[str, list[str]] | None = None,
) -> str:
    """Build the master document from per-workflow ideal sections.

    ``sections`` and ``checklists`` are keyed by ``WorkflowSegment.id``. ``global_notes``
    is preserved verbatim in the ``## Notes to the compiler`` channel; ``guidance`` and
    ``open_questions`` (also keyed by id) let a re-author round carry the user's
    per-workflow notes and edited questions forward. Segments without a rendered
    section are skipped.
    """
    guidance = guidance or {}
    open_questions = open_questions or {}
    parts: list[str] = [
        _PREAMBLE,
        "",
        _notes_section(global_notes),
        "",
        _index(segments, clarifications),
        "",
    ]
    for seg in segments:
        section = sections.get(seg.id)
        if section is None:
            continue
        parts.append(section.rstrip())
        parts.append("")
        parts.append("### Guidance")
        parts.append("")
        parts.append((guidance.get(seg.id) or "").strip() or _GUIDANCE_PLACEHOLDER)
        parts.append("")
        parts.append("### Open questions")
        parts.append("")
        questions = open_questions.get(seg.id, seg.questions)
        parts.append("\n".join(f"- {q}" for q in questions) if questions else "_(none)_")
        parts.append("")
        parts.append("### Readiness gaps")
        parts.append("")
        parts.append(_readiness_gaps(checklists.get(seg.id)))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"

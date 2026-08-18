"""Deterministic ChangeSpec → ``changes.md`` projection (the review surface).

The change spec is the second editable file of a knowledge-graph-grounded
project. Like the workflow spec files it follows a strict line grammar so
``spec/change_ingest.py`` can parse it back without a model; the structured
:class:`~workflow_compiler.models.change_spec.ChangeSpec` stays the source of
truth and every field this file renders is a field the parser reads back.

Line grammar (what the parser relies on):

* ``# Change Spec`` — fixed H1.
* ``## Grounding`` — read-only ``- key: value`` lines (knowledge base, change
  request, version); the parser ignores them.
* ``## Components`` — one ``### <name> — <kind>, <change_type>`` block per
  component, with an optional trailing ``[human]`` / ``[inferred]`` provenance
  marker; then ``- path: `…``` and ``- requirements: A, B`` bullets; then
  ``#### Existing`` and ``#### Proposed`` free-text blocks (until the next
  ``####`` / ``###`` / ``##``).
* ``## Assumptions`` — ``- <text>`` bullets with optional provenance marker.
* ``## Open Questions`` — ``- [ ] (<ref>) <question> [marker]`` + indented ``Answer:``.
* ``## Sources`` — read-only ``- `path — lines a-b``` bullets (kept as stored).
"""

from __future__ import annotations

from workflow_compiler.models import ChangeSpec, ComponentChange, Provenance, SpecItem
from workflow_compiler.spec.renderer import PROVENANCE_MARKERS

CHANGES_FILENAME = "changes.md"
CHANGES_TITLE = "Change Spec"

GROUNDING_SECTION = "Grounding"
COMPONENTS_SECTION = "Components"
ASSUMPTIONS_SECTION = "Assumptions"
QUESTIONS_SECTION = "Open Questions"
SOURCES_SECTION = "Sources"

EXISTING_HEADING = "Existing"
PROPOSED_HEADING = "Proposed"

_HEADER_COMMENT = (
    "<!--\n"
    "  workflow-compiler change specification (v1) — changes.md\n"
    "  Existing vs. proposed per component, extracted from the design document and\n"
    "  grounded in the knowledge base. Edit it freely, then run validate to fold your\n"
    "  edits back in. Keep the `### name — kind, change` headings on existing entries\n"
    "  so your edits update the right component; new headings are recorded as\n"
    "  human-provided. Lines under Grounding and Sources are read-only.\n"
    "-->"
)


def _marker(provenance: Provenance) -> str:
    marker = PROVENANCE_MARKERS.get(provenance, "")
    return f" {marker}" if marker else ""


def _item_line(item: SpecItem) -> str:
    return f"- {item.text}{_marker(item.provenance)}"


def _text_block(text: str) -> list[str]:
    """A free-text block: the text's lines, or an explicit none marker."""
    body = text.strip("\n").rstrip()
    return body.splitlines() if body.strip() else ["<!-- none -->"]


def render_component(component: ComponentChange) -> list[str]:
    """Render one ``### name — kind, change`` block."""
    lines = [
        f"### {component.name} — {component.kind.value}, {component.change_type.value}"
        + _marker(component.provenance),
        f"- path: `{component.path}`" if component.path else "- path:",
        (
            f"- requirements: {', '.join(component.requirement_ids)}"
            if component.requirement_ids
            else "- requirements:"
        ),
        "",
        f"#### {EXISTING_HEADING}",
        *_text_block(component.existing),
        "",
        f"#### {PROPOSED_HEADING}",
        *_text_block(component.proposed),
        "",
    ]
    return lines


def render_change_spec(
    spec: ChangeSpec,
    *,
    kb_id: str | None = None,
    kb_name: str = "",
    change_request_id: str | None = None,
    change_request_title: str = "",
) -> str:
    """Render ``spec`` to ``changes.md``.

    The grounding arguments are display-only (they belong to the project, not
    the change spec) and are ignored by the parser.
    """
    lines: list[str] = [f"# {CHANGES_TITLE}", "", _HEADER_COMMENT, ""]

    def section(title: str, body: list[str]) -> None:
        lines.append(f"## {title}")
        lines.extend(body or ["<!-- none -->"])
        lines.append("")

    grounding: list[str] = []
    if kb_id:
        label = f"{kb_name} (`{kb_id}`)" if kb_name else f"`{kb_id}`"
        grounding.append(f"- knowledge base: {label}")
    if change_request_id:
        label = (
            f"{change_request_title} (`{change_request_id}`)"
            if change_request_title
            else f"`{change_request_id}`"
        )
        grounding.append(f"- change request: {label}")
    grounding.append(f"- version: {spec.version}")
    section(GROUNDING_SECTION, grounding)

    component_lines: list[str] = []
    for component in spec.components:
        component_lines.extend(render_component(component))
    if component_lines and component_lines[-1] == "":
        component_lines.pop()
    section(COMPONENTS_SECTION, component_lines)

    section(ASSUMPTIONS_SECTION, [_item_line(item) for item in spec.assumptions])

    question_lines: list[str] = []
    for question in spec.open_questions:
        box = "x" if question.resolved else " "
        ref = f"({question.ref}) " if question.ref else ""
        question_lines.append(f"- [{box}] {ref}{question.text}{_marker(question.provenance)}")
        question_lines.append(f"  Answer: {question.answer or ''}")
    section(QUESTIONS_SECTION, question_lines)

    section(SOURCES_SECTION, [f"- `{source}`" for source in spec.sources])

    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "ASSUMPTIONS_SECTION",
    "CHANGES_FILENAME",
    "CHANGES_TITLE",
    "COMPONENTS_SECTION",
    "EXISTING_HEADING",
    "GROUNDING_SECTION",
    "PROPOSED_HEADING",
    "QUESTIONS_SECTION",
    "SOURCES_SECTION",
    "render_change_spec",
    "render_component",
]

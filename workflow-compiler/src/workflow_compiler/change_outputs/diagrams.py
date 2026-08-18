"""Deterministic half of the diagram stage: which diagrams, checks, and the flow doc.

The model rewrites Mermaid text; this module decides what to ask for (the
reference ``.mmd`` files found in the knowledge base plus the change spec's
new companion diagram), verifies each answer (header present, every expected
state named, balanced ``subgraph``/``end`` and braces) and assembles the
``system-flow-diagram.md`` document with numbered H2 sections — the original
three, the per-workflow spec mermaid as section 4 (decision D10), then any
new companion diagram.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from workflow_compiler.change_outputs.models import DiagramKind, UpdatedDiagram
from workflow_compiler.models.change_spec import ChangeSpec, ComponentKind

_HEADERS = (
    "statediagram-v2", "statediagram", "sequencediagram", "flowchart", "graph",
    "classdiagram", "erdiagram", "journey", "gantt", "c4context", "mindmap", "timeline",
)
_STATE_TOKEN = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*)\b")
_TRANSITION = re.compile(r"^\s*([A-Za-z_][\w]*|\[\*\])\s*-->\s*([A-Za-z_][\w]*|\[\*\])")
_STATE_DECL = re.compile(r"^\s*state\s+(?:\"[^\"]*\"\s+as\s+)?([A-Za-z_][\w]*)")
_MULTI_SEGMENT = re.compile(r"\b[A-Z]{3,}(?:_[A-Z0-9]{2,})+\b")
_FENCE = re.compile(r"```mermaid[^\n]*\n(.*?)\n```", re.S)
_H2 = re.compile(r"^##\s+(\d+)\.\s+(.*)$", re.M)


def mermaid_header(text: str) -> str | None:
    """The diagram type keyword of the first non-empty, non-directive line."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        head = stripped.split()[0].lower()
        return head if head in _HEADERS else None
    return None


def diagram_kind_of(name: str, text: str = "") -> DiagramKind:
    """Guess the kind from the file name (then the header)."""
    lowered = name.lower()
    if "partial" in lowered or "sub-state" in lowered or "group" in lowered:
        return DiagramKind.STATE_PARTIAL
    if "sequence" in lowered:
        return DiagramKind.SEQUENCE
    if "architecture" in lowered or "system" in lowered:
        return DiagramKind.ARCHITECTURE
    if "state" in lowered:
        return DiagramKind.STATE
    header = mermaid_header(text) or ""
    if header.startswith("sequence"):
        return DiagramKind.SEQUENCE
    if header in ("flowchart", "graph"):
        return DiagramKind.ARCHITECTURE
    return DiagramKind.STATE


def states_in(text: str) -> set[str]:
    """State names of a Mermaid state diagram (transition ends + declarations)."""
    found: set[str] = set()
    if (mermaid_header(text) or "").startswith("statediagram"):
        for line in text.splitlines():
            for match in _TRANSITION.finditer(line):
                for tok in match.groups():
                    if tok != "[*]":
                        found.add(tok)
            decl = _STATE_DECL.match(line)
            if decl:
                found.add(decl.group(1))
    return found


def balanced(text: str) -> list[str]:
    """Structural problems: unbalanced ``subgraph``/``end``, ``{``/``}``, ``loop/alt/opt``."""
    problems: list[str] = []
    header = mermaid_header(text) or ""
    if header in ("flowchart", "graph"):
        opens = len(re.findall(r"^\s*subgraph\b", text, re.M))
        ends = len(re.findall(r"^\s*end\b", text, re.M))
        if opens != ends:
            problems.append(f"unbalanced subgraph/end ({opens} subgraph, {ends} end)")
    if header.startswith("statediagram") and text.count("{") != text.count("}"):
        problems.append("unbalanced braces in composite state")
    if header.startswith("sequence"):
        opens = len(re.findall(r"^\s*(?:loop|alt|opt|par|critical|rect|break)\b", text, re.M))
        ends = len(re.findall(r"^\s*end\b", text, re.M))
        if opens != ends:
            problems.append(f"unbalanced block/end ({opens} blocks, {ends} end)")
    return problems


def expected_states(spec: ChangeSpec | None, original_states: Iterable[str]) -> set[str]:
    """States an updated state diagram must name.

    The original diagram's states (nothing the design keeps may vanish) plus
    every multi-segment UPPER_SNAKE token the change spec proposes on a type /
    diagram / workflow / module component (``PARTIALLY_PROVISIONED``). Single
    words are too ambiguous to require (``OK``, ``TDD``).
    """
    states = set(original_states)
    if spec is None:
        return states
    for component in spec.components:
        if component.kind not in (
            ComponentKind.TYPE, ComponentKind.DIAGRAM, ComponentKind.WORKFLOW, ComponentKind.MODULE,
        ):
            continue
        for match in _MULTI_SEGMENT.finditer(component.proposed):
            token = match.group(0)
            if token.startswith(("TDD_", "TC_", "US_", "BCR_", "BR_", "EPIC_", "TP_")):
                continue
            states.add(token)
    return states


def check_diagram(
    diagram: UpdatedDiagram, *, required_states: Iterable[str] = ()
) -> list[str]:
    """Deterministic checks; a list of failure messages (empty = passed)."""
    text = diagram.updated
    failures: list[str] = []
    if not text.strip():
        return ["empty diagram"]
    if mermaid_header(text) is None:
        failures.append("missing Mermaid header (stateDiagram-v2 / sequenceDiagram / flowchart)")
    failures.extend(balanced(text))
    if diagram.kind in (DiagramKind.STATE, DiagramKind.STATE_PARTIAL) and required_states:
        present = states_in(text)
        missing = sorted(s for s in required_states if s not in present)
        if missing:
            failures.append("missing state(s): " + ", ".join(missing))
    return failures


# --------------------------------------------------------------------------- #
# What to ask for
# --------------------------------------------------------------------------- #


@dataclass
class DiagramRequest:
    """One diagram the stage produces."""

    name: str
    kind: DiagramKind
    source_path: str = ""  # corpus path of the original ("" when new)
    original: str | None = None
    reasons: list[str] = field(default_factory=list)


def plan_diagrams(
    spec: ChangeSpec | None, corpus_files: Sequence[str]
) -> list[DiagramRequest]:
    """Every ``.mmd`` in the corpus (regenerated by D10) plus new ones the spec adds."""
    requests: list[DiagramRequest] = []
    seen: set[str] = set()
    for path in sorted(p for p in corpus_files if p.lower().endswith(".mmd")):
        name = path.rsplit("/", 1)[-1]
        requests.append(DiagramRequest(name=name, kind=diagram_kind_of(name), source_path=path))
        seen.add(name.lower())
    if spec is not None:
        for component in spec.components:
            if component.kind is not ComponentKind.DIAGRAM and not component.name.lower().endswith(
                ".mmd"
            ):
                continue
            name = component.name.strip().strip("`").replace("\\", "/").rsplit("/", 1)[-1]
            if not name.lower().endswith(".mmd"):
                continue
            existing = next((r for r in requests if r.name.lower() == name.lower()), None)
            if existing is not None:
                existing.reasons.append(component.proposed.strip() or component.change_type.value)
                continue
            requests.append(
                DiagramRequest(
                    name=name,
                    kind=diagram_kind_of(name),
                    reasons=[component.proposed.strip() or "new diagram"],
                )
            )
            seen.add(name.lower())
    return requests


# --------------------------------------------------------------------------- #
# system-flow-diagram.md
# --------------------------------------------------------------------------- #


def _sections_of(markdown: str) -> list[tuple[str, str, str]]:
    """``(title, intro, mermaid)`` per numbered H2 of the original flow document."""
    out: list[tuple[str, str, str]] = []
    matches = list(_H2.finditer(markdown))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[match.end():end]
        fence = _FENCE.search(body)
        intro = body[: fence.start()].strip() if fence else body.strip()
        out.append((match.group(2).strip(), intro, fence.group(1) if fence else ""))
    return out


def _title_of(markdown: str) -> str:
    match = re.search(r"^#\s+(.*)$", markdown, re.M)
    return match.group(1).strip() if match else "System & Process Flow Diagrams"


def _preamble_of(markdown: str) -> str:
    """Text between the H1 and the first H2."""
    h1 = re.search(r"^#\s+.*$", markdown, re.M)
    first = _H2.search(markdown)
    if h1 is None:
        return ""
    end = first.start() if first else len(markdown)
    return markdown[h1.end():end].strip()


def _match_section(title: str, diagrams: Sequence[UpdatedDiagram]) -> UpdatedDiagram | None:
    lowered = title.lower()
    wanted: DiagramKind | None = None
    if "sequence" in lowered:
        wanted = DiagramKind.SEQUENCE
    elif "architecture" in lowered:
        wanted = DiagramKind.ARCHITECTURE
    elif "state" in lowered:
        wanted = DiagramKind.STATE
    if wanted is None:
        return None
    return next((d for d in diagrams if d.kind is wanted), None)


def assemble_system_flow(
    original_md: str | None,
    diagrams: Sequence[UpdatedDiagram],
    workflow_diagrams: Mapping[str, str],
    *,
    change_title: str = "",
) -> str:
    """Rebuild the flow document with the updated diagrams.

    Sections 1-3 keep the original titles / intros (matched by kind) with the
    updated Mermaid; section 4 is the per-workflow specification diagram(s)
    from the approved spec (D10); the companion (``state-partial``) diagrams and
    any other new diagram follow as further numbered sections.
    """
    used: set[int] = set()
    lines: list[str] = []
    title = _title_of(original_md or "")
    lines.append(f"# {title}")
    lines.append("")
    if change_title:
        lines.append(f"_Updated for {change_title}._")
        lines.append("")
    preamble = _preamble_of(original_md or "")
    if preamble:
        lines.append(preamble)
        lines.append("")
    number = 0
    for section_title, intro, original_mermaid in _sections_of(original_md or ""):
        number += 1
        match = _match_section(section_title, diagrams)
        lines.append(f"## {number}. {section_title}")
        lines.append("")
        if intro:
            lines.append(intro)
            lines.append("")
        mermaid = match.updated if match is not None and match.updated.strip() else original_mermaid
        if match is not None:
            used.add(id(match))
        lines.append("```mermaid")
        lines.append(mermaid.rstrip("\n"))
        lines.append("```")
        lines.append("")
    if workflow_diagrams:
        number += 1
        many = len(workflow_diagrams) > 1
        lines.append(f"## {number}. Workflow Specification" + (" Diagrams" if many else " Diagram"))
        lines.append("")
        lines.append(
            "Generated from the approved workflow specification (the compiled graph), "
            "one per workflow."
        )
        lines.append("")
        for slug, mermaid in workflow_diagrams.items():
            if many:
                lines.append(f"### {slug}")
                lines.append("")
            lines.append("```mermaid")
            lines.append(mermaid.rstrip("\n"))
            lines.append("```")
            lines.append("")
    for diagram in diagrams:
        if id(diagram) in used or not diagram.updated.strip():
            continue
        number += 1
        pretty = diagram.name.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()
        lines.append(f"## {number}. {pretty}")
        lines.append("")
        if diagram.notes:
            lines.append(diagram.notes.strip())
            lines.append("")
        lines.append("```mermaid")
        lines.append(diagram.updated.rstrip("\n"))
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"

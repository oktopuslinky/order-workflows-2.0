"""Deterministic change-spec validation → findings under the ``__changes__`` slug.

No model is involved. Three rules (plan Phase 3):

* a component whose ``path`` cannot be resolved in the knowledge base →
  ``WARNING`` with suggestions from :meth:`KgService.search`;
* a requirement id the linked change request does not declare → ``WARNING``;
* an empty ``proposed`` text → ``BLOCKING`` (the change spec must say what
  changes; "removed" is a proposal too).

The findings land in ``project.validation_findings["__changes__"]`` so the
Resolve dialogue's agenda picks them up exactly like a workflow's findings.
"""

from __future__ import annotations

from collections.abc import Iterable

from workflow_compiler.kg.service import KgService
from workflow_compiler.models import (
    CHANGES_SLUG,
    ChangeSpec,
    ChangeType,
    ComponentChange,
    Severity,
    SpecFinding,
)

COMPONENTS_SECTION = "Components"
QUESTIONS_SECTION = "Open Questions"

#: How many search hits to offer as suggestions for an unresolved path.
_SUGGESTIONS = 3


def _finding(
    severity: Severity,
    message: str,
    *,
    field: str | None = None,
    suggestion: str | None = None,
    section: str = COMPONENTS_SECTION,
) -> SpecFinding:
    return SpecFinding(
        severity=severity,
        workflow=CHANGES_SLUG,
        section=section,
        field=field,
        message=message,
        suggestion=suggestion,
    )


def _label(component: ComponentChange) -> str:
    return f"{component.name} ({component.kind.value})"


async def _suggest(kg: KgService, kb_id: str, component: ComponentChange) -> str | None:
    """``KgService.search`` hits for the component's name/path, as a suggestion."""
    query = " ".join(part for part in (component.name, component.path) if part)
    try:
        hits = await kg.search(kb_id, query, k=_SUGGESTIONS)
    except Exception:
        return None
    if not hits:
        return None
    options = ", ".join(f"`{hit.node_id}`" for hit in hits[:_SUGGESTIONS])
    return f"did you mean {options}? Fix the path or clear it if the component is new"


async def validate_change_spec(
    spec: ChangeSpec,
    *,
    kg: KgService | None = None,
    kb_id: str | None = None,
    requirement_ids: Iterable[str] | None = None,
) -> list[SpecFinding]:
    """Validate ``spec`` and return its findings (empty when clean).

    ``kg``/``kb_id`` enable the path check (skipped when either is missing);
    ``requirement_ids`` (the linked change request's) enables the requirement
    check (skipped when ``None``, i.e. no change request is linked).
    """
    findings: list[SpecFinding] = []
    known_reqs = (
        {r.strip().upper() for r in requirement_ids if r.strip()}
        if requirement_ids is not None
        else None
    )

    if not spec.components:
        findings.append(
            _finding(
                Severity.WARNING,
                "the change spec lists no components",
                suggestion="add one `### name — kind, change` block per affected component",
            )
        )

    for component in spec.components:
        label = _label(component)
        if not component.proposed.strip():
            findings.append(
                _finding(
                    Severity.BLOCKING,
                    f"{label} has no proposed change",
                    field=component.name,
                    suggestion=(
                        "describe what changes under '#### Proposed' (for a removal, say "
                        "what is removed and what replaces it)"
                    ),
                )
            )
        if (
            component.path
            and kg is not None
            and kb_id
            and component.change_type is not ChangeType.ADD
        ):
            try:
                resolved = await kg.resolve_ref(kb_id, component.path)
            except Exception:
                resolved = component.path
            if resolved is None:
                findings.append(
                    _finding(
                        Severity.WARNING,
                        f"{label} points at `{component.path}`, which is not in the knowledge base",
                        field=component.name,
                        suggestion=await _suggest(kg, kb_id, component),
                    )
                )
        if known_reqs is not None:
            unknown = [r for r in component.requirement_ids if r.strip().upper() not in known_reqs]
            if unknown:
                findings.append(
                    _finding(
                        Severity.WARNING,
                        f"{label} cites requirement(s) {', '.join(unknown)} that the change "
                        "request does not declare",
                        field=component.name,
                        suggestion=(
                            "use the change request's requirement ids "
                            + (f"({', '.join(sorted(known_reqs))})" if known_reqs else "")
                        ).strip(),
                    )
                )

    return findings


__all__ = ["validate_change_spec"]

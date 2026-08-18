"""Change-spec bookkeeping for the guided dialogue (the ``__changes__`` slug).

The workflow specs change through :mod:`workflow_compiler.dialogue.spec_ops`
(patches → ``EditPatchApplier``). The change spec has no patch vocabulary —
its LLM plan is a list of :class:`~workflow_compiler.models.change_spec.ComponentUpdate`
rows — so its deterministic half lives here: apply the updates to a **copy**
of the spec, stamp what a human touched ``HUMAN_PROVIDED``, resolve the open
questions the answer settled, bump the version once, and swap the copy in.
Parking follows the same rule as a workflow spec: the answer becomes a new
unresolved, human-provided open question rather than being discarded.
"""

from __future__ import annotations

from workflow_compiler.models import (
    ChangeSpec,
    CompilationProject,
    ComponentChange,
    ComponentUpdate,
    Provenance,
    SpecItem,
)
from workflow_compiler.spec.change_ingest import coerce_change_type, coerce_kind


def _find(spec: ChangeSpec, name: str, kind: str | None) -> ComponentChange | None:
    """Locate a component by name (and kind when it disambiguates)."""
    needle = name.strip().strip("`").lower()
    if not needle:
        return None
    hits = [c for c in spec.components if c.name.strip().lower() == needle]
    if not hits:
        tail = needle.rsplit("/", 1)[-1]
        hits = [c for c in spec.components if c.name.strip().lower().rsplit("/", 1)[-1] == tail]
    if len(hits) > 1 and kind:
        wanted = coerce_kind(kind).value
        narrowed = [c for c in hits if c.kind.value == wanted]
        if narrowed:
            hits = narrowed
    return hits[0] if hits else None


def apply_component_updates(
    spec: ChangeSpec,
    updates: list[ComponentUpdate],
    *,
    resolve_questions: list[str] | None = None,
) -> tuple[ChangeSpec, list[str], list[str]]:
    """Apply ``updates`` to a copy of ``spec``; return ``(new, summary, warnings)``.

    ``modify`` carries only the fields that change (``None`` = keep); ``add``
    creates a human-provided component; ``remove`` drops one. An update that
    names an unknown component is reported in ``warnings`` and skipped, never
    raised. The version bumps once when anything changed.
    """
    new = spec.model_copy(deep=True)
    summary: list[str] = []
    warnings: list[str] = []
    for update in updates:
        action = (update.action or "modify").strip().lower()
        name = update.name.strip().strip("`")
        if not name:
            warnings.append("update without a component name skipped")
            continue
        target = _find(new, name, update.kind)
        if action == "remove":
            if target is None:
                warnings.append(f"remove skipped — no component named {name!r}")
                continue
            new.components = [c for c in new.components if c is not target]
            summary.append(f"removed component {target.name} ({target.kind.value})")
            continue
        if action == "add" or target is None:
            if action != "add":
                # A modify of something the spec does not list becomes an add:
                # the user named a real component and said what changes.
                warnings.append(f"no component named {name!r}; added it instead")
            component = ComponentChange(
                name=name,
                kind=coerce_kind(update.kind or "module"),
                path=(update.path or "").strip(),
                existing=(update.existing or "").strip(),
                proposed=(update.proposed or "").strip(),
                change_type=coerce_change_type(update.change_type or "modify"),
                requirement_ids=list(update.requirement_ids or []),
                provenance=Provenance.HUMAN_PROVIDED,
            )
            new.components.append(component)
            summary.append(f"added component {component.name} ({component.kind.value})")
            continue
        changed: list[str] = []
        if update.kind is not None and coerce_kind(update.kind) != target.kind:
            target.kind = coerce_kind(update.kind)
            changed.append("kind")
        if update.path is not None and update.path.strip() != target.path:
            target.path = update.path.strip()
            changed.append("path")
        if update.existing is not None and update.existing.strip() != target.existing:
            target.existing = update.existing.strip()
            changed.append("existing")
        if update.proposed is not None and update.proposed.strip() != target.proposed:
            target.proposed = update.proposed.strip()
            changed.append("proposed")
        if (
            update.change_type is not None
            and coerce_change_type(update.change_type) != target.change_type
        ):
            target.change_type = coerce_change_type(update.change_type)
            changed.append("change_type")
        if update.requirement_ids is not None:
            reqs = [r.strip() for r in update.requirement_ids if r.strip()]
            if reqs != target.requirement_ids:
                target.requirement_ids = reqs
                changed.append("requirements")
        if changed:
            target.provenance = Provenance.HUMAN_PROVIDED
            summary.append(
                f"updated {target.name} ({target.kind.value}): {', '.join(changed)}"
            )
        else:
            warnings.append(f"update to {target.name} changed nothing")
    for text in resolve_questions or []:
        needle = text.strip().lower()
        for question in new.open_questions:
            if not question.resolved and question.text.strip().lower() == needle:
                question.resolved = True
                summary.append(f"resolved open question: {question.text}")
    if summary:
        new.version = spec.version + 1
        summary.append(f"change spec version bumped to {new.version}")
    return new, summary, warnings


def park_change_question(spec: ChangeSpec, note: str, ref: str) -> ChangeSpec:
    """Record ``note`` as a new unresolved, human-provided open question."""
    new = spec.model_copy(deep=True)
    new.open_questions = [
        *new.open_questions,
        SpecItem(text=note, provenance=Provenance.HUMAN_PROVIDED, resolved=False, ref=ref),
    ]
    return new


def replace_change_spec(project: CompilationProject, spec: ChangeSpec) -> None:
    """Install ``spec`` on the project (mirrors :func:`spec_ops.replace_spec`)."""
    project.change_spec = spec


__all__ = ["apply_component_updates", "park_change_question", "replace_change_spec"]

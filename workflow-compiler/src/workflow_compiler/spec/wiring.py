"""Applying cross-workflow dependency operations to a project.

A cross-reference is the one piece of the specification that belongs to the
*project* rather than to any single workflow, so it cannot be expressed as a
:class:`~workflow_compiler.models.patch.Patch` against a spec — the edit path
carries a typed :class:`~workflow_compiler.models.edit.XrefOp` for it instead.

This module holds the applier so the **edit path and the conversational path use
the same one**. Both can confirm, correct, or drop a dependency, and neither may
develop its own idea of what those mean: an unconfirmed dependency is a hard stop
at approval, so the code that clears it is load-bearing.

Note that ``ADD`` and ``MODIFY`` both mark the result ``user_confirmed=True``.
That is the point of them — a human naming a dependency *is* the confirmation.
Confirming an existing dependency unchanged is therefore a ``MODIFY`` carrying
the same four-tuple, not a separate verb.
"""

from __future__ import annotations

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.models import CompilationProject, CrossReference
from workflow_compiler.models.edit import WiringAction, XrefOp


def _key(ref: CrossReference) -> tuple[str, str, str, str]:
    """The four-tuple that identifies a dependency."""
    return (ref.source_workflow, ref.output_field, ref.target_workflow, ref.input_field)


def apply_xref_op(project: CompilationProject, op: XrefOp) -> str:
    """Apply one cross-reference operation in place; return a summary line.

    Raises :class:`CompilationError` for an operation that cannot be carried out
    (unknown workflow, adding a duplicate, removing something absent, an
    ambiguous modify) rather than guessing — a mis-wired dependency corrupts the
    generated saga's hand-off.
    """
    if op.reference is None:
        raise CompilationError(
            f"Dependency {op.action.value} operation carries no reference payload."
        )
    ref = op.reference
    slugs = {spec.slug for spec in project.specs}
    for endpoint in (ref.source_workflow, ref.target_workflow):
        if endpoint not in slugs:
            raise CompilationError(
                f"Dependency operation references unknown workflow '{endpoint}'. "
                f"Known: {sorted(slugs)}."
            )
    label = (
        f"{ref.source_workflow}.{ref.output_field} → "
        f"{ref.target_workflow}.{ref.input_field}"
    )

    exact = next(
        (i for i, r in enumerate(project.cross_references) if _key(r) == _key(ref)),
        -1,
    )
    if op.action is WiringAction.ADD:
        if exact != -1:
            raise CompilationError(f"Dependency {label} already exists.")
        project.cross_references.append(ref.model_copy(update={"user_confirmed": True}))
        return f"added dependency {label}"
    if op.action is WiringAction.REMOVE:
        if exact == -1:
            raise CompilationError(f"No dependency {label} to remove.")
        project.cross_references.pop(exact)
        return f"removed dependency {label}"

    # MODIFY: replace the reference between the same workflow pair. When the pair
    # has several links, disambiguate by matching either endpoint field.
    candidates = [
        i
        for i, r in enumerate(project.cross_references)
        if r.source_workflow == ref.source_workflow
        and r.target_workflow == ref.target_workflow
    ]
    if len(candidates) > 1:
        candidates = [
            i
            for i in candidates
            if project.cross_references[i].output_field == ref.output_field
            or project.cross_references[i].input_field == ref.input_field
        ]
    if len(candidates) != 1:
        raise CompilationError(
            f"Cannot identify which dependency between {ref.source_workflow} "
            f"and {ref.target_workflow} to modify — remove and re-add it instead."
        )
    was_unconfirmed = not project.cross_references[candidates[0]].user_confirmed
    unchanged = _key(project.cross_references[candidates[0]]) == _key(ref)
    project.cross_references[candidates[0]] = ref.model_copy(
        update={"user_confirmed": True}
    )
    if unchanged and was_unconfirmed:
        # The common conversational case: the user was asked whether a detected
        # dependency is real and said yes. Saying "modified" would be confusing.
        return f"confirmed dependency {label}"
    return f"modified dependency {label}"

"""EditPatchApplier: apply human-authored edit patches to a WorkflowSpec.

Wraps :class:`~workflow_compiler.spec.validator.SpecPatchApplier` in its
human-authority mode and adds the provenance bookkeeping the edit flow needs:
every element the patches created is marked ``HUMAN_PROVIDED`` (the human wrote
the edit request — no grounded-vs-inferred detection), and provenance entries
for removed elements are cleaned up.
"""

from __future__ import annotations

from workflow_compiler.models import (
    Patch,
    Provenance,
    WorkflowSpec,
)
from workflow_compiler.spec.validator import SpecPatchApplier

#: Metadata list fields tracked for provenance, keyed as ``<field>:<value>``.
_METADATA_LIST_FIELDS = (
    "actors",
    "systems",
    "trigger_events",
    "start_states",
    "end_states",
    "tags",
)


def _element_refs(spec: WorkflowSpec) -> set[str]:
    """Every provenance-addressable element reference currently in ``spec``.

    Entity refs use the stable structure id (``activity:a3``); scalar facts use
    the category + lowercased statement (``rule:refunds over $500 …``), matching
    the keys the spec validator's ``_is_human`` check looks up; metadata list
    items use ``<field>:<value>``.
    """
    refs: set[str] = set()
    structure = spec.facts.structure
    if structure is not None:
        for kind, nodes in (
            ("activity", structure.activities),
            ("decision", structure.decisions),
            ("exception", structure.exceptions),
            ("compensation", structure.compensations),
            ("event", structure.events),
        ):
            refs.update(f"{kind}:{node.id}" for node in nodes)
    for fact in spec.facts.facts:
        refs.add(f"{fact.category.value}:{fact.statement.lower()}")
    for field in _METADATA_LIST_FIELDS:
        for value in getattr(spec.metadata, field, None) or []:
            refs.add(f"{field}:{value}")
    return refs


class EditPatchApplier:
    """Apply edit-request patches with human authority and record provenance."""

    def __init__(self) -> None:
        self._applier = SpecPatchApplier(human_authority=True)

    def apply(
        self, spec: WorkflowSpec, patches: list[Patch], document_text: str
    ) -> tuple[WorkflowSpec, list[str], list[str]]:
        """Return ``(new_spec, summary_lines, warnings)``.

        Pure: the input spec is never mutated. ``warnings`` carries the
        applier's findings (e.g. pruned references); ``summary_lines`` is a
        short human-readable account of what changed.
        """
        working = spec.model_copy(deep=True)
        before = _element_refs(working)

        working, warnings, provenance_note = self._applier.apply(
            working, patches, document_text
        )

        after = _element_refs(working)
        provenance = dict(working.provenance)
        for ref in after - before:
            provenance[ref] = Provenance.HUMAN_PROVIDED
        for ref in before - after:
            provenance.pop(ref, None)
        working.provenance = provenance

        summary_lines = [
            f"{patch.action.value} {patch.target}".strip() for patch in patches
        ]
        if provenance_note and provenance_note != "no_change":
            summary_lines.append(provenance_note)
        return working, summary_lines, warnings

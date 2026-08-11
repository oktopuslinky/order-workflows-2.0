"""Spec bookkeeping shared by both conversational doors to the spec gate.

The guided dialogue (:mod:`workflow_compiler.dialogue.engine`) and the free-form
chat (:mod:`workflow_compiler.dialogue.chat`) differ in *what they ask* and
*when*, but they change a specification in exactly the same way: patches go
through :class:`~workflow_compiler.spec.edit_applier.EditPatchApplier` with
human authority, the patch version bumps once per accepted instruction, the new
spec is swapped in wholesale, and the project returns to the spec gate so
approval waits for a fresh validate.

Keeping that one copy here is deliberate. The two engines must not be able to
drift on provenance or on the gate reset — those are the properties that make an
applied answer safe to approve.
"""

from __future__ import annotations

import re

from workflow_compiler.models import (
    CompilationProject,
    Patch,
    Provenance,
    SpecItem,
    WorkflowSpec,
)
from workflow_compiler.models.enums import ApprovalStatus
from workflow_compiler.models.project import ProjectStage
from workflow_compiler.spec.edit_applier import EditPatchApplier


def bump_patch_version(version: str) -> str | None:
    """``X.Y.Z`` → ``X.Y.(Z+1)``; ``None`` when ``version`` is not semver.

    Returning ``None`` rather than inventing a version keeps a hand-written
    version string (``"draft"``, ``"2026-08"``) intact instead of clobbering it.
    """
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        return None
    major, minor, patch = (int(g) for g in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def replace_spec(project: CompilationProject, spec: WorkflowSpec) -> None:
    """Swap ``spec`` in by slug, preserving order."""
    project.specs = [spec if s.slug == spec.slug else s for s in project.specs]


def reset_to_spec_gate(project: CompilationProject) -> None:
    """Return the project to the editable-spec gate after a change.

    Any conversational change invalidates a prior approval, so the project drops
    back to ``SPEC_DRAFTED`` / ``PENDING``. Findings are *not* touched here —
    the two engines have different, deliberate rules about when to drop them.
    """
    project.spec_approval_status = ApprovalStatus.PENDING
    project.stage = ProjectStage.SPEC_DRAFTED
    project.touch()


def apply_patches(
    project: CompilationProject,
    spec: WorkflowSpec,
    patches: list[Patch],
    applier: EditPatchApplier,
) -> tuple[WorkflowSpec, list[str], list[str]]:
    """Fold effective ``patches`` into ``spec``, bump its version, swap it in.

    Returns ``(new_spec, summary_lines, warnings)``. Pure with respect to
    ``spec`` — a new instance is built and installed on the project, so a failed
    apply can never leave a half-changed specification behind.
    """
    effective = [p for p in patches if not p.is_noop()]
    new_spec, summary, warnings = applier.apply(spec, effective, project.document_text)
    bumped = bump_patch_version(new_spec.metadata.version)
    if bumped is not None:
        new_spec.metadata = new_spec.metadata.model_copy(update={"version": bumped})
        summary.append(f"version bumped to {bumped}")
    replace_spec(project, new_spec)
    return new_spec, summary, warnings


def park_as_open_question(
    project: CompilationProject, spec: WorkflowSpec, note: str, ref: str
) -> WorkflowSpec:
    """Record ``note`` as a new unresolved open question on ``spec``.

    The user told us something real; it just is not a spec change yet. Stored
    ``HUMAN_PROVIDED`` and unresolved, so the validator surfaces it for
    confirmation but nothing is ever silently dropped.
    """
    parked = SpecItem(
        text=note,
        provenance=Provenance.HUMAN_PROVIDED,
        resolved=False,
        ref=ref,
    )
    new_spec = spec.model_copy(deep=True)
    new_spec.open_questions = [*new_spec.open_questions, parked]
    replace_spec(project, new_spec)
    return new_spec

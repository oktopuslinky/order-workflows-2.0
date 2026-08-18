"""What the dialogue may ask about, and a digest of it.

Two things live here because they must agree, and would drift if they were
written twice:

* :func:`askable_findings` — the rule that only **blocking and warning** findings
  earn a question. INFO records non-problems (a folded-in edit, an ingest note)
  and would only pad the agenda.
* :func:`agenda_fingerprint` — a digest over *exactly* the inputs an agenda is
  drafted from. Pre-drafting happens minutes before the user opens the session,
  and the specs can move underneath it (the free-form chat, a hand edit, another
  validate). Comparing fingerprints is how a prepared agenda is known to still
  describe the project it was drafted for.

The fingerprint is deliberately **not** a hash of the whole project. Rendering
timestamps, stage timings and approval status all change without changing what
there is to ask about, and hashing them would throw away good agendas for no
reason. It covers the findings that earn questions, each spec's unresolved open
questions, and each spec's version — the last so that a spec edited to the same
findings is still treated as new material.
"""

from __future__ import annotations

import hashlib

from workflow_compiler.models.change_spec import CHANGES_SLUG
from workflow_compiler.models.findings import Severity, SpecFinding
from workflow_compiler.models.project import CompilationProject

#: Severities that earn a question. INFO records non-problems and would only pad
#: the agenda.
ASKED_SEVERITIES = frozenset({Severity.BLOCKING, Severity.WARNING})

#: Blocking findings sort ahead of warnings within a workflow's agenda.
SEVERITY_ORDER: dict[Severity, int] = {
    Severity.BLOCKING: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


def askable_findings(project: CompilationProject, slug: str) -> list[SpecFinding]:
    """Blocking + warning findings for ``slug``, most severe first."""
    found = [
        f
        for f in project.validation_findings.get(slug, [])
        if f.severity in ASKED_SEVERITIES
    ]
    return sorted(found, key=lambda f: SEVERITY_ORDER[f.severity])


def has_anything_to_ask(project: CompilationProject) -> bool:
    """True when at least one spec has an askable finding or an open question.

    The cheap check the API uses to decide whether pre-drafting is worth starting
    at all, without paying for a drafting run to discover the agenda is empty.
    """
    if any(
        askable_findings(project, spec.slug) or spec.unresolved_questions()
        for spec in project.specs
    ):
        return True
    return change_spec_has_anything_to_ask(project)


def change_spec_has_anything_to_ask(project: CompilationProject) -> bool:
    """True when the change spec (``changes.md``) has an askable finding or question.

    The change spec is a second file at the same gate: its findings travel
    under :data:`CHANGES_SLUG` and its unresolved open questions count exactly
    like a workflow's.
    """
    change_spec = project.change_spec
    if change_spec is None:
        return False
    return bool(
        askable_findings(project, CHANGES_SLUG) or change_spec.unresolved_questions()
    )


def agenda_fingerprint(project: CompilationProject) -> str:
    """Digest the material an agenda would be drafted from.

    Stable across reorderings that do not change content (findings are sorted
    within a spec by their one-line projection), and sensitive to any change in
    the questions themselves, the specs' versions, or which workflows exist.
    """
    digest = hashlib.sha256()
    for spec in sorted(project.specs, key=lambda s: s.slug):
        digest.update(f"\x00spec\x01{spec.slug}\x01{spec.metadata.version}".encode())
        for line in sorted(f.as_string() for f in askable_findings(project, spec.slug)):
            digest.update(f"\x00finding\x01{line}".encode())
        for question in sorted(q.text for q in spec.unresolved_questions()):
            digest.update(f"\x00question\x01{question}".encode())
    change_spec = project.change_spec
    if change_spec is not None:
        digest.update(f"\x00changes\x01{change_spec.version}".encode())
        for line in sorted(f.as_string() for f in askable_findings(project, CHANGES_SLUG)):
            digest.update(f"\x00finding\x01{line}".encode())
        for question in sorted(q.text for q in change_spec.unresolved_questions()):
            digest.update(f"\x00question\x01{question}".encode())
    return digest.hexdigest()


def prepared_agenda_is_fresh(project: CompilationProject) -> bool:
    """True when the project carries a prepared agenda still matching its inputs."""
    prepared = project.prepared_dialogue
    return prepared is not None and prepared.fingerprint == agenda_fingerprint(project)

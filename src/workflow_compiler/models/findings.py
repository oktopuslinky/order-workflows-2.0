"""Structured spec-validation findings with severity and precise location.

A :class:`SpecFinding` replaces the flat finding strings the spec validator used
to emit. It carries a :class:`Severity`, the workflow / section / field it refers
to, an actionable message, and an optional suggestion, so the terminal can tell
the user exactly which part of which spec needs to change.

Only ``BLOCKING`` findings gate: they prevent code generation, make ``validate``
exit non-zero, and make ``approve-spec`` refuse. ``WARNING`` is advisory; ``INFO``
records non-problems (e.g. an edit that was folded in). ``as_string()`` renders
the legacy one-line projection kept for the overview file and the HTTP API.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class Severity(StrEnum):
    """How much a spec finding matters.

    * ``BLOCKING`` — prevents code generation; ``validate`` exits non-zero and
      ``approve-spec`` refuses while any remain.
    * ``WARNING`` — advisory; the user should look but generation can proceed.
    * ``INFO`` — informational (e.g. an edit that was folded in); never gates.
    """

    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


#: Short uppercase tag rendered in one-line finding output, per severity.
_TAGS: dict[Severity, str] = {
    Severity.BLOCKING: "BLOCK",
    Severity.WARNING: "WARN",
    Severity.INFO: "INFO",
}


class SpecFinding(WorkflowBaseModel):
    """One structured spec-validation finding with severity and location."""

    severity: Severity = Field(
        default=Severity.WARNING, description="How much this finding matters."
    )
    workflow: str = Field(
        default="", description="Slug of the workflow this finding refers to."
    )
    section: str | None = Field(
        default=None,
        description="Spec section the finding sits in, e.g. 'Outputs', 'Decisions'.",
    )
    field: str | None = Field(
        default=None, description="Field / element reference within the section."
    )
    message: str = Field(..., description="What is wrong, in plain language.")
    suggestion: str | None = Field(
        default=None, description="Concrete action that resolves the finding."
    )

    @property
    def tag(self) -> str:
        """Short uppercase severity tag ('BLOCK' / 'WARN' / 'INFO')."""
        return _TAGS[self.severity]

    @property
    def location(self) -> str:
        """The ``section > field`` breadcrumb (empty when neither is set)."""
        parts = [p for p in (self.section, self.field) if p]
        return " > ".join(parts)

    def as_string(self) -> str:
        """One-line projection: ``[TAG] section > field: message (suggestion)``."""
        loc = self.location
        head = f"[{self.tag}] {loc}: {self.message}" if loc else f"[{self.tag}] {self.message}"
        if self.suggestion:
            head += f" ({self.suggestion})"
        return head

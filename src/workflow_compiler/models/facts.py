"""Workflow facts models."""

from __future__ import annotations

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.enums import FactCategory


class SourceSpan(WorkflowBaseModel):
    """A character-offset span into the source document, for traceability."""

    start: int = Field(..., ge=0, description="Inclusive start character offset.")
    end: int = Field(..., ge=0, description="Exclusive end character offset.")
    snippet: str | None = Field(default=None, description="Verbatim source text for the span.")


class WorkflowFact(WorkflowBaseModel):
    """A single atomic, traceable statement extracted from the source document."""

    id: str = Field(..., description="Stable identifier for the fact.")
    statement: str = Field(..., description="The extracted fact as a normalized statement.")
    category: FactCategory = Field(
        default=FactCategory.OTHER, description="Semantic category of the fact."
    )
    subject: str | None = Field(default=None, description="Primary actor/entity the fact is about.")
    source_span: SourceSpan | None = Field(
        default=None, description="Location of the supporting text in the source document."
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Extraction confidence in [0, 1]."
    )


class WorkflowFacts(WorkflowBaseModel):
    """The collection of facts extracted from a workflow document."""

    facts: list[WorkflowFact] = Field(default_factory=list, description="Extracted facts.")

    def by_category(self, category: FactCategory) -> list[WorkflowFact]:
        """Return all facts matching a given category."""
        return [fact for fact in self.facts if fact.category == category]

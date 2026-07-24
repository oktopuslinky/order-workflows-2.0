"""Prompt template model."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class Prompt(WorkflowBaseModel):
    """A named prompt template loaded from a Markdown file.

    The template body may reference variables with ``{{ name }}`` placeholders.
    ``variables`` lists the variables a caller is required to supply.
    """

    name: str = Field(..., description="Unique prompt name (file stem).")
    template: str = Field(..., description="Raw template body with {{ variable }} placeholders.")
    description: str | None = Field(default=None, description="Human-readable description.")
    variables: list[str] = Field(
        default_factory=list, description="Declared required variables."
    )
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Additional front-matter metadata."
    )
    path: Path | None = Field(default=None, description="Source file path, if loaded from disk.")

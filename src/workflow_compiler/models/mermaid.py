"""Mermaid diagram model."""

from __future__ import annotations

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.enums import MermaidDiagramType, MermaidDirection


class MermaidDiagram(WorkflowBaseModel):
    """A renderable Mermaid diagram derived from the canonical workflow graph."""

    diagram_type: MermaidDiagramType = Field(
        default=MermaidDiagramType.FLOWCHART, description="Mermaid diagram family."
    )
    direction: MermaidDirection = Field(
        default=MermaidDirection.TOP_DOWN, description="Layout direction (flowcharts)."
    )
    source: str = Field(default="", description="The Mermaid diagram source text.")
    title: str | None = Field(default=None, description="Optional diagram title.")

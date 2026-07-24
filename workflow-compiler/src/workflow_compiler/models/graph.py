"""Canonical workflow graph models."""

from __future__ import annotations

from pydantic import Field, model_validator

from workflow_compiler.models.base import WorkflowBaseModel
from workflow_compiler.models.enums import CVPAPhase, EdgeType, NodeType


class WorkflowNode(WorkflowBaseModel):
    """A single node in the canonical workflow graph."""

    id: str = Field(..., description="Unique node identifier within the graph.")
    label: str = Field(..., description="Human-readable node label.")
    node_type: NodeType = Field(default=NodeType.TASK, description="Canonical node kind.")
    cvpa_phase: CVPAPhase = Field(
        default=CVPAPhase.UNCLASSIFIED, description="Capture/Validate/Process/Activate phase."
    )
    description: str | None = Field(default=None, description="Optional node description.")
    fact_ids: list[str] = Field(
        default_factory=list, description="Identifiers of facts that support this node."
    )
    attributes: dict[str, str] = Field(
        default_factory=dict, description="Free-form node attributes."
    )


class WorkflowEdge(WorkflowBaseModel):
    """A directed edge connecting two workflow nodes."""

    id: str = Field(..., description="Unique edge identifier within the graph.")
    source: str = Field(..., description="Source node id.")
    target: str = Field(..., description="Target node id.")
    edge_type: EdgeType = Field(default=EdgeType.SEQUENCE, description="Canonical edge kind.")
    label: str | None = Field(default=None, description="Optional edge label.")
    condition: str | None = Field(
        default=None, description="Guard/condition expression for conditional edges."
    )


class WorkflowGraph(WorkflowBaseModel):
    """A canonical, normalized directed graph of a business workflow."""

    nodes: list[WorkflowNode] = Field(default_factory=list, description="Graph nodes.")
    edges: list[WorkflowEdge] = Field(default_factory=list, description="Graph edges.")

    @model_validator(mode="after")
    def _check_unique_node_ids(self) -> WorkflowGraph:
        """Ensure node ids are unique; edge endpoint integrity is enforced elsewhere."""
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("WorkflowGraph node ids must be unique.")
        return self

    @property
    def node_ids(self) -> set[str]:
        """Return the set of node identifiers."""
        return {node.id for node in self.nodes}

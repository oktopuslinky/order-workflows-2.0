"""Pydantic v2 domain models for workflow-compiler."""

from __future__ import annotations

from workflow_compiler.models.confidence import ConfidenceScores
from workflow_compiler.models.cvpa import (
    CVPAClassification,
    CVPANodeAssignment,
    CVPAPhaseSummary,
)
from workflow_compiler.models.enums import (
    ApprovalStatus,
    CompilationStage,
    CVPAPhase,
    EdgeType,
    FactCategory,
    MermaidDiagramType,
    MermaidDirection,
    NodeType,
    ReviewSeverity,
)
from workflow_compiler.models.facts import SourceSpan, WorkflowFact, WorkflowFacts
from workflow_compiler.models.graph import WorkflowEdge, WorkflowGraph, WorkflowNode
from workflow_compiler.models.mermaid import MermaidDiagram
from workflow_compiler.models.metadata import WorkflowMetadata
from workflow_compiler.models.review import ReviewIssue, ReviewReport
from workflow_compiler.models.state import WorkflowState
from workflow_compiler.models.temporal import (
    RetryPolicyDesign,
    TemporalActivityDesign,
    TemporalChildWorkflowDesign,
    TemporalCompensationDesign,
    TemporalQueryDesign,
    TemporalSignalDesign,
    TemporalTimerDesign,
    TemporalWorkflowDesign,
)

__all__ = [
    # state
    "WorkflowState",
    # metadata
    "WorkflowMetadata",
    # facts
    "SourceSpan",
    "WorkflowFact",
    "WorkflowFacts",
    # graph
    "WorkflowEdge",
    "WorkflowGraph",
    "WorkflowNode",
    # review
    "ReviewIssue",
    "ReviewReport",
    # cvpa
    "CVPAClassification",
    "CVPANodeAssignment",
    "CVPAPhaseSummary",
    # temporal
    "RetryPolicyDesign",
    "TemporalActivityDesign",
    "TemporalChildWorkflowDesign",
    "TemporalCompensationDesign",
    "TemporalQueryDesign",
    "TemporalSignalDesign",
    "TemporalTimerDesign",
    "TemporalWorkflowDesign",
    # mermaid
    "MermaidDiagram",
    # confidence
    "ConfidenceScores",
    # enums
    "ApprovalStatus",
    "CVPAPhase",
    "CompilationStage",
    "EdgeType",
    "FactCategory",
    "MermaidDiagramType",
    "MermaidDirection",
    "NodeType",
    "ReviewSeverity",
]

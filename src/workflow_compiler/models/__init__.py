"""Pydantic v2 domain models for workflow-compiler."""

from __future__ import annotations

from workflow_compiler.models.checklist import (
    ChecklistItem,
    ChecklistSeverity,
    ChecklistStatus,
    WorkflowChecklist,
)
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
from workflow_compiler.models.patch import (
    Evidence,
    Patch,
    PatchAction,
    ReviewResult,
)
from workflow_compiler.models.project import (
    CompilationProject,
    ProjectStage,
    WorkflowSegment,
)
from workflow_compiler.models.review import ReviewIssue, ReviewReport
from workflow_compiler.models.spec import (
    CrossReference,
    Provenance,
    SpecItem,
    WorkflowSpec,
)
from workflow_compiler.models.state import WorkflowState
from workflow_compiler.models.structure import (
    ActivityNode,
    CompensationNode,
    DecisionNode,
    EventNode,
    ExceptionNode,
    TransitionEdge,
    WorkflowStructure,
)
from workflow_compiler.models.temporal import (
    BindingSource,
    GeneratedFile,
    InputBinding,
    RetryPolicyDesign,
    StepKind,
    TemporalActivityDesign,
    TemporalChildWorkflowDesign,
    TemporalCodeBundle,
    TemporalCompensationDesign,
    TemporalParam,
    TemporalQueryDesign,
    TemporalSignalDesign,
    TemporalStep,
    TemporalTimerDesign,
    TemporalWorkflowDesign,
)

__all__ = [
    # state
    "WorkflowState",
    # project (spec-centric front-end aggregate)
    "CompilationProject",
    "ProjectStage",
    "WorkflowSegment",
    # spec (the human-reviewed primary artifact)
    "CrossReference",
    "Provenance",
    "SpecItem",
    "WorkflowSpec",
    # checklist (pre-generation readiness gate)
    "ChecklistItem",
    "ChecklistSeverity",
    "ChecklistStatus",
    "WorkflowChecklist",
    # metadata
    "WorkflowMetadata",
    # facts
    "SourceSpan",
    "WorkflowFact",
    "WorkflowFacts",
    # structure (relational facts)
    "ActivityNode",
    "CompensationNode",
    "DecisionNode",
    "EventNode",
    "ExceptionNode",
    "TransitionEdge",
    "WorkflowStructure",
    # graph
    "WorkflowEdge",
    "WorkflowGraph",
    "WorkflowNode",
    # review
    "ReviewIssue",
    "ReviewReport",
    # patch (review-pipeline vocabulary)
    "Evidence",
    "Patch",
    "PatchAction",
    "ReviewResult",
    # cvpa
    "CVPAClassification",
    "CVPANodeAssignment",
    "CVPAPhaseSummary",
    # temporal
    "BindingSource",
    "InputBinding",
    "RetryPolicyDesign",
    "StepKind",
    "TemporalActivityDesign",
    "TemporalChildWorkflowDesign",
    "TemporalCompensationDesign",
    "TemporalParam",
    "TemporalQueryDesign",
    "TemporalSignalDesign",
    "TemporalStep",
    "TemporalTimerDesign",
    "TemporalWorkflowDesign",
    # temporal code generation
    "GeneratedFile",
    "TemporalCodeBundle",
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

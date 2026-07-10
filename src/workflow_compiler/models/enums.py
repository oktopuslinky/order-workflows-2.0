"""Shared enumerations for workflow-compiler domain models."""

from __future__ import annotations

from enum import StrEnum


class CompilationStage(StrEnum):
    """Ordered stages of the compilation pipeline."""

    INGESTED = "ingested"
    METADATA_EXTRACTED = "metadata_extracted"
    FACTS_EXTRACTED = "facts_extracted"
    CHECKLISTED = "checklisted"
    GRAPH_BUILT = "graph_built"
    REVIEWED = "reviewed"
    CLASSIFIED = "classified"
    TEMPORAL_DESIGNED = "temporal_designed"
    CODE_GENERATED = "code_generated"
    DIAGRAMMED = "diagrammed"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    """Human-in-the-loop approval state for a generated workflow graph."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class CVPAPhase(StrEnum):
    """Capture / Validate / Process / Activate classification phases."""

    CAPTURE = "capture"
    VALIDATE = "validate"
    PROCESS = "process"
    ACTIVATE = "activate"
    UNCLASSIFIED = "unclassified"


class EventKind(StrEnum):
    """How the workflow relates to an event — the distinction the graph builder
    and Temporal design need to wire it correctly.

    - ``TRIGGER``: the event *starts* the workflow (an inbound request/message).
    - ``SIGNAL_WAIT``: the workflow *pauses mid-flow* to receive an external
      signal, usually bounded by a deadline (a Temporal ``wait_condition``).
    - ``OUTPUT_EMIT``: the workflow *produces* a value (an activity's return);
      it is never something the workflow waits for.
    """

    TRIGGER = "trigger"
    SIGNAL_WAIT = "signal_wait"
    OUTPUT_EMIT = "output_emit"


class NodeType(StrEnum):
    """Canonical node kinds in a workflow graph."""

    START = "start"
    END = "end"
    TASK = "task"
    DECISION = "decision"
    GATEWAY = "gateway"
    EVENT = "event"
    SUBPROCESS = "subprocess"
    SIGNAL = "signal"
    TIMER = "timer"
    TRIGGER = "trigger"


class EdgeType(StrEnum):
    """Canonical edge kinds in a workflow graph."""

    SEQUENCE = "sequence"
    CONDITIONAL = "conditional"
    DEFAULT = "default"
    SIGNAL = "signal"
    ERROR = "error"
    RETRY = "retry"
    COMPENSATION = "compensation"


class FactCategory(StrEnum):
    """Classification of an extracted workflow fact."""

    ACTOR = "actor"
    ACTION = "action"
    CONDITION = "condition"
    DATA = "data"
    TRIGGER = "trigger"
    CONSTRAINT = "constraint"
    OUTCOME = "outcome"
    # Detailed fact kinds produced by FactExtractionAgent.
    INPUT = "input"
    OUTPUT = "output"
    ACTIVITY = "activity"
    DECISION = "decision"
    RULE = "rule"
    EVENT = "event"
    API = "api"
    SYSTEM = "system"
    EXCEPTION = "exception"
    STATE_TRANSITION = "state_transition"
    TIMER = "timer"
    RETRY = "retry"
    COMPENSATION = "compensation"
    OTHER = "other"


class ReviewSeverity(StrEnum):
    """Severity level for a review issue."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MermaidDiagramType(StrEnum):
    """Supported Mermaid diagram families."""

    FLOWCHART = "flowchart"
    STATE = "stateDiagram-v2"
    SEQUENCE = "sequenceDiagram"


class MermaidDirection(StrEnum):
    """Layout direction for Mermaid flowcharts."""

    TOP_DOWN = "TD"
    LEFT_RIGHT = "LR"
    BOTTOM_TOP = "BT"
    RIGHT_LEFT = "RL"


__all__ = [
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

"""Temporal workflow design models.

These describe a Temporal (temporal.io) workflow blueprint derived from the
canonical workflow graph: activities, signals, queries, timers, and retry
policies. They are design artifacts, not executable Temporal definitions.
"""

from __future__ import annotations

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class RetryPolicyDesign(WorkflowBaseModel):
    """Design-time retry policy for a Temporal activity."""

    maximum_attempts: int = Field(default=3, ge=0, description="Max attempts; 0 means unlimited.")
    initial_interval_seconds: float = Field(
        default=1.0, gt=0, description="Initial retry interval in seconds."
    )
    backoff_coefficient: float = Field(
        default=2.0, ge=1.0, description="Exponential backoff multiplier."
    )
    maximum_interval_seconds: float | None = Field(
        default=None, description="Cap on retry interval in seconds."
    )
    non_retryable_error_types: list[str] = Field(
        default_factory=list, description="Error types that should not be retried."
    )


class TemporalActivityDesign(WorkflowBaseModel):
    """A single Temporal activity derived from a workflow node."""

    name: str = Field(..., description="Activity name.")
    source_node_id: str | None = Field(
        default=None, description="Graph node this activity was derived from."
    )
    description: str | None = Field(default=None, description="What the activity does.")
    inputs: list[str] = Field(default_factory=list, description="Named input parameters.")
    outputs: list[str] = Field(default_factory=list, description="Named outputs.")
    timeout_seconds: float | None = Field(
        default=None, description="Start-to-close timeout in seconds."
    )
    retry_policy: RetryPolicyDesign | None = Field(
        default=None, description="Retry policy for the activity."
    )


class TemporalSignalDesign(WorkflowBaseModel):
    """A Temporal signal handler design."""

    name: str = Field(..., description="Signal name.")
    description: str | None = Field(default=None, description="When/why the signal is sent.")
    payload: list[str] = Field(default_factory=list, description="Named payload fields.")


class TemporalQueryDesign(WorkflowBaseModel):
    """A Temporal query handler design."""

    name: str = Field(..., description="Query name.")
    description: str | None = Field(default=None, description="What state the query returns.")
    returns: str | None = Field(default=None, description="Return type or shape description.")


class TemporalTimerDesign(WorkflowBaseModel):
    """A Temporal timer / durable sleep design."""

    name: str = Field(..., description="Timer name.")
    duration_seconds: float = Field(..., gt=0, description="Timer duration in seconds.")
    description: str | None = Field(default=None, description="What the timer gates.")


class TemporalChildWorkflowDesign(WorkflowBaseModel):
    """A child workflow invoked by the parent workflow."""

    name: str = Field(..., description="Child workflow type name.")
    source_node_id: str | None = Field(
        default=None, description="Graph node (e.g. subprocess) this child was derived from."
    )
    description: str | None = Field(default=None, description="What the child workflow does.")
    inputs: list[str] = Field(default_factory=list, description="Named input parameters.")
    outputs: list[str] = Field(default_factory=list, description="Named outputs.")
    task_queue: str | None = Field(
        default=None, description="Recommended task queue for the child workflow."
    )


class TemporalCompensationDesign(WorkflowBaseModel):
    """A compensation (saga rollback) activity that undoes a prior activity."""

    name: str = Field(..., description="Compensation activity name.")
    compensates: str | None = Field(
        default=None, description="Name of the activity this compensation reverses."
    )
    source_node_id: str | None = Field(
        default=None, description="Graph node this compensation was derived from."
    )
    description: str | None = Field(
        default=None, description="What the compensation undoes and when it runs."
    )
    retry_policy: RetryPolicyDesign | None = Field(
        default=None, description="Retry policy for the compensation activity."
    )


class TemporalWorkflowDesign(WorkflowBaseModel):
    """A complete Temporal workflow blueprint."""

    workflow_name: str = Field(..., description="Temporal workflow type name.")
    task_queue: str | None = Field(default=None, description="Recommended task queue name.")
    description: str | None = Field(default=None, description="Workflow purpose.")
    activities: list[TemporalActivityDesign] = Field(
        default_factory=list, description="Activity designs."
    )
    signals: list[TemporalSignalDesign] = Field(
        default_factory=list, description="Signal handler designs."
    )
    queries: list[TemporalQueryDesign] = Field(
        default_factory=list, description="Query handler designs."
    )
    child_workflows: list[TemporalChildWorkflowDesign] = Field(
        default_factory=list, description="Child workflow designs."
    )
    timers: list[TemporalTimerDesign] = Field(default_factory=list, description="Timer designs.")
    compensation_activities: list[TemporalCompensationDesign] = Field(
        default_factory=list, description="Compensation (saga rollback) activity designs."
    )
    default_retry_policy: RetryPolicyDesign | None = Field(
        default=None, description="Workflow-wide default retry policy."
    )

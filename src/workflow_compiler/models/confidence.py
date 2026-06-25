"""Confidence score models."""

from __future__ import annotations

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class ConfidenceScores(WorkflowBaseModel):
    """Per-stage and overall confidence scores for a compiled workflow.

    Every score is in the range [0, 1]. ``None`` indicates a stage that has not
    produced a confidence estimate yet.
    """

    metadata: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in extracted metadata."
    )
    facts: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in extracted facts."
    )
    graph: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in the canonical graph."
    )
    cvpa: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in the CVPA classification."
    )
    temporal: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in the Temporal design."
    )
    overall: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Aggregate confidence across all stages."
    )
    notes: dict[str, str] = Field(
        default_factory=dict, description="Optional per-stage explanatory notes."
    )

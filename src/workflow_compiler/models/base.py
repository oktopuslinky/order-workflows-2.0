"""Shared Pydantic base model and common field helpers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WorkflowBaseModel(BaseModel):
    """Project-wide base model with strict, predictable configuration.

    All domain models inherit from this to share validation behavior:
    extra fields are forbidden, assignment is validated, and enum values are
    used on serialization.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
        str_strip_whitespace=True,
        frozen=False,
    )

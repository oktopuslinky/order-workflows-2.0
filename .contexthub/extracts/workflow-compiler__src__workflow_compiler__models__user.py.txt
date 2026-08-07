"""Local user accounts for the HTTP API.

Users are stored as JSON files (``storage/user_store.py``) exactly like
projects and workflow states — no database. The password is never stored:
only a scrypt hash plus its salt (see ``api/auth.py`` for the parameters).
The model is never serialized into API responses; ``api/schemas.py`` exposes
the ``UserPublic`` projection instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class UserPreferences(WorkflowBaseModel):
    """Per-user UI/metric preferences, persisted alongside the account.

    Kept small and additive: every field has a default so existing on-disk
    user JSON (which omits the whole block) keeps loading.
    """

    baseline_hours: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-user overrides of the org-wide time-saved baselines. Keys match "
            "the metric categories (discovery/spec/validate/compile/edit); only "
            "the keys present override, the rest inherit config defaults. Empty "
            "means use the config defaults entirely."
        ),
    )
    projects_page_size: int = Field(
        default=10,
        ge=1,
        le=200,
        description="How many projects to show per page in the Projects list.",
    )


class User(WorkflowBaseModel):
    """One local account (identity + project ownership on the HTTP surface)."""

    user_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable identifier; referenced by CompilationProject.owner_id.",
    )
    email: str = Field(..., description="Login email, stored lowercased; unique per store.")
    display_name: str = Field(..., description="Name shown in the UI and recorded as author.")
    password_hash: str = Field(..., description="Hex scrypt digest of the password.")
    password_salt: str = Field(..., description="Hex salt the digest was computed with.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Registration timestamp."
    )
    preferences: UserPreferences = Field(
        default_factory=UserPreferences,
        description="Per-user UI/metric preferences (page size, baseline overrides).",
    )

"""Request/response DTOs for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from workflow_compiler.metrics import TimeSavedReport
from workflow_compiler.models import (
    ChatTurnStatus,
    CompilationProject,
    DialogueQuestion,
    DialogueSession,
    EditRecord,
    GeneratedFile,
    ProjectStage,
    ResolvedEdit,
    SpecChatSession,
    SuggestedOption,
    WorkflowState,
)
from workflow_compiler.models.user import UserPreferences


class MetricsSummary(BaseModel):
    """Aggregate time-saved across the caller's projects (estimates, see metrics.py)."""

    projects: int = Field(default=0, description="Projects with measured timings.")
    total_baseline_hours: float = Field(default=0.0)
    total_actual_seconds: float = Field(default=0.0)
    total_saved_hours: float = Field(default=0.0)


class RegisterRequest(BaseModel):
    """Request body for creating a local account."""

    email: str = Field(..., min_length=3, description="Login email (stored lowercased).")
    password: str = Field(..., min_length=8, description="Password, at least 8 characters.")
    display_name: str = Field(
        default="", description="Name shown in the UI; defaults to the email's local part."
    )


class LoginRequest(BaseModel):
    """Request body for signing in."""

    email: str = Field(..., description="Login email.")
    password: str = Field(..., description="Password.")


class UserPublic(BaseModel):
    """The signed-in user, as exposed to the frontend (never the password hash)."""

    user_id: str = Field(...)
    email: str = Field(...)
    display_name: str = Field(...)
    preferences: UserPreferences = Field(
        default_factory=UserPreferences,
        description="Per-user UI/metric preferences (page size, baseline overrides).",
    )


class ProfileUpdateRequest(BaseModel):
    """Request body for updating the signed-in user's profile/preferences.

    Both fields are optional so a caller can update just the display name or
    just the preferences; omitted (``None``) fields are left unchanged.
    """

    display_name: str | None = Field(
        default=None, min_length=1, description="New display name (unchanged when omitted)."
    )
    preferences: UserPreferences | None = Field(
        default=None, description="Replacement preferences block (unchanged when omitted)."
    )


class SettingsDefaults(BaseModel):
    """Org-wide defaults, so the Settings UI can show 'default: X' and offer reset."""

    baseline_hours: dict[str, float] = Field(
        default_factory=dict,
        description="Config default human-team hours per metric category.",
    )
    projects_page_size: int = Field(
        default=10, description="Default projects-per-page when the user has not set one."
    )


class ApproveRequest(BaseModel):
    """Request body for approving a workflow graph."""

    workflow_id: str = Field(..., description="Id of the workflow to approve.")
    reviewer: str | None = Field(default=None, description="Reviewer identity.")


class RejectRequest(BaseModel):
    """Request body for rejecting a workflow graph."""

    workflow_id: str = Field(..., description="Id of the workflow to reject.")
    reviewer: str | None = Field(default=None, description="Reviewer identity.")
    reason: str | None = Field(default=None, description="Reason for rejection.")


class WorkflowStateResponse(BaseModel):
    """Response wrapper carrying a full workflow state."""

    state: WorkflowState


class WorkflowIdList(BaseModel):
    """Response listing stored workflow ids."""

    workflow_ids: list[str] = Field(default_factory=list)


class ProjectCompileRequest(BaseModel):
    """Request body for compiling a document into a spec project."""

    document_text: str = Field(..., description="The raw business workflow document.")
    persist: bool = Field(default=True, description="Persist the resulting project.")
    provider: str | None = Field(
        default=None,
        description="Optional LLM provider for this compile: 'local' (eGPU gateway "
        "only), 'nemotron' (hosted NVIDIA API), or 'local-fallback' (gateway with "
        "automatic Nemotron fallback). Defaults to the server's configured provider.",
    )
    model: str | None = Field(
        default=None,
        description="Optional local gateway model id for this compile (else the server default).",
    )
    nickname: str | None = Field(
        default=None, description="Optional human-friendly label for the new project."
    )


class LocalModel(BaseModel):
    """One model the gateway advertises, with its probed health if known."""

    id: str = Field(..., description="Model id to pass as `model`.")
    available: bool | None = Field(
        default=None,
        description="True/False once probed; None when health was not checked.",
    )
    detail: str | None = Field(
        default=None, description="Why the model is unavailable, when it is."
    )


class LocalModelList(BaseModel):
    """Response listing the models the local eGPU gateway exposes.

    The gateway advertises every configured model whether or not its inference
    server is actually up, so an id appearing here is not a promise that it
    serves. ``entries`` carries the health verdict when ``probe=true`` was asked
    for; ``models`` stays the plain advertised list it has always been.
    """

    models: list[str] = Field(default_factory=list)
    entries: list[LocalModel] = Field(default_factory=list)
    probed: bool = Field(
        default=False, description="Whether health was actually checked."
    )


class SpecUpdateRequest(BaseModel):
    """Edited spec file contents keyed by workflow slug."""

    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → edited spec Markdown."
    )


class ProjectEditRequest(BaseModel):
    """Request body for applying a workflow edit-request document."""

    edit_document: str = Field(
        ..., description="The edit-request Markdown (see docs/EDIT_FORMAT_GUIDE.md)."
    )
    workflows: list[str] | None = Field(
        default=None, description="Restrict edits to these slugs (default: any)."
    )
    author: str | None = Field(
        default=None, description="Author recorded in the project's edit log."
    )
    resolved: ResolvedEdit | None = Field(
        default=None,
        description=(
            "Preview handoff from POST /projects/{id}/edit/preview — apply exactly "
            "those interpreted operations with no LLM re-interpretation. A stale "
            "blob (the project changed since the preview) answers 409."
        ),
    )


class EditPreviewResponse(BaseModel):
    """A previewed edit: what would change, without persisting anything."""

    record: EditRecord = Field(
        ..., description="The would-be audit entry (summary, patches, wiring ops)."
    )
    resolved: ResolvedEdit = Field(
        ..., description="Replayable interpretation — send back on confirm."
    )
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → post-edit rendered spec Markdown."
    )
    workflows_added: list[str] = Field(default_factory=list)
    workflows_removed: list[str] = Field(default_factory=list)


class ProjectApproveRequest(BaseModel):
    """Request body for approving a project's specs."""

    workflows: list[str] | None = Field(
        default=None, description="Slugs to approve (default: all)."
    )
    reviewer: str | None = Field(default=None, description="Reviewer identity.")
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="Final edited spec Markdown by slug."
    )
    accept_incomplete: bool = Field(
        default=False, description="Proceed despite unanswered required questions."
    )
    allow_unconfirmed_references: bool = Field(
        default=False, description="Proceed without confirming cross-workflow links."
    )


class ProjectResponse(BaseModel):
    """Response wrapper carrying a project plus its rendered spec files."""

    project: CompilationProject
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → rendered spec Markdown."
    )
    time_saved: TimeSavedReport | None = Field(
        default=None,
        description=(
            "Measured pipeline time vs. estimated human-team hours (None when "
            "nothing was measured). Baselines are configurable estimates."
        ),
    )
    diagrams: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "slug → structural Mermaid diagram source, built deterministically from "
            "the current specs (a preview of the graph approval will build)."
        ),
    )


class JobStartRequest(BaseModel):
    """Request body for starting a background run (validate or approve).

    Carries the union of both stages' parameters; the approve-only knobs are
    ignored for a ``validate`` job."""

    kind: Literal["validate", "approve"] = Field(
        ..., description="Which stage to run in the background."
    )
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="Edited spec Markdown by slug (folded in first)."
    )
    workflows: list[str] | None = Field(
        default=None, description="approve: slugs to approve (default: all)."
    )
    reviewer: str | None = Field(
        default=None, description="approve: reviewer identity (default: signed-in user)."
    )
    accept_incomplete: bool = Field(
        default=False, description="approve: proceed despite unanswered required questions."
    )
    allow_unconfirmed_references: bool = Field(
        default=False, description="approve: proceed without confirming cross-workflow links."
    )


class JobResponse(BaseModel):
    """A background run's status. ``project`` is embedded only when the run has
    succeeded, so a single ``GET /jobs/{id}`` yields the finished result."""

    job_id: str
    project_id: str
    kind: str
    status: str = Field(
        ..., description="running | succeeded | failed | canceled."
    )
    error: str | None = Field(default=None, description="Failure message when status is failed.")
    created_at: datetime
    updated_at: datetime
    project: ProjectResponse | None = Field(
        default=None, description="The finished project — present only when status is succeeded."
    )


class CvpaPreviewRequest(BaseModel):
    """Request body for an on-demand CVPA phase-coloring preview."""

    workflow: str = Field(..., description="Slug of the workflow to classify.")


class CvpaPreviewResponse(BaseModel):
    """A single workflow's CVPA phase-colored Mermaid diagram (display-only)."""

    slug: str = Field(..., description="Slug of the classified workflow.")
    diagram: str = Field(..., description="CVPA phase-colored Mermaid diagram source.")


class ProjectIdList(BaseModel):
    """Response listing stored project ids."""

    project_ids: list[str] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    """Lightweight project row for the Projects list — enough to label, search, sort."""

    project_id: str = Field(..., description="Stable project identifier.")
    nickname: str | None = Field(
        default=None, description="Human-friendly label (None until named)."
    )
    stage: ProjectStage = Field(..., description="Current project stage.")
    workflow_count: int = Field(
        default=0, description="Number of discovered workflows (specs) in the project."
    )
    updated_at: datetime = Field(..., description="Last mutation timestamp.")


class RenameProjectRequest(BaseModel):
    """Request body for setting or clearing a project's nickname."""

    nickname: str | None = Field(
        default=None, description="New nickname; null or empty clears it."
    )


class ProjectListResponse(BaseModel):
    """Response listing visible projects as summaries (newest first)."""

    projects: list[ProjectSummary] = Field(default_factory=list)


class ProjectFilesResponse(BaseModel):
    """Flat, directory-prefixed file tree for a compiled project (ready to zip)."""

    project_id: str = Field(..., description="Id of the project the files belong to.")
    files: list[GeneratedFile] = Field(
        default_factory=list,
        description=(
            "Every generated file: each workflow's bundle under '<slug>/...' plus the "
            "shared project glue files (contracts.py, README.md) at the root."
        ),
    )


class DialogueAnswerRequest(BaseModel):
    """Request body for answering the dialogue's current question."""

    answer: str = Field(
        ...,
        min_length=1,
        description="The user's answer, in ordinary prose — no particular format.",
    )
    option: str | None = Field(
        default=None,
        description=(
            "Label of the suggested option the user accepted verbatim, when they took "
            "one instead of writing their own. Recorded for the audit trail only: the "
            "answer is interpreted the same way either way, and a label that was not "
            "actually offered is ignored."
        ),
    )


class SpecChatRequest(BaseModel):
    """Request body for one free-form spec-editing instruction."""

    message: str = Field(
        ...,
        min_length=1,
        description="What the user wants changed, in ordinary prose.",
    )
    slug: str | None = Field(
        default=None,
        description=(
            "Workflow the instruction concerns. Send the one the user is looking "
            "at; omit to let the interpreter choose. An unknown slug is rejected "
            "rather than silently redirected."
        ),
    )
    option: str | None = Field(
        default=None,
        description=(
            "Label of the suggested reply the user accepted verbatim, when answering "
            "a clarifying question by picking rather than typing. Recorded for the "
            "audit trail only; a label that was not offered is ignored."
        ),
    )


class SpecChatResponse(BaseModel):
    """The chat's state after an operation, plus what the last message did.

    ``session`` is ``None`` once the chat has been closed. As with the guided
    dialogue, everything the last message changed is reported explicitly — a
    client should never have to diff the specs to find out whether it took.
    """

    project: CompilationProject
    session: SpecChatSession | None = Field(
        default=None, description="The open chat, or None once it has been closed."
    )
    reply: str | None = Field(
        default=None, description="Plain-language reply to show the user."
    )
    status: ChatTurnStatus | None = Field(
        default=None, description="How the last message was disposed of."
    )
    slug: str | None = Field(
        default=None, description="Workflow the last message was read against."
    )
    changes: list[str] = Field(
        default_factory=list, description="What the last message changed in the spec."
    )
    parked_as: str | None = Field(
        default=None,
        description="Set when the last message was recorded as a new open question.",
    )
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal issues from applying the last message."
    )
    options: list[SuggestedOption] = Field(
        default_factory=list,
        description=(
            "Candidate replies to the open clarifying question. Empty unless one is "
            "awaiting an answer; the free-text box is always the real interface."
        ),
    )
    awaiting_clarification: bool = Field(
        default=False,
        description="True when the next message will be read as a reply to a question.",
    )
    applied: int = Field(
        default=0, description="How many instructions have changed the specs."
    )
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → rendered spec Markdown (kept in step)."
    )


class DialogueResponse(BaseModel):
    """The dialogue's state after an operation, plus what the last answer did.

    ``session`` is ``None`` once the session has been ended, which is how the
    client knows to leave the panel. Everything the last answer changed is
    reported explicitly — a client should never have to diff the specs to find
    out whether an answer took effect.
    """

    project: CompilationProject
    session: DialogueSession | None = Field(
        default=None, description="The open session, or None once it has been closed."
    )
    question: DialogueQuestion | None = Field(
        default=None, description="The question now awaiting an answer, if any."
    )
    prompt: str | None = Field(
        default=None,
        description=(
            "Exact text to show the user: the pending clarifying follow-up when "
            "one is open, else the current question."
        ),
    )
    options: list[SuggestedOption] = Field(
        default_factory=list,
        description=(
            "Candidate answers belonging to ``prompt`` — the follow-up's when one is "
            "open, else the question's. Often empty; the free-text box is always the "
            "real interface."
        ),
    )
    prepared: bool = Field(
        default=False,
        description=(
            "True when questions are already drafted and waiting, so starting a "
            "session is instant."
        ),
    )
    preparing: bool = Field(
        default=False,
        description=(
            "True when a background drafting run is in flight for this project. The "
            "client should say so and poll rather than showing an empty panel."
        ),
    )
    answered: int = Field(
        default=0, description="How many questions have produced applied spec changes."
    )
    total: int = Field(default=0, description="Questions on the agenda.")
    remaining: int = Field(default=0, description="Questions not yet dispositioned.")
    changes: list[str] = Field(
        default_factory=list, description="What the last answer changed in the spec."
    )
    parked_as: str | None = Field(
        default=None,
        description="Set when the last answer was recorded as a new open question.",
    )
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal issues from applying the last answer."
    )
    spec_markdown: dict[str, str] = Field(
        default_factory=dict, description="slug → rendered spec Markdown (kept in step)."
    )

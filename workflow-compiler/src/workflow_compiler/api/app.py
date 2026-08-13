"""FastAPI application exposing the workflow compiler.

Project endpoints (the compile → validate → approve pipeline):

- ``POST /projects/compile``        — segment a document into reviewed specs.
- ``GET  /projects``                — list visible projects as summaries.
- ``GET  /projects/{id}``           — load a project + rendered spec files.
- ``PATCH /projects/{id}``          — set/clear a project nickname (metadata only).
- ``PUT  /projects/{id}/spec``      — fold edited spec Markdown back in (no LLM).
- ``POST /projects/{id}/edit``      — apply an edit-request document, re-arm the gate.
- ``POST /projects/{id}/validate``  — run the spec validator passes.
- ``POST /projects/{id}/approve``   — approve specs, compile every workflow.

Conversational spec resolution — the alternative to hand-editing spec Markdown.
The validator's blocking/warning findings and the specs' unresolved open
questions become plain-language questions; answers are prose and are applied
**incrementally** (one spec patch set and version bump per answered question):

- ``GET    /projects/{id}/dialogue``        — the open session, if any.
- ``POST   /projects/{id}/dialogue``        — open a session (400 if nothing to ask).
- ``POST   /projects/{id}/dialogue/answer`` — answer the current question in prose.
- ``POST   /projects/{id}/dialogue/skip``   — pass, leaving the spec untouched.
- ``DELETE /projects/{id}/dialogue``        — close it; applied answers stay applied.

Long stages can also run in the background so they can be canceled and survive
the user navigating away (one run per project at a time, unlimited across
projects; canceling never persists a partial result):

- ``POST /projects/{id}/jobs``      — start validate/approve as a background run.
- ``GET  /jobs``                    — list the caller's runs (``?project_id=``).
- ``GET  /jobs/{job_id}``           — one run's status (+ project when done).
- ``POST /jobs/{job_id}/cancel``    — cancel a run, leaving the project untouched.

Per-workflow endpoints (viewing plus the manual override for workflows whose
graph health fell below the auto-approve threshold):

- ``POST /approve``           — approve a graph and run downstream artifacts.
- ``POST /reject``            — reject a graph.
- ``GET  /workflow/{id}``     — load a stored workflow state.
- ``GET  /workflows``         — list stored workflow ids.
- ``GET  /health``            — liveness probe.

Auth (local accounts; see ``api/auth.py``): ``POST /auth/register``,
``POST /auth/login``, ``POST /auth/logout``, ``GET /auth/me``,
``PUT /auth/me`` (display name + preferences). ``GET /settings/defaults``
exposes the org-wide baseline estimates so the Settings UI can offer reset.
Every project
and workflow endpoint requires a signed-in session. Projects carry an
``owner_id`` (recorded for attribution — who created/edits each workflow). By
default (``projects_shared``) every signed-in user can see and open every
project; set ``WORKFLOW_COMPILER_PROJECTS_SHARED=false`` to restore per-owner
isolation, where other users' projects answer 404 and only legacy unowned
projects (``owner_id`` is None, e.g. CLI-created) stay visible to everyone.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from workflow_compiler import __version__
from workflow_compiler.api.auth import (
    clear_session_cookie,
    get_current_user,
    get_user_store,
    hash_password,
    set_session_cookie,
    verify_password,
)
from workflow_compiler.api.dependencies import (
    SELECTABLE_PROVIDERS,
    get_compiler,
    get_executor,
    get_local_provider,
    get_project_compiler,
    project_compiler_for_model,
    project_compiler_for_selection,
)
from workflow_compiler.api.jobs import Job, JobConflictError, JobManager
from workflow_compiler.api.schemas import (
    ApproveRequest,
    CvpaPreviewRequest,
    CvpaPreviewResponse,
    DialogueAnswerRequest,
    DialogueResponse,
    EditPreviewResponse,
    JobResponse,
    JobStartRequest,
    LocalModel,
    LocalModelList,
    LoginRequest,
    MetricsSummary,
    ProfileUpdateRequest,
    ProjectApproveRequest,
    ProjectCompileRequest,
    ProjectEditRequest,
    ProjectFilesResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectSummary,
    RegisterRequest,
    RejectRequest,
    RenameProjectRequest,
    RunEventSchema,
    RunnableListResponse,
    RunnableWorkflowSchema,
    RunResponse,
    SettingsDefaults,
    SignalRunRequest,
    SignalSchema,
    SpecChatRequest,
    SpecChatResponse,
    SpecUpdateRequest,
    StartRunRequest,
    TemporalHealth,
    UserPublic,
    WorkflowIdList,
    WorkflowInputFieldSchema,
    WorkflowStateResponse,
)
from workflow_compiler.codegen.temporal.project_generator import generate_project_files
from workflow_compiler.compiler import WorkflowCompiler
from workflow_compiler.config import get_settings
from workflow_compiler.dialogue import (
    AnswerOutcome,
    ChatOutcome,
    has_anything_to_ask,
    prepared_agenda_is_fresh,
)
from workflow_compiler.exceptions import (
    ApprovalError,
    CompilationError,
    EditPreviewStaleError,
    LLMProviderError,
    ProviderConnectionError,
    ProviderTimeoutError,
    StateNotFoundError,
    UnsupportedFormatError,
    WorkflowCompilerError,
)
from workflow_compiler.execution import (
    Run,
    RunRegistry,
    bundle_dir,
    describe_runnable,
    is_materialized,
    materialize_bundle,
)
from workflow_compiler.ingestion import DocumentParserFactory
from workflow_compiler.interfaces.executor import (
    ExecutorUnavailableError,
    RunNotFoundError,
    RunStatus,
    WorkflowExecutor,
)
from workflow_compiler.llm.types import ChatMessage
from workflow_compiler.metrics import compute_time_saved
from workflow_compiler.models import (
    CompilationProject,
    DialogueSession,
    GeneratedFile,
    SpecChatSession,
    TemporalWorkflowDesign,
    WorkflowState,
)
from workflow_compiler.models.user import User
from workflow_compiler.project_compiler import ProjectCompiler
from workflow_compiler.spec import render_spec
from workflow_compiler.storage.user_store import UserStore

logger = logging.getLogger(__name__)

#: Per-model deadline for a health probe. Generous enough that a cold but live
#: model still answers a one-token request, short enough that four dead ones do
#: not hold the picker open — they fail fast with HTTP 502 anyway.
_PROBE_TIMEOUT = 30.0


def _check_owner(project: CompilationProject, user: User) -> None:
    """404 for another account's project — don't leak that the id exists.

    No-op when ``projects_shared`` is set (the default): every signed-in user
    may open every project. ``owner_id`` is still recorded for attribution.
    """
    if get_settings().projects_shared:
        return
    if project.owner_id is not None and project.owner_id != user.user_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No project with id {project.project_id!r}."
        )


def _public(user: User) -> UserPublic:
    return UserPublic(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        preferences=user.preferences,
    )


def _effective_baselines(user: User | None) -> dict[str, float]:
    """Merge the caller's per-user baseline overrides over the org-wide defaults.

    Only the categories the user set override; the rest inherit the config
    estimates. ``None`` (no signed-in user) returns the config defaults.
    """
    defaults = get_settings().baseline_hours
    if user is None:
        return defaults
    return {**defaults, **user.preferences.baseline_hours}


def _project_summary(project: CompilationProject) -> ProjectSummary:
    """Project a full project onto the lightweight list row."""
    return ProjectSummary(
        project_id=project.project_id,
        nickname=project.nickname,
        stage=project.stage,
        workflow_count=len(project.specs),
        updated_at=project.updated_at,
    )


async def _guard[T](coro: Awaitable[T]) -> T:
    """Run a compiler coroutine, mapping domain errors to HTTP responses."""
    try:
        return await coro
    except StateNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (ApprovalError, EditPreviewStaleError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except CompilationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    # The upstream model failing is not this server failing. A dead gateway
    # model, an expired key or an unparseable completion are all bad-gateway
    # conditions: 5xx-but-not-ours, and retryable by the caller. Reported as 500
    # they read as a compiler bug and send debugging in the wrong direction.
    except ProviderTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except WorkflowCompilerError as exc:  # pragma: no cover - defensive catch-all
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


async def _run_guard[T](coro: Awaitable[T]) -> T:
    """Map execution failures onto HTTP statuses.

    A missing SDK or an unreachable server is **503**, not 500: it is a
    precondition of the deployment, not a bug in the request. The UI normally
    prevents ever reaching this by disabling the control (§5.4), but a server
    that dies between the health check and the click must still say why.
    """
    try:
        return await coro
    except ExecutorUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _status_query_for(state: WorkflowState) -> str | None:
    """A query that reports the workflow's own disposition, if it declares one.

    Needed because a compensating saga ends *failed* on the server — the
    generated ``workflow.py`` sets ``self._status = "compensated"`` and re-raises
    — so a clean rollback and a genuine crash are indistinguishable without
    asking the workflow. Prefers a query that names itself a status; falls back
    to any string-returning query. ``None`` when there is none, in which case a
    compensated run honestly reads as failed rather than being guessed at.
    """
    design = state.temporal_design
    if design is None or not design.queries:
        return None
    string_queries = [q for q in design.queries if (q.returns or "str").strip() == "str"]
    if not string_queries:
        return None
    named = next((q for q in string_queries if "status" in q.name.lower()), None)
    return (named or string_queries[0]).name


def _run_response(
    run: Run,
    status: RunStatus,
    *,
    written: list[str] | None = None,
    kept: list[str] | None = None,
) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        project_id=run.project_id,
        slug=run.slug,
        workflow_id=run.workflow_id,
        execution_run_id=status.run_id or run.execution_run_id,
        task_queue=run.task_queue,
        state=status.state,
        result=status.result,
        error=status.error,
        current_step=status.current_step,
        events=[
            RunEventSchema(at=event.at, kind=event.kind, detail=event.detail)
            for event in status.events
        ],
        created_at=run.created_at,
        bundle_written=written or [],
        bundle_kept=kept or [],
    )


def _cached_run_response(run: Run) -> RunResponse:
    """The last observed state, without calling Temporal.

    Used by the list endpoint so opening the Results tab costs one round trip
    rather than one per run.
    """
    return RunResponse(
        run_id=run.run_id,
        project_id=run.project_id,
        slug=run.slug,
        workflow_id=run.workflow_id,
        execution_run_id=run.execution_run_id,
        task_queue=run.task_queue,
        state=run.last_state,
        created_at=run.created_at,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Reap bundle worker subprocesses so they do not outlive the API.

    The pool deliberately keeps workers alive across requests (a workflow parked
    on a 24-hour timer needs one), so nothing else would ever stop them.
    """
    yield
    await get_executor().shutdown()


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="workflow-compiler",
        version=__version__,
        description="Compile business workflow documents into canonical artifacts.",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        # Accept any localhost / 127.0.0.1 dev port (the two are interchangeable
        # in the address bar but not to CORS). Starlette echoes the matched
        # origin, so this stays compatible with allow_credentials=True.
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Background-run registry (validate/approve). One instance per app so tests
    # that rebuild the app start clean; a run is an asyncio.Task that outlives
    # the request, and cancelling one never persists a partial result.
    jobs = JobManager()

    # Executions started from the Results tab. In memory like `jobs`, and for a
    # stronger reason: Temporal is the durable record, so a restart loses only
    # the project/slug mapping, never the run itself.
    runs = RunRegistry()

    @app.get("/health", tags=["meta"])
    async def health(
        executor: WorkflowExecutor = Depends(get_executor),
    ) -> dict[str, object]:
        """Liveness probe, plus whether generated bundles can be run.

        The Temporal block is what lets the UI disable its Run control with a
        reason instead of failing on click (§5.4).
        """
        reachability = await executor.health()
        return {
            "status": "ok",
            "version": __version__,
            "temporal": {
                "reachable": reachability.reachable,
                "address": reachability.address,
                "detail": reachability.detail,
            },
        }


    @app.post("/auth/register", response_model=UserPublic, tags=["auth"])
    async def register(
        request: RegisterRequest,
        response: Response,
        store: UserStore = Depends(get_user_store),
    ) -> UserPublic:
        """Create a local account and sign it in."""
        email = request.email.strip().lower()
        if "@" not in email:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Enter a valid email address."
            )
        if await store.get_by_email(email) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "An account with this email already exists."
            )
        password_hash, password_salt = hash_password(request.password)
        user = User(
            email=email,
            display_name=request.display_name.strip() or email.split("@", 1)[0],
            password_hash=password_hash,
            password_salt=password_salt,
        )
        await store.save(user)
        set_session_cookie(response, user)
        return _public(user)

    @app.post("/auth/login", response_model=UserPublic, tags=["auth"])
    async def login(
        request: LoginRequest,
        response: Response,
        store: UserStore = Depends(get_user_store),
    ) -> UserPublic:
        """Sign in with email + password; sets the session cookie."""
        user = await store.get_by_email(request.email.strip().lower())
        # One generic message for both failure modes — don't reveal which.
        if user is None or not verify_password(
            request.password, user.password_hash, user.password_salt
        ):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Invalid email or password."
            )
        set_session_cookie(response, user)
        return _public(user)

    @app.post("/auth/logout", tags=["auth"])
    async def logout(response: Response) -> dict[str, str]:
        """Sign out (clears the session cookie)."""
        clear_session_cookie(response)
        return {"status": "signed out"}

    @app.get("/auth/me", response_model=UserPublic, tags=["auth"])
    async def me(user: User = Depends(get_current_user)) -> UserPublic:
        """Return the signed-in user (401 when there is no valid session)."""
        return _public(user)

    @app.put("/auth/me", response_model=UserPublic, tags=["auth"])
    async def update_me(
        request: ProfileUpdateRequest,
        user: User = Depends(get_current_user),
        store: UserStore = Depends(get_user_store),
    ) -> UserPublic:
        """Update the signed-in user's display name and/or preferences.

        Omitted fields are left unchanged; preferences (page size + baseline
        overrides) are replaced wholesale when provided.
        """
        if request.display_name is not None:
            user.display_name = request.display_name.strip()
        if request.preferences is not None:
            user.preferences = request.preferences
        await store.save(user)
        return _public(user)

    @app.get("/settings/defaults", response_model=SettingsDefaults, tags=["meta"])
    async def settings_defaults(
        user: User = Depends(get_current_user),
    ) -> SettingsDefaults:
        """Org-wide defaults powering the Settings UI (show 'default: X' + reset)."""
        return SettingsDefaults(baseline_hours=dict(get_settings().baseline_hours))

    @app.get("/providers/local/models", response_model=LocalModelList, tags=["providers"])
    async def local_models(probe: bool = False) -> LocalModelList:
        """List the models the local eGPU gateway currently exposes (for the picker).

        The gateway advertises every configured model regardless of whether its
        inference server is up, so the picker can otherwise offer models that
        answer every request with HTTP 502. ``probe=true`` checks each one.

        Probing is opt-in and **serial** on purpose: the eGPU is a single card
        with no request queueing, so parallel probes — or probes fired
        automatically on page load — inflate latency for anything else in flight
        and can time out a running compile.
        """
        provider = get_local_provider()
        try:
            ids = await provider.list_models()  # type: ignore[attr-defined]
        except ProviderTimeoutError as exc:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc
        except ProviderConnectionError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        finally:
            await provider.aclose()  # type: ignore[attr-defined]

        if not probe:
            return LocalModelList(
                models=ids, entries=[LocalModel(id=i) for i in ids], probed=False
            )

        entries: list[LocalModel] = []
        for model_id in ids:
            checked = get_local_provider(model=model_id, timeout=_PROBE_TIMEOUT)
            try:
                await checked.chat(  # type: ignore[attr-defined]
                    [ChatMessage.user("ping")], max_tokens=1
                )
                entries.append(LocalModel(id=model_id, available=True))
            except LLMProviderError as exc:
                entries.append(
                    LocalModel(id=model_id, available=False, detail=str(exc)[:200])
                )
            finally:
                await checked.aclose()  # type: ignore[attr-defined]
        return LocalModelList(models=ids, entries=entries, probed=True)

    @app.post("/approve", response_model=WorkflowStateResponse, tags=["workflows"])
    async def approve_workflow(
        request: ApproveRequest,
        compiler: WorkflowCompiler = Depends(get_compiler),
        user: User = Depends(get_current_user),
    ) -> WorkflowStateResponse:
        """Approve a generated graph and produce CVPA + Temporal artifacts."""
        state = await _guard(
            compiler.approve_graph(
                request.workflow_id, reviewer=request.reviewer or user.display_name
            )
        )
        return WorkflowStateResponse(state=state)

    @app.post("/reject", response_model=WorkflowStateResponse, tags=["workflows"])
    async def reject_workflow(
        request: RejectRequest,
        compiler: WorkflowCompiler = Depends(get_compiler),
        user: User = Depends(get_current_user),
    ) -> WorkflowStateResponse:
        """Reject a generated workflow graph."""
        state = await _guard(
            compiler.reject_graph(
                request.workflow_id,
                reviewer=request.reviewer or user.display_name,
                reason=request.reason,
            )
        )
        return WorkflowStateResponse(state=state)

    @app.get("/workflow/{workflow_id}", response_model=WorkflowStateResponse, tags=["workflows"])
    async def get_workflow(
        workflow_id: str,
        compiler: WorkflowCompiler = Depends(get_compiler),
        user: User = Depends(get_current_user),
    ) -> WorkflowStateResponse:
        """Load a stored workflow state by id."""
        state = await _guard(compiler.load_state(workflow_id))
        return WorkflowStateResponse(state=state)

    @app.get("/workflows", response_model=WorkflowIdList, tags=["workflows"])
    async def list_workflows(
        compiler: WorkflowCompiler = Depends(get_compiler),
        user: User = Depends(get_current_user),
    ) -> WorkflowIdList:
        """List stored workflow ids."""
        ids = await _guard(compiler.list_states())
        return WorkflowIdList(workflow_ids=ids)

    async def _project_response(
        project: CompilationProject,
        compiler: ProjectCompiler,
        user: User | None = None,
    ) -> ProjectResponse:
        """Wrap a project with its rendered spec Markdown and structural diagrams.

        ``user`` supplies per-user baseline overrides for the time-saved figure;
        when omitted the org-wide config defaults are used.
        """
        return ProjectResponse(
            project=project,
            spec_markdown={
                spec.slug: render_spec(spec, project.cross_references, project.triggers)
                for spec in project.specs
            },
            time_saved=compute_time_saved(project, _effective_baselines(user)),
            diagrams=await compiler.build_diagrams(project),
        )

    def _select_compiler(
        provider: str | None, model: str | None, default: ProjectCompiler
    ) -> ProjectCompiler:
        """Resolve the per-compile provider/model selection to a compiler.

        An explicit ``provider`` wins; a bare ``model`` keeps the legacy sentinel
        routing (``nemotron-cloud`` vs. local-with-fallback); neither uses the
        server's configured default.
        """
        if provider:
            if provider not in SELECTABLE_PROVIDERS:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Unknown provider '{provider}'. "
                    f"Available: {', '.join(SELECTABLE_PROVIDERS)}.",
                )
            return project_compiler_for_selection(provider, model)
        if model:
            return project_compiler_for_model(model)
        return default

    @app.post("/projects/compile", response_model=ProjectResponse, tags=["projects"])
    async def compile_project(
        request: ProjectCompileRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Segment a document into per-workflow specs (stops at the spec gate)."""
        compiler = _select_compiler(request.provider, request.model, compiler)
        project = await _guard(
            compiler.compile_document(request.document_text, persist=request.persist)
        )
        project.owner_id = user.user_id
        if request.nickname and request.nickname.strip():
            project.nickname = request.nickname.strip()
        if request.persist:
            await compiler.save_project(project)
        return await _project_response(project, compiler, user)

    @app.post(
        "/projects/compile-upload", response_model=ProjectResponse, tags=["projects"]
    )
    async def compile_project_upload(
        file: UploadFile = File(..., description="A .docx/.pdf/.md/.html/.txt document."),
        persist: bool = Form(default=True),
        provider: str | None = Form(default=None),
        model: str | None = Form(default=None),
        nickname: str | None = Form(default=None),
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Parse an uploaded document to text, then segment it into per-workflow specs."""
        data = await file.read()
        try:
            content = DocumentParserFactory().parse(
                data, filename=file.filename, content_type=file.content_type
            )
        except UnsupportedFormatError as exc:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
        except WorkflowCompilerError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        compiler = _select_compiler(provider, model, compiler)
        project = await _guard(compiler.compile_document(content.text, persist=persist))
        project.owner_id = user.user_id
        if nickname and nickname.strip():
            project.nickname = nickname.strip()
        if persist:
            await compiler.save_project(project)
        return await _project_response(project, compiler, user)

    @app.get("/metrics/summary", response_model=MetricsSummary, tags=["projects"])
    async def metrics_summary(
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> MetricsSummary:
        """Aggregate time saved across the caller's (and legacy) projects.

        Baselines are configurable estimates (``baseline_hours``), not
        measurements; only projects with recorded timings are counted.
        """
        summary = MetricsSummary()
        shared = get_settings().projects_shared
        for project_id in await _guard(compiler.list_projects()):
            try:
                project = await compiler.load_project(project_id)
            except (StateNotFoundError, ValidationError):
                # One corrupt/legacy project file must not take down the whole
                # metrics page; per-project endpoints still surface the error.
                logger.warning(
                    "Skipping unloadable project %r in metrics summary", project_id
                )
                continue
            if not shared and project.owner_id not in (None, user.user_id):
                continue
            report = compute_time_saved(project, _effective_baselines(user))
            if report is None:
                continue
            summary.projects += 1
            summary.total_baseline_hours += report.total_baseline_hours
            summary.total_actual_seconds += report.total_actual_seconds
            summary.total_saved_hours += report.total_saved_hours
        return summary

    @app.get("/projects", response_model=ProjectListResponse, tags=["projects"])
    async def list_projects(
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectListResponse:
        """List visible projects as summaries (newest first).

        With ``projects_shared`` (the default) every stored project is listed;
        otherwise the caller's own projects plus unowned legacy ones. Each
        project is loaded to project its label/stage/timestamp for the UI;
        unloadable files are skipped (per-project endpoints still surface the
        error).
        """
        shared = get_settings().projects_shared
        summaries: list[ProjectSummary] = []
        for project_id in await _guard(compiler.list_projects()):
            try:
                project = await compiler.load_project(project_id)
            except (StateNotFoundError, ValidationError):
                logger.warning(
                    "Skipping unloadable project %r in project listing", project_id
                )
                continue
            if not shared and project.owner_id not in (None, user.user_id):
                continue
            summaries.append(_project_summary(project))
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return ProjectListResponse(projects=summaries)

    @app.get("/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
    async def get_project(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Load a stored project plus its rendered spec files."""
        project = await _guard(compiler.load_project(project_id))
        _check_owner(project, user)
        return await _project_response(project, compiler, user)

    @app.patch(
        "/projects/{project_id}", response_model=ProjectSummary, tags=["projects"]
    )
    async def rename_project(
        project_id: str,
        request: RenameProjectRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectSummary:
        """Set or clear a project's nickname (a cheap metadata update — no recompile)."""
        project = await _guard(compiler.load_project(project_id))
        _check_owner(project, user)
        nickname = (request.nickname or "").strip()
        project.nickname = nickname or None
        project.touch()
        await compiler.save_project(project)
        return _project_summary(project)

    @app.get(
        "/projects/{project_id}/files", response_model=ProjectFilesResponse, tags=["projects"]
    )
    async def get_project_files(
        project_id: str,
        project_compiler: ProjectCompiler = Depends(get_project_compiler),
        compiler: WorkflowCompiler = Depends(get_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectFilesResponse:
        """Assemble every compiled workflow's bundle plus shared glue files (zip-ready)."""
        project = await _guard(project_compiler.load_project(project_id))
        _check_owner(project, user)
        files: list[GeneratedFile] = []
        designs: dict[str, TemporalWorkflowDesign] = {}
        for slug, workflow_id in project.workflow_ids.items():
            state = await _guard(compiler.load_state(workflow_id))
            if state.temporal_design is not None:
                designs[slug] = state.temporal_design
            if state.temporal_code is not None:
                files.extend(
                    GeneratedFile(
                        path=f"{slug}/{generated.path}",
                        language=generated.language,
                        content=generated.content,
                    )
                    for generated in state.temporal_code.files
                )
        if designs:
            files.extend(generate_project_files(designs, project.triggers))
        return ProjectFilesResponse(project_id=project.project_id, files=files)

    @app.put("/projects/{project_id}/spec", response_model=ProjectResponse, tags=["projects"])
    async def update_project_spec(
        project_id: str,
        request: SpecUpdateRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Fold edited spec Markdown back onto the structured specs (no LLM)."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project = await _guard(
            compiler.update_specs(project_id, request.spec_markdown)
        )
        return await _project_response(project, compiler, user)

    @app.post(
        "/projects/{project_id}/edit", response_model=ProjectResponse, tags=["projects"]
    )
    async def edit_project(
        project_id: str,
        request: ProjectEditRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Apply a workflow edit-request document; the project re-enters the spec gate."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project = await _guard(
            compiler.edit_specs(
                project_id,
                request.edit_document,
                workflows=request.workflows,
                author=request.author or user.display_name,
                resolved=request.resolved,
            )
        )
        return await _project_response(project, compiler, user)

    @app.post(
        "/projects/{project_id}/edit/preview",
        response_model=EditPreviewResponse,
        tags=["projects"],
    )
    async def preview_project_edit(
        project_id: str,
        request: ProjectEditRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> EditPreviewResponse:
        """Dry-run an edit request: interpret and apply on a copy, persist nothing.

        The response carries the would-be summary/diff plus the ``resolved``
        blob; POST the same document with that blob to ``/edit`` to apply it
        exactly as previewed (no LLM re-interpretation).
        """
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        preview = await _guard(
            compiler.preview_edit(
                project_id,
                request.edit_document,
                workflows=request.workflows,
                author=request.author or user.display_name,
            )
        )
        return EditPreviewResponse(
            record=preview.record,
            resolved=preview.resolved,
            spec_markdown={
                spec.slug: render_spec(
                    spec, preview.project.cross_references, preview.project.triggers
                )
                for spec in preview.project.specs
            },
            workflows_added=preview.record.workflows_added,
            workflows_removed=preview.record.workflows_removed,
        )

    @app.post(
        "/projects/{project_id}/validate", response_model=ProjectResponse, tags=["projects"]
    )
    async def validate_project(
        project_id: str,
        request: SpecUpdateRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Ingest edits (if any) and run the spec validator review passes."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project = await _guard(
            compiler.validate_specs(
                project_id, markdown_by_slug=request.spec_markdown or None
            )
        )
        return await _project_response(project, compiler, user)

    @app.post(
        "/projects/{project_id}/approve", response_model=ProjectResponse, tags=["projects"]
    )
    async def approve_project(
        project_id: str,
        request: ProjectApproveRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Approve the specs and compile every workflow through the back-end."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project = await _guard(
            compiler.approve_spec(
                project_id,
                workflows=request.workflows,
                reviewer=request.reviewer or user.display_name,
                markdown_by_slug=request.spec_markdown or None,
                accept_incomplete=request.accept_incomplete,
                allow_unconfirmed_references=request.allow_unconfirmed_references,
            )
        )
        return await _project_response(project, compiler, user)

    # ------------------------------------------------------------------ #
    # Conversational spec resolution: ask about findings, answer in prose
    # ------------------------------------------------------------------ #
    # Answers apply incrementally — each one patches its spec and bumps that
    # spec's patch version — so these are all plain synchronous calls. A single
    # answer is one LLM round trip, not a pipeline run.

    def _predraft_allowed() -> bool:
        """Whether background question drafting may run on this deployment.

        ``cloud`` (the default) excludes the local Spark gateway: it is a single
        GPU with no queueing, and an extra concurrent request there can push an
        in-flight compile past its timeout and kill it. ``local-fallback`` counts
        as local — it tries the gateway first.
        """
        settings = get_settings()
        if settings.predraft_questions == "off":
            return False
        if settings.predraft_questions == "always":
            return True
        return not settings.llm_provider.startswith("local")

    async def _maybe_predraft(
        project: CompilationProject, compiler: ProjectCompiler, owner_id: str | None
    ) -> Job | None:
        """Start background question drafting, if it is wanted and possible.

        Idempotent and entirely best-effort: it does nothing when the feature is
        off, when there is nothing to ask, when a fresh agenda is already waiting,
        or when any run is already in flight for this project. Callers treat a
        ``None`` return as unremarkable — pre-drafting is a latency optimisation,
        and every path still works without it.
        """
        if not _predraft_allowed():
            return None
        if prepared_agenda_is_fresh(project) or not has_anything_to_ask(project):
            return None
        try:
            return await jobs.start(
                project_id=project.project_id,
                kind="predraft",
                owner_id=owner_id,
                run=lambda: compiler.prepare_dialogue(project.project_id),
            )
        except JobConflictError:
            # Something is already running on this project. Either it is the
            # pre-draft we wanted, or it is real work that will supersede it.
            return None

    def _dialogue_response(
        project: CompilationProject,
        session: DialogueSession | None,
        *,
        outcome: AnswerOutcome | None = None,
    ) -> DialogueResponse:
        """Wrap the dialogue state for the client, including what just changed."""
        question = session.current if session is not None else None
        predraft = jobs.active_for_project(project.project_id, speculative=True)
        return DialogueResponse(
            project=project,
            session=session,
            question=question,
            prompt=question.prompt if question is not None else None,
            options=question.prompt_options if question is not None else [],
            prepared=prepared_agenda_is_fresh(project),
            preparing=predraft is not None,
            answered=session.answered_count if session is not None else 0,
            total=len(session.questions) if session is not None else 0,
            remaining=(
                max(len(session.questions) - session.cursor, 0)
                if session is not None
                else 0
            ),
            changes=outcome.changes if outcome is not None else [],
            parked_as=outcome.parked_as if outcome is not None else None,
            warnings=outcome.warnings if outcome is not None else [],
            spec_markdown={
                spec.slug: render_spec(spec, project.cross_references, project.triggers)
                for spec in project.specs
            },
        )

    @app.get(
        "/projects/{project_id}/dialogue",
        response_model=DialogueResponse,
        tags=["dialogue"],
    )
    async def get_dialogue(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> DialogueResponse:
        """Return the open session, or an empty response when none is open."""
        project = await _guard(compiler.load_project(project_id))
        _check_owner(project, user)
        return _dialogue_response(project, project.dialogue_session)

    @app.post(
        "/projects/{project_id}/dialogue",
        response_model=DialogueResponse,
        tags=["dialogue"],
    )
    async def start_dialogue(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> DialogueResponse:
        """Open a session over the project's blocking/warning findings + questions.

        400 when there is nothing to resolve — validate first if the specs moved.

        A background pre-draft still in flight is cancelled first. The user has
        stopped waiting for it, and letting both run would draft the same agenda
        twice against the model at once — wasted tokens on cloud, and on the
        single-GPU local gateway the kind of concurrent request that pushes an
        in-flight call past its timeout.
        """
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        stale = jobs.active_for_project(project_id, speculative=True)
        if stale is not None:
            await jobs.cancel(stale.job_id)
        project, session = await _guard(compiler.start_dialogue(project_id))
        return _dialogue_response(project, session)

    @app.post(
        "/projects/{project_id}/dialogue/prepare",
        response_model=DialogueResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["dialogue"],
    )
    async def prepare_dialogue(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> DialogueResponse:
        """Draft the dialogue's questions in the background, so opening is instant.

        Safe to call whenever the Resolve tab is opened: it is a no-op when a
        fresh agenda is already waiting, when one is already being drafted, when
        there is nothing to ask, or when the feature is disabled for this
        provider. The response reports ``prepared``/``preparing`` either way, so
        the client learns which of those happened without a second call.

        Nothing is persisted until drafting completes, so an interrupted run —
        a cancelled job, a restarted server — simply leaves nothing prepared and
        this call starts it again.
        """
        project = await _guard(compiler.load_project(project_id))
        _check_owner(project, user)
        await _maybe_predraft(project, compiler, user.user_id)
        return _dialogue_response(project, project.dialogue_session)

    @app.post(
        "/projects/{project_id}/dialogue/answer",
        response_model=DialogueResponse,
        tags=["dialogue"],
    )
    async def answer_dialogue(
        project_id: str,
        request: DialogueAnswerRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> DialogueResponse:
        """Answer the current question in prose; the spec is patched in place."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project, session, outcome = await _guard(
            compiler.answer_dialogue(
                project_id, request.answer, chosen_option=request.option
            )
        )
        return _dialogue_response(project, session, outcome=outcome)

    @app.post(
        "/projects/{project_id}/dialogue/skip",
        response_model=DialogueResponse,
        tags=["dialogue"],
    )
    async def skip_dialogue(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> DialogueResponse:
        """Pass on the current question, leaving the spec untouched."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project, session = await _guard(compiler.skip_dialogue(project_id))
        return _dialogue_response(project, session)

    @app.delete(
        "/projects/{project_id}/dialogue",
        response_model=DialogueResponse,
        tags=["dialogue"],
    )
    async def end_dialogue(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> DialogueResponse:
        """Close the session. Every answer already applied stays applied."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project = await _guard(compiler.end_dialogue(project_id))
        return _dialogue_response(project, None)

    # ------------------------------------------------------------------ #
    # Free-form spec chat: the user says what to change, we patch it
    # ------------------------------------------------------------------ #
    # The other door to the same gate. No agenda and no `validate` prerequisite
    # — POST is enough to start one, so there is no separate "open" call the UI
    # has to make before the user can type.

    def _chat_response(
        project: CompilationProject,
        session: SpecChatSession | None,
        *,
        outcome: ChatOutcome | None = None,
    ) -> SpecChatResponse:
        """Wrap the chat state for the client, including what just changed."""
        return SpecChatResponse(
            project=project,
            session=session,
            reply=outcome.reply if outcome is not None else None,
            status=outcome.status if outcome is not None else None,
            slug=outcome.slug if outcome is not None else None,
            changes=outcome.changes if outcome is not None else [],
            parked_as=outcome.parked_as if outcome is not None else None,
            warnings=outcome.warnings if outcome is not None else [],
            options=session.pending_options if session is not None else [],
            awaiting_clarification=(
                session.awaiting_clarification if session is not None else False
            ),
            applied=session.applied_count if session is not None else 0,
            spec_markdown={
                spec.slug: render_spec(spec, project.cross_references, project.triggers)
                for spec in project.specs
            },
        )

    @app.get(
        "/projects/{project_id}/chat",
        response_model=SpecChatResponse,
        tags=["chat"],
    )
    async def get_spec_chat(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> SpecChatResponse:
        """Return the open chat and its transcript, or an empty response."""
        project = await _guard(compiler.load_project(project_id))
        _check_owner(project, user)
        return _chat_response(project, project.spec_chat)

    @app.post(
        "/projects/{project_id}/chat",
        response_model=SpecChatResponse,
        tags=["chat"],
    )
    async def send_spec_chat(
        project_id: str,
        request: SpecChatRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> SpecChatResponse:
        """Send one instruction in prose; the spec is patched in place.

        Opens a session implicitly when none is open, so the client can just
        post the user's first message.
        """
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project, session, outcome = await _guard(
            compiler.send_spec_chat(
                project_id,
                request.message,
                slug=request.slug,
                chosen_option=request.option,
            )
        )
        return _chat_response(project, session, outcome=outcome)

    @app.delete(
        "/projects/{project_id}/chat",
        response_model=SpecChatResponse,
        tags=["chat"],
    )
    async def end_spec_chat(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> SpecChatResponse:
        """Close the chat and discard the transcript. Applied changes stay."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        project = await _guard(compiler.end_spec_chat(project_id))
        return _chat_response(project, None)

    # ------------------------------------------------------------------ #
    # Background jobs: cancelable validate/approve that survive navigation
    # ------------------------------------------------------------------ #
    # The synchronous /validate and /approve above stay for the CLI-parity path
    # and existing tests. The frontend instead starts a run here so it can cancel
    # it and let it keep running after the user leaves the project page.

    def _authorize_job(job: Job, user: User) -> None:
        """404 a job the caller may not see — mirrors project visibility."""
        if get_settings().projects_shared:
            return
        if job.owner_id is not None and job.owner_id != user.user_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"No job with id {job.job_id!r}."
            )

    def _job_response(job: Job, project: ProjectResponse | None = None) -> JobResponse:
        return JobResponse(
            job_id=job.job_id,
            project_id=job.project_id,
            kind=job.kind,
            status=job.status,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
            project=project,
        )

    @app.post(
        "/projects/{project_id}/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["jobs"],
    )
    async def start_project_job(
        project_id: str,
        request: JobStartRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> JobResponse:
        """Start validate/approve in the background and return immediately (202).

        The run keeps going if the client navigates away; poll ``GET /jobs`` to
        follow it and ``POST /jobs/{id}/cancel`` to stop it (nothing is persisted
        on cancel, so the project is left as it was). At most one run per project
        may be in flight — a second start answers 409.
        """
        _check_owner(await _guard(compiler.load_project(project_id)), user)

        async def warm_questions() -> object:
            """Draft the Resolve tab's questions once a validate has succeeded.

            Validation is what produces the findings the agenda is built from, so
            this is the first moment pre-drafting *can* run — and the user is
            usually heading for the Resolve tab next. It runs as a follow-on
            rather than inside the validate job so that the validate reports done
            when validation is done, and so the pre-draft is not blocked by the
            job that is calling it.
            """
            return await _maybe_predraft(
                await compiler.load_project(project_id), compiler, user.user_id
            )

        def run() -> Awaitable[object]:
            if request.kind == "validate":
                return compiler.validate_specs(
                    project_id, markdown_by_slug=request.spec_markdown or None
                )
            return compiler.approve_spec(
                project_id,
                workflows=request.workflows,
                reviewer=request.reviewer or user.display_name,
                markdown_by_slug=request.spec_markdown or None,
                accept_incomplete=request.accept_incomplete,
                allow_unconfirmed_references=request.allow_unconfirmed_references,
            )

        try:
            job = await jobs.start(
                project_id=project_id,
                kind=request.kind,
                owner_id=user.user_id,
                run=run,
                after=warm_questions if request.kind == "validate" else None,
            )
        except JobConflictError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return _job_response(job)

    @app.get("/jobs", response_model=list[JobResponse], tags=["jobs"])
    async def list_jobs(
        project_id: str | None = None,
        user: User = Depends(get_current_user),
    ) -> list[JobResponse]:
        """Jobs visible to the caller (all users' when projects are shared)."""
        owner_filter = None if get_settings().projects_shared else user.user_id
        return [
            _job_response(j)
            for j in jobs.list(owner_id=owner_filter, project_id=project_id)
        ]

    @app.get("/jobs/{job_id}", response_model=JobResponse, tags=["jobs"])
    async def get_job(
        job_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> JobResponse:
        """One job's status, with the finished project embedded on success."""
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No job with id {job_id!r}.")
        _authorize_job(job, user)
        project: ProjectResponse | None = None
        if job.status == "succeeded":
            loaded = await _guard(compiler.load_project(job.project_id))
            project = await _project_response(loaded, compiler, user)
        return _job_response(job, project)

    @app.post("/jobs/{job_id}/cancel", response_model=JobResponse, tags=["jobs"])
    async def cancel_job(
        job_id: str,
        user: User = Depends(get_current_user),
    ) -> JobResponse:
        """Cancel a running job. Anything the run had not yet persisted is not
        saved, so the project is left exactly as it was before the run started.
        Canceling an already-finished job is a no-op that returns its state."""
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No job with id {job_id!r}.")
        _authorize_job(job, user)
        settled = await jobs.cancel(job_id)
        assert settled is not None  # just fetched above; cancel returns the same job
        return _job_response(settled)

    @app.post(
        "/projects/{project_id}/cvpa", response_model=CvpaPreviewResponse, tags=["projects"]
    )
    async def classify_project_workflow(
        project_id: str,
        request: CvpaPreviewRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> CvpaPreviewResponse:
        """Run CVPA phase-coloring for one workflow and return the diagram (preview)."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        diagram = await _guard(compiler.classify_preview(project_id, request.workflow))
        return CvpaPreviewResponse(slug=request.workflow, diagram=diagram)

    # -- running generated bundles (RUN_WORKFLOWS_HANDOFF §5) ---------------

    @app.get(
        "/projects/{project_id}/runnable",
        response_model=RunnableListResponse,
        tags=["runs"],
    )
    async def list_runnable(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        states: WorkflowCompiler = Depends(get_compiler),
        executor: WorkflowExecutor = Depends(get_executor),
        user: User = Depends(get_current_user),
    ) -> RunnableListResponse:
        """What can be run, and whether Temporal is there to run it.

        Reachability is reported rather than assumed so the UI can disable the
        control with a reason instead of failing when it is clicked (§5.4).
        """
        project = await _guard(compiler.load_project(project_id))
        _check_owner(project, user)

        health = await executor.health()
        root = get_settings().generated_root
        workflows: list[RunnableWorkflowSchema] = []
        for slug, workflow_id in project.workflow_ids.items():
            state = await _guard(states.load_state(workflow_id))
            runnable = describe_runnable(
                slug=slug, state=state, root=root, project_id=project_id
            )
            workflows.append(
                RunnableWorkflowSchema(
                    slug=runnable.slug,
                    workflow_id=runnable.workflow_id,
                    workflow_type=runnable.workflow_type,
                    task_queue=runnable.task_queue,
                    runnable=runnable.runnable,
                    bundle_dir=runnable.bundle_dir,
                    materialized=is_materialized(bundle_dir(root, project_id, slug)),
                    inputs=[
                        WorkflowInputFieldSchema(
                            name=f.name, type=f.type, sample=f.sample
                        )
                        for f in runnable.inputs
                    ],
                    signals=[
                        SignalSchema(name=s.name, params=s.params) for s in runnable.signals
                    ],
                )
            )
        return RunnableListResponse(
            temporal=TemporalHealth(
                reachable=health.reachable,
                address=health.address,
                detail=health.detail,
            ),
            workflows=workflows,
        )

    @app.post(
        "/projects/{project_id}/runs", response_model=RunResponse, tags=["runs"]
    )
    async def start_run(
        project_id: str,
        request: StartRunRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        states: WorkflowCompiler = Depends(get_compiler),
        executor: WorkflowExecutor = Depends(get_executor),
        user: User = Depends(get_current_user),
    ) -> RunResponse:
        """Start one execution of a generated workflow.

        The bundle is materialized to disk if it is not there, and then run
        **from disk** — so a hand-implemented ``activities.py`` is what actually
        executes. Existing files are never overwritten (§3).
        """
        project = await _guard(compiler.load_project(project_id))
        _check_owner(project, user)

        workflow_id = project.workflow_ids.get(request.slug)
        if workflow_id is None:
            raise HTTPException(
                status_code=404,
                detail=f"No generated workflow {request.slug!r} in this project.",
            )
        state = await _guard(states.load_state(workflow_id))
        root = get_settings().generated_root
        runnable = describe_runnable(
            slug=request.slug, state=state, root=root, project_id=project_id
        )
        if not runnable.runnable or runnable.bundle_dir is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{request.slug!r} has no generated bundle to run — approve "
                    "the specs first."
                ),
            )

        unknown = set(request.input) - {f.name for f in runnable.inputs}
        if unknown:
            # Rejected rather than dropped: a field the workflow never reads is
            # a caller mistake, and silently ignoring it makes the run look like
            # it honored input it did not.
            raise HTTPException(
                status_code=422,
                detail=f"Unknown WorkflowInput field(s): {', '.join(sorted(unknown))}.",
            )

        materialized = materialize_bundle(state, Path(runnable.bundle_dir))
        started = await _run_guard(
            executor.start(
                bundle_dir=str(materialized.directory),
                workflow_type=runnable.workflow_type,
                task_queue=runnable.task_queue,
                workflow_id=f"{request.slug}-{uuid.uuid4().hex[:12]}",
                payload=dict(request.input),
            )
        )

        run = runs.add(
            project_id=project_id,
            slug=request.slug,
            owner_id=user.user_id,
            workflow_id=started.workflow_id,
            execution_run_id=started.run_id,
            task_queue=runnable.task_queue,
            workflow_type=runnable.workflow_type,
            bundle_dir=str(materialized.directory),
            status_query=_status_query_for(state),
        )
        return _run_response(
            run,
            started,
            written=materialized.written,
            kept=materialized.kept,
        )

    @app.get(
        "/projects/{project_id}/runs", response_model=list[RunResponse], tags=["runs"]
    )
    async def list_runs(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> list[RunResponse]:
        """Runs for this project, newest first (cached states, no Temporal call)."""
        _check_owner(await _guard(compiler.load_project(project_id)), user)
        visible = None if get_settings().projects_shared else user.user_id
        return [_cached_run_response(run) for run in runs.list(
            owner_id=visible, project_id=project_id
        )]

    @app.get("/runs/{run_id}", response_model=RunResponse, tags=["runs"])
    async def get_run(
        run_id: str,
        executor: WorkflowExecutor = Depends(get_executor),
        user: User = Depends(get_current_user),
    ) -> RunResponse:
        """Live status and step trail for one run."""
        run = _require_run(run_id)
        status = await _run_guard(
            executor.describe(
                workflow_id=run.workflow_id,
                run_id=run.execution_run_id,
                status_query=run.status_query,
            )
        )
        runs.note_state(run.run_id, status.state)
        return _run_response(run, status)

    @app.post("/runs/{run_id}/signal", response_model=RunResponse, tags=["runs"])
    async def signal_run(
        run_id: str,
        request: SignalRunRequest,
        executor: WorkflowExecutor = Depends(get_executor),
        user: User = Depends(get_current_user),
    ) -> RunResponse:
        """Deliver a signal by its **spec** name, one argument per parameter (§6.2)."""
        run = _require_run(run_id)
        await _run_guard(
            executor.signal(
                workflow_id=run.workflow_id,
                run_id=run.execution_run_id,
                name=request.name,
                args=list(request.args),
            )
        )
        status = await _run_guard(
            executor.describe(
                workflow_id=run.workflow_id,
                run_id=run.execution_run_id,
                status_query=run.status_query,
            )
        )
        runs.note_state(run.run_id, status.state)
        return _run_response(run, status)

    @app.delete("/runs/{run_id}", response_model=RunResponse, tags=["runs"])
    async def terminate_run(
        run_id: str,
        executor: WorkflowExecutor = Depends(get_executor),
        user: User = Depends(get_current_user),
    ) -> RunResponse:
        """Stop a running execution."""
        run = _require_run(run_id)
        await _run_guard(
            executor.terminate(
                workflow_id=run.workflow_id,
                run_id=run.execution_run_id,
                reason="terminated from the workflow-compiler UI",
            )
        )
        runs.note_state(run.run_id, "terminated")
        return _cached_run_response(run)

    def _require_run(run_id: str) -> Run:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run {run_id!r}.")
        return run

    return app


app = create_app()

"""FastAPI application exposing the workflow compiler.

Project endpoints (the compile → validate → approve pipeline):

- ``POST /projects/compile``        — segment a document into reviewed specs.
- ``GET  /projects``                — list stored project ids.
- ``GET  /projects/{id}``           — load a project + rendered spec files.
- ``PUT  /projects/{id}/spec``      — fold edited spec Markdown back in (no LLM).
- ``POST /projects/{id}/edit``      — apply an edit-request document, re-arm the gate.
- ``POST /projects/{id}/validate``  — run the spec validator passes.
- ``POST /projects/{id}/approve``   — approve specs, compile every workflow.

Per-workflow endpoints (viewing plus the manual override for workflows whose
graph health fell below the auto-approve threshold):

- ``POST /approve``           — approve a graph and run downstream artifacts.
- ``POST /reject``            — reject a graph.
- ``GET  /workflow/{id}``     — load a stored workflow state.
- ``GET  /workflows``         — list stored workflow ids.
- ``GET  /health``            — liveness probe.

Auth (local accounts; see ``api/auth.py``): ``POST /auth/register``,
``POST /auth/login``, ``POST /auth/logout``, ``GET /auth/me``. Every project
and workflow endpoint requires a signed-in session. Projects carry an
``owner_id`` (recorded for attribution — who created/edits each workflow). By
default (``projects_shared``) every signed-in user can see and open every
project; set ``WORKFLOW_COMPILER_PROJECTS_SHARED=false`` to restore per-owner
isolation, where other users' projects answer 404 and only legacy unowned
projects (``owner_id`` is None, e.g. CLI-created) stay visible to everyone.
"""

from __future__ import annotations

from collections.abc import Awaitable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

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
    get_compiler,
    get_local_provider,
    get_project_compiler,
    project_compiler_for_model,
)
from workflow_compiler.api.schemas import (
    ApproveRequest,
    CvpaPreviewRequest,
    CvpaPreviewResponse,
    EditPreviewResponse,
    LocalModelList,
    LoginRequest,
    MetricsSummary,
    ProjectApproveRequest,
    ProjectCompileRequest,
    ProjectEditRequest,
    ProjectFilesResponse,
    ProjectIdList,
    ProjectResponse,
    RegisterRequest,
    RejectRequest,
    SpecUpdateRequest,
    UserPublic,
    WorkflowIdList,
    WorkflowStateResponse,
)
from workflow_compiler.codegen.temporal.project_generator import generate_project_files
from workflow_compiler.compiler import WorkflowCompiler
from workflow_compiler.config import get_settings
from workflow_compiler.exceptions import (
    ApprovalError,
    CompilationError,
    EditPreviewStaleError,
    ProviderConnectionError,
    ProviderTimeoutError,
    StateNotFoundError,
    UnsupportedFormatError,
    WorkflowCompilerError,
)
from workflow_compiler.ingestion import DocumentParserFactory
from workflow_compiler.metrics import compute_time_saved
from workflow_compiler.models import CompilationProject, GeneratedFile, TemporalWorkflowDesign
from workflow_compiler.models.user import User
from workflow_compiler.project_compiler import ProjectCompiler
from workflow_compiler.spec import render_spec
from workflow_compiler.storage.user_store import UserStore


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
        user_id=user.user_id, email=user.email, display_name=user.display_name
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
    except WorkflowCompilerError as exc:  # pragma: no cover - defensive catch-all
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="workflow-compiler",
        version=__version__,
        description="Compile business workflow documents into canonical artifacts.",
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

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "version": __version__}

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

    @app.get("/providers/local/models", response_model=LocalModelList, tags=["providers"])
    async def local_models() -> LocalModelList:
        """List the models the local eGPU gateway currently exposes (for the picker)."""
        provider = get_local_provider()
        try:
            ids = await provider.list_models()  # type: ignore[attr-defined]
        except ProviderTimeoutError as exc:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc
        except ProviderConnectionError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        finally:
            await provider.aclose()  # type: ignore[attr-defined]
        return LocalModelList(models=ids)

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
        project: CompilationProject, compiler: ProjectCompiler
    ) -> ProjectResponse:
        """Wrap a project with its rendered spec Markdown and structural diagrams."""
        return ProjectResponse(
            project=project,
            spec_markdown={
                spec.slug: render_spec(spec, project.cross_references, project.triggers)
                for spec in project.specs
            },
            time_saved=compute_time_saved(project, get_settings().baseline_hours),
            diagrams=await compiler.build_diagrams(project),
        )

    @app.post("/projects/compile", response_model=ProjectResponse, tags=["projects"])
    async def compile_project(
        request: ProjectCompileRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Segment a document into per-workflow specs (stops at the spec gate)."""
        if request.model:
            compiler = project_compiler_for_model(request.model)
        project = await _guard(
            compiler.compile_document(request.document_text, persist=request.persist)
        )
        project.owner_id = user.user_id
        if request.persist:
            await compiler.save_project(project)
        return await _project_response(project, compiler)

    @app.post(
        "/projects/compile-upload", response_model=ProjectResponse, tags=["projects"]
    )
    async def compile_project_upload(
        file: UploadFile = File(..., description="A .docx/.pdf/.md/.html/.txt document."),
        persist: bool = Form(default=True),
        model: str | None = Form(default=None),
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
        if model:
            compiler = project_compiler_for_model(model)
        project = await _guard(compiler.compile_document(content.text, persist=persist))
        project.owner_id = user.user_id
        if persist:
            await compiler.save_project(project)
        return await _project_response(project, compiler)

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
            project = await _guard(compiler.load_project(project_id))
            if not shared and project.owner_id not in (None, user.user_id):
                continue
            report = compute_time_saved(project, get_settings().baseline_hours)
            if report is None:
                continue
            summary.projects += 1
            summary.total_baseline_hours += report.total_baseline_hours
            summary.total_actual_seconds += report.total_actual_seconds
            summary.total_saved_hours += report.total_saved_hours
        return summary

    @app.get("/projects", response_model=ProjectIdList, tags=["projects"])
    async def list_projects(
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectIdList:
        """List visible project ids.

        With ``projects_shared`` (the default) every stored project is listed;
        otherwise the caller's own projects plus unowned legacy ones.
        """
        ids = await _guard(compiler.list_projects())
        if get_settings().projects_shared:
            return ProjectIdList(project_ids=ids)
        visible: list[str] = []
        for project_id in ids:
            project = await _guard(compiler.load_project(project_id))
            if project.owner_id in (None, user.user_id):
                visible.append(project_id)
        return ProjectIdList(project_ids=visible)

    @app.get("/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
    async def get_project(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
        user: User = Depends(get_current_user),
    ) -> ProjectResponse:
        """Load a stored project plus its rendered spec files."""
        project = await _guard(compiler.load_project(project_id))
        _check_owner(project, user)
        return await _project_response(project, compiler)

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
        return await _project_response(project, compiler)

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
        return await _project_response(project, compiler)

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
        return await _project_response(project, compiler)

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
        return await _project_response(project, compiler)

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

    return app


app = create_app()

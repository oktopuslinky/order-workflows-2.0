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
"""

from __future__ import annotations

from collections.abc import Awaitable

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from workflow_compiler import __version__
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
    LocalModelList,
    ProjectApproveRequest,
    ProjectCompileRequest,
    ProjectEditRequest,
    ProjectFilesResponse,
    ProjectIdList,
    ProjectResponse,
    RejectRequest,
    SpecUpdateRequest,
    WorkflowIdList,
    WorkflowStateResponse,
)
from workflow_compiler.codegen.temporal.project_generator import generate_project_files
from workflow_compiler.compiler import WorkflowCompiler
from workflow_compiler.config import get_settings
from workflow_compiler.exceptions import (
    ApprovalError,
    CompilationError,
    ProviderConnectionError,
    ProviderTimeoutError,
    StateNotFoundError,
    UnsupportedFormatError,
    WorkflowCompilerError,
)
from workflow_compiler.ingestion import DocumentParserFactory
from workflow_compiler.models import CompilationProject, GeneratedFile, TemporalWorkflowDesign
from workflow_compiler.project_compiler import ProjectCompiler
from workflow_compiler.spec import render_spec


async def _guard[T](coro: Awaitable[T]) -> T:
    """Run a compiler coroutine, mapping domain errors to HTTP responses."""
    try:
        return await coro
    except StateNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ApprovalError as exc:
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
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "version": __version__}

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
    ) -> WorkflowStateResponse:
        """Approve a generated graph and produce CVPA + Temporal artifacts."""
        state = await _guard(
            compiler.approve_graph(request.workflow_id, reviewer=request.reviewer)
        )
        return WorkflowStateResponse(state=state)

    @app.post("/reject", response_model=WorkflowStateResponse, tags=["workflows"])
    async def reject_workflow(
        request: RejectRequest,
        compiler: WorkflowCompiler = Depends(get_compiler),
    ) -> WorkflowStateResponse:
        """Reject a generated workflow graph."""
        state = await _guard(
            compiler.reject_graph(
                request.workflow_id, reviewer=request.reviewer, reason=request.reason
            )
        )
        return WorkflowStateResponse(state=state)

    @app.get("/workflow/{workflow_id}", response_model=WorkflowStateResponse, tags=["workflows"])
    async def get_workflow(
        workflow_id: str,
        compiler: WorkflowCompiler = Depends(get_compiler),
    ) -> WorkflowStateResponse:
        """Load a stored workflow state by id."""
        state = await _guard(compiler.load_state(workflow_id))
        return WorkflowStateResponse(state=state)

    @app.get("/workflows", response_model=WorkflowIdList, tags=["workflows"])
    async def list_workflows(
        compiler: WorkflowCompiler = Depends(get_compiler),
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
            diagrams=await compiler.build_diagrams(project),
        )

    @app.post("/projects/compile", response_model=ProjectResponse, tags=["projects"])
    async def compile_project(
        request: ProjectCompileRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
    ) -> ProjectResponse:
        """Segment a document into per-workflow specs (stops at the spec gate)."""
        if request.model:
            compiler = project_compiler_for_model(request.model)
        project = await _guard(
            compiler.compile_document(request.document_text, persist=request.persist)
        )
        return await _project_response(project, compiler)

    @app.post(
        "/projects/compile-upload", response_model=ProjectResponse, tags=["projects"]
    )
    async def compile_project_upload(
        file: UploadFile = File(..., description="A .docx/.pdf/.md/.html/.txt document."),
        persist: bool = Form(default=True),
        model: str | None = Form(default=None),
        compiler: ProjectCompiler = Depends(get_project_compiler),
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
        return await _project_response(project, compiler)

    @app.get("/projects", response_model=ProjectIdList, tags=["projects"])
    async def list_projects(
        compiler: ProjectCompiler = Depends(get_project_compiler),
    ) -> ProjectIdList:
        """List stored project ids."""
        ids = await _guard(compiler.list_projects())
        return ProjectIdList(project_ids=ids)

    @app.get("/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
    async def get_project(
        project_id: str,
        compiler: ProjectCompiler = Depends(get_project_compiler),
    ) -> ProjectResponse:
        """Load a stored project plus its rendered spec files."""
        project = await _guard(compiler.load_project(project_id))
        return await _project_response(project, compiler)

    @app.get(
        "/projects/{project_id}/files", response_model=ProjectFilesResponse, tags=["projects"]
    )
    async def get_project_files(
        project_id: str,
        project_compiler: ProjectCompiler = Depends(get_project_compiler),
        compiler: WorkflowCompiler = Depends(get_compiler),
    ) -> ProjectFilesResponse:
        """Assemble every compiled workflow's bundle plus shared glue files (zip-ready)."""
        project = await _guard(project_compiler.load_project(project_id))
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
    ) -> ProjectResponse:
        """Fold edited spec Markdown back onto the structured specs (no LLM)."""
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
    ) -> ProjectResponse:
        """Apply a workflow edit-request document; the project re-enters the spec gate."""
        project = await _guard(
            compiler.edit_specs(
                project_id,
                request.edit_document,
                workflows=request.workflows,
                author=request.author,
            )
        )
        return await _project_response(project, compiler)

    @app.post(
        "/projects/{project_id}/validate", response_model=ProjectResponse, tags=["projects"]
    )
    async def validate_project(
        project_id: str,
        request: SpecUpdateRequest,
        compiler: ProjectCompiler = Depends(get_project_compiler),
    ) -> ProjectResponse:
        """Ingest edits (if any) and run the spec validator review passes."""
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
    ) -> ProjectResponse:
        """Approve the specs and compile every workflow through the back-end."""
        project = await _guard(
            compiler.approve_spec(
                project_id,
                workflows=request.workflows,
                reviewer=request.reviewer,
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
    ) -> CvpaPreviewResponse:
        """Run CVPA phase-coloring for one workflow and return the diagram (preview)."""
        diagram = await _guard(compiler.classify_preview(project_id, request.workflow))
        return CvpaPreviewResponse(slug=request.workflow, diagram=diagram)

    return app


app = create_app()

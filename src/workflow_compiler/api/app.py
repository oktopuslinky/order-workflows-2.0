"""FastAPI application exposing the workflow compiler.

Endpoints (per the project spec):

- ``POST /compile``           — compile a document into a review-ready state.
- ``POST /approve``           — approve a graph and run downstream artifacts.
- ``POST /reject``            — reject a graph.
- ``GET  /workflow/{id}``     — load a stored workflow state.
- ``GET  /workflows``         — list stored workflow ids.
- ``GET  /health``            — liveness probe.
"""

from __future__ import annotations

from collections.abc import Awaitable

from fastapi import Depends, FastAPI, HTTPException, status

from workflow_compiler import __version__
from workflow_compiler.api.dependencies import get_compiler
from workflow_compiler.api.schemas import (
    ApproveRequest,
    CompileRequest,
    RejectRequest,
    WorkflowIdList,
    WorkflowStateResponse,
)
from workflow_compiler.compiler import WorkflowCompiler
from workflow_compiler.exceptions import (
    ApprovalError,
    CompilationError,
    StateNotFoundError,
    WorkflowCompilerError,
)


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

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "version": __version__}

    @app.post("/compile", response_model=WorkflowStateResponse, tags=["workflows"])
    async def compile_document(
        request: CompileRequest,
        compiler: WorkflowCompiler = Depends(get_compiler),
    ) -> WorkflowStateResponse:
        """Compile a workflow document into a review-ready state."""
        state = await _guard(
            compiler.compile_document(
                request.document_text,
                review_mode=not request.auto_approve,
                persist=request.persist,
            )
        )
        return WorkflowStateResponse(state=state)

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

    return app


app = create_app()

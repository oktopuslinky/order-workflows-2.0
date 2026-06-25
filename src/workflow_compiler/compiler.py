"""The WorkflowCompiler orchestration surface.

This class wires together the agents, review manager, and state store into the
end-to-end compilation pipeline, stopping at the human-in-the-loop approval
gate. Downstream artifacts (CVPA, Temporal) are produced after approval in later
stages of the project.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from workflow_compiler.agents import (
    CVPAClassifierAgent,
    FactExtractionAgent,
    GraphBuilderAgent,
    TemporalGeneratorAgent,
    WorkflowDiscoveryAgent,
)
from workflow_compiler.exceptions import ApprovalError, CompilationError
from workflow_compiler.interfaces import (
    BaseAgent,
    BaseLLMProvider,
    BaseParser,
    ReviewManager,
    StateStore,
)
from workflow_compiler.models import (
    ApprovalStatus,
    CompilationStage,
    ReviewReport,
    WorkflowState,
)
from workflow_compiler.prompts import PromptManager
from workflow_compiler.review import DefaultReviewManager
from workflow_compiler.storage import FileStateStore

if TYPE_CHECKING:
    from workflow_compiler.config import Settings


class WorkflowCompiler:
    """Compile business workflow documents into canonical artifacts.

    The compiler is constructed with its collaborators and exposes a small,
    stable surface:

    - :meth:`compile_document` — run the pipeline up to the approval gate.
    - :meth:`approve_graph` / :meth:`reject_graph` — drive the approval gate.
    - :meth:`review_graph` — refresh a stored workflow's review report.
    - :meth:`save_state` / :meth:`load_state` — persistence helpers.

    The LLM provider is injected and only ever referenced through the
    :class:`BaseLLMProvider` contract, so providers (Nemotron, mock, future
    vendors) are swappable without touching agent or compiler logic::

        compiler = WorkflowCompiler(llm_provider=NemotronProvider(...))
    """

    def __init__(
        self,
        *,
        llm_provider: BaseLLMProvider | None = None,
        parser: BaseParser | None = None,
        agents: list[BaseAgent] | None = None,
        post_approval_agents: list[BaseAgent] | None = None,
        review_manager: ReviewManager | None = None,
        state_store: StateStore | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Wire the compiler to its collaborators, defaulting the rest.

        If ``agents`` is omitted, the pre-review pipeline (discovery → facts →
        graph) is built around the injected ``llm_provider``. If
        ``post_approval_agents`` is omitted, the post-approval pipeline (CVPA
        classification → Temporal design) is built the same way.
        ``review_manager`` and ``state_store`` default to the deterministic
        graph reviewer and a file-backed store respectively.
        """
        self._llm_provider = llm_provider
        self._parser = parser
        self._prompt_manager = prompt_manager or PromptManager()
        self._agents = (
            list(agents)
            if agents is not None
            else self._default_agents(llm_provider, self._prompt_manager)
        )
        self._post_approval_agents = (
            list(post_approval_agents)
            if post_approval_agents is not None
            else self._default_post_approval_agents(llm_provider, self._prompt_manager)
        )
        self._review_manager = review_manager or DefaultReviewManager()
        self._state_store = state_store or FileStateStore()

    @classmethod
    def from_settings(
        cls,
        *,
        llm_provider: BaseLLMProvider | None = None,
        settings: Settings | None = None,
        state_store: StateStore | None = None,
        **kwargs: object,
    ) -> WorkflowCompiler:
        """Build a fully wired compiler from application settings / ``.env``.

        Resolves the LLM provider via :class:`ProviderFactory` and a file-backed
        state store rooted at ``settings.state_store_path`` unless explicitly
        supplied. This is the entry point used by the CLI and HTTP API.
        """
        from workflow_compiler.config import get_settings
        from workflow_compiler.llm import ProviderFactory

        resolved = settings or get_settings()
        provider = llm_provider or ProviderFactory().from_settings(resolved)
        store = state_store or FileStateStore(resolved.state_store_path)
        return cls(llm_provider=provider, state_store=store, **kwargs)  # type: ignore[arg-type]

    @staticmethod
    def _default_agents(
        llm: BaseLLMProvider | None, prompts: PromptManager
    ) -> list[BaseAgent]:
        """Build the standard discovery → facts → graph agent pipeline."""
        return [
            WorkflowDiscoveryAgent(llm, prompt_manager=prompts),
            FactExtractionAgent(llm, prompt_manager=prompts),
            GraphBuilderAgent(),
        ]

    @staticmethod
    def _default_post_approval_agents(
        llm: BaseLLMProvider | None, prompts: PromptManager
    ) -> list[BaseAgent]:
        """Build the post-approval CVPA → Temporal design pipeline."""
        return [
            CVPAClassifierAgent(llm, prompt_manager=prompts),
            TemporalGeneratorAgent(llm, prompt_manager=prompts),
        ]

    @property
    def llm_provider(self) -> BaseLLMProvider | None:
        """The injected LLM provider (accessed only via the abstract contract)."""
        return self._llm_provider

    @property
    def prompt_manager(self) -> PromptManager:
        """The prompt manager used to render agent prompts."""
        return self._prompt_manager

    async def compile_document(
        self,
        document_text: str,
        *,
        review_mode: bool = True,
        persist: bool = True,
        workflow_id: str | None = None,
    ) -> WorkflowState:
        """Compile a raw workflow document into a review-ready WorkflowState.

        Runs the configured agent pipeline (discovery → facts → graph), then
        reviews the generated graph and sets ``approval_status`` to ``PENDING``.

        When ``review_mode`` is ``True`` (the default) compilation **stops** at
        the approval gate and returns the reviewed state; downstream artifacts
        (CVPA, Temporal) are only produced once the graph is approved via
        :meth:`approve_graph`. When ``review_mode`` is ``False`` the graph is
        auto-approved and the full pipeline runs end-to-end in one call.
        """
        if not document_text or not document_text.strip():
            raise CompilationError("Cannot compile an empty document.")

        state = WorkflowState(document_text=document_text)
        if workflow_id is not None:
            state.workflow_id = workflow_id

        for agent in self._agents:
            state = await agent.run(state)

        report = await self._review_manager.review(state)
        state.review_report = report
        state.approval_status = ApprovalStatus.PENDING
        state.stage = CompilationStage.REVIEWED
        state.touch()

        if persist:
            await self._state_store.save(state)

        if review_mode:
            return state

        # Fully automated run: clear the gate and produce downstream artifacts
        # in-process (no reload), persisting once at the end if requested.
        state = await self._finalize_approval(state, reviewer="auto")
        if persist:
            await self._state_store.save(state)
        return state

    async def _finalize_approval(
        self, state: WorkflowState, *, reviewer: str | None
    ) -> WorkflowState:
        """Approve the graph and run the downstream CVPA → Temporal pipeline."""
        if state.workflow_graph is None:
            raise ApprovalError(f"Workflow {state.workflow_id!r} has no graph to approve.")
        state = await self._review_manager.approve(state, reviewer=reviewer)
        for agent in self._post_approval_agents:
            state = await agent.run(state)
        state.stage = CompilationStage.COMPLETED
        state.touch()
        return state

    async def approve_graph(
        self,
        workflow_id: str,
        *,
        reviewer: str | None = None,
        persist: bool = True,
    ) -> WorkflowState:
        """Approve a stored workflow graph and produce downstream artifacts.

        Clearing the gate runs the post-approval pipeline (CVPA classification →
        Temporal design) and marks the run ``COMPLETED``.
        """
        state = await self._state_store.load(workflow_id)
        state = await self._finalize_approval(state, reviewer=reviewer)
        if persist:
            await self._state_store.save(state)
        return state

    async def reject_graph(
        self,
        workflow_id: str,
        *,
        reviewer: str | None = None,
        reason: str | None = None,
        persist: bool = True,
    ) -> WorkflowState:
        """Reject a stored workflow graph, halting downstream production."""
        state = await self._state_store.load(workflow_id)
        if state.workflow_graph is None:
            raise ApprovalError(f"Workflow {workflow_id!r} has no graph to reject.")
        state = await self._review_manager.reject(state, reviewer=reviewer, reason=reason)
        if persist:
            await self._state_store.save(state)
        return state

    async def review_graph(self, workflow_id: str) -> ReviewReport:
        """Produce (and persist) a fresh review report for a stored workflow."""
        state = await self._state_store.load(workflow_id)
        report = await self._review_manager.review(state)
        state.review_report = report
        state.touch()
        await self._state_store.save(state)
        return report

    async def save_state(self, state: WorkflowState) -> None:
        """Persist a workflow state via the configured state store."""
        await self._state_store.save(state)

    async def load_state(self, workflow_id: str) -> WorkflowState:
        """Load a workflow state by id via the configured state store."""
        return await self._state_store.load(workflow_id)

    async def list_states(self) -> list[str]:
        """Return the ids of all stored workflow states."""
        return await self._state_store.list_ids()

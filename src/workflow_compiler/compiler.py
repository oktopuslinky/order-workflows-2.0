"""The WorkflowCompiler orchestration surface.

This class wires together the agents, review manager, and state store into the
end-to-end compilation pipeline, stopping at the human-in-the-loop approval
gate. Downstream artifacts (CVPA, Temporal) are produced after approval in later
stages of the project.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from workflow_compiler.agents import (
    DISCOVERY_SPEC,
    FACTS_REVIEW_SPEC,
    FACTS_SPEC,
    METADATA_REVIEW_SPEC,
    ConsensusMergeAgent,
    CVPAClassifierAgent,
    FactExtractionAgent,
    GraphBuilderAgent,
    ReviewPipelineAgent,
    ReviewSpec,
    StageSpec,
    TemporalCodeGeneratorAgent,
    TemporalGeneratorAgent,
    WorkflowDiscoveryAgent,
)
from workflow_compiler.checklist import ChecklistValidator
from workflow_compiler.checklist import amend as checklist_amend
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


@dataclass(frozen=True)
class ProgressEvent:
    """A single observable pipeline step, emitted as it starts and finishes.

    The compiler emits one ``status="start"`` event before a step runs and one
    ``status="done"`` event after, so callers can render a live, timed view of
    what is happening at each moment without coupling to the compiler internals.
    """

    phase: str  # "agent" | "review" | "approve"
    name: str  # step name (e.g. the agent name)
    status: str  # "start" | "done"
    index: int  # 1-based position within its sub-pipeline
    total: int  # number of steps in its sub-pipeline
    seconds: float | None = None  # wall time for the step (on "done")
    stage: str | None = None  # resulting CompilationStage value (on "done")


#: A progress sink: called with each :class:`ProgressEvent`. Never raises into
#: the pipeline — the compiler guards every call.
ProgressCallback = Callable[[ProgressEvent], None]


def _emit(progress: ProgressCallback | None, event: ProgressEvent) -> None:
    """Deliver ``event`` to ``progress`` if set, swallowing observer errors."""
    if progress is None:
        return
    with contextlib.suppress(Exception):  # a progress sink must never break a run
        progress(event)


@dataclass(frozen=True)
class EnsembleConfig:
    """Configuration for the consensus-merge ensemble on selected LLM stages."""

    enabled: bool = False
    n: int = 3
    temperatures: tuple[float, ...] = (0.2, 0.5, 0.8)
    stages: frozenset[str] = frozenset({"discovery", "facts"})
    per_candidate_timeout: float = 300.0
    overall_timeout: float = 480.0

    def temperatures_for(self) -> list[float]:
        """Return exactly ``n`` temperatures, spreading evenly if too few given."""
        base = list(self.temperatures)
        if len(base) >= self.n:
            return base[: self.n]
        if self.n == 1:
            return [base[0] if base else 0.5]
        return [round(0.2 + 0.6 * i / (self.n - 1), 3) for i in range(self.n)]

    @classmethod
    def from_settings(
        cls, settings: Settings, *, enabled: bool | None = None, n: int | None = None
    ) -> EnsembleConfig:
        """Build from ``Settings`` with optional CLI overrides for enabled / n."""
        return cls(
            enabled=settings.ensemble_enabled if enabled is None else enabled,
            n=settings.ensemble_n if n is None else n,
            temperatures=tuple(settings.ensemble_temperatures),
            stages=frozenset(settings.ensemble_stages),
            per_candidate_timeout=settings.ensemble_per_candidate_timeout,
            overall_timeout=settings.ensemble_overall_timeout,
        )


@dataclass(frozen=True)
class ReviewConfig:
    """Configuration for the sequential review pipeline on selected LLM stages.

    The review pipeline generates one canonical output per stage and improves it
    with three sequential review passes. It is **on by default**, but the ensemble
    takes precedence on any stage it is enabled for (see ``WorkflowCompiler._maybe_wrap``).
    """

    enabled: bool = True
    stages: frozenset[str] = frozenset({"discovery", "facts"})

    @classmethod
    def from_settings(
        cls, settings: Settings, *, enabled: bool | None = None
    ) -> ReviewConfig:
        """Build from ``Settings`` with an optional CLI override for ``enabled``."""
        return cls(
            enabled=settings.review_enabled if enabled is None else enabled,
            stages=frozenset(settings.review_stages),
        )


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
        ensemble: EnsembleConfig | None = None,
        review: ReviewConfig | None = None,
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
        self._ensemble = ensemble or EnsembleConfig()
        self._review = review or ReviewConfig()
        self._agents = (
            list(agents)
            if agents is not None
            else self._default_agents(
                llm_provider, self._prompt_manager, self._ensemble, self._review
            )
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
        ensemble = kwargs.pop("ensemble", None) or EnsembleConfig.from_settings(resolved)
        review = kwargs.pop("review", None) or ReviewConfig.from_settings(resolved)
        return cls(  # type: ignore[arg-type]
            llm_provider=provider,
            state_store=store,
            ensemble=ensemble,
            review=review,
            **kwargs,
        )

    @staticmethod
    def _default_agents(
        llm: BaseLLMProvider | None,
        prompts: PromptManager,
        ensemble: EnsembleConfig,
        review: ReviewConfig,
    ) -> list[BaseAgent]:
        """Build the standard discovery → facts → graph agent pipeline.

        Each LLM stage is wrapped per :meth:`_maybe_wrap`'s precedence: the
        ensemble (if enabled for the stage), else the sequential review pipeline
        (on by default), else the plain agent. Graph building is deterministic and
        never wrapped.
        """
        discovery = WorkflowDiscoveryAgent(llm, prompt_manager=prompts)
        facts = FactExtractionAgent(llm, prompt_manager=prompts)
        return [
            WorkflowCompiler._maybe_wrap(
                "discovery",
                discovery,
                lambda p: WorkflowDiscoveryAgent(p, prompt_manager=prompts),
                DISCOVERY_SPEC,
                METADATA_REVIEW_SPEC,
                llm,
                prompts,
                ensemble,
                review,
            ),
            WorkflowCompiler._maybe_wrap(
                "facts",
                facts,
                lambda p: FactExtractionAgent(p, prompt_manager=prompts),
                FACTS_SPEC,
                FACTS_REVIEW_SPEC,
                llm,
                prompts,
                ensemble,
                review,
            ),
            GraphBuilderAgent(),
        ]

    @staticmethod
    def _maybe_wrap(
        stage: str,
        plain: BaseAgent,
        inner_factory: Callable[[BaseLLMProvider], BaseAgent],
        ensemble_spec: StageSpec,
        review_spec: ReviewSpec,
        llm: BaseLLMProvider | None,
        prompts: PromptManager,
        ensemble: EnsembleConfig,
        review: ReviewConfig,
    ) -> BaseAgent:
        """Select the quality strategy for ``stage`` (ensemble > review > plain).

        The ensemble wins on any stage it is explicitly enabled for; otherwise the
        sequential review pipeline runs (default-on); otherwise the plain agent runs.
        """
        if llm is None:
            return plain
        if ensemble.enabled and stage in ensemble.stages:
            return ConsensusMergeAgent(
                inner_factory=inner_factory,
                provider=llm,
                temperatures=ensemble.temperatures_for(),
                spec=ensemble_spec,
                per_candidate_timeout=ensemble.per_candidate_timeout,
                overall_timeout=ensemble.overall_timeout,
            )
        if review.enabled and stage in review.stages:
            return ReviewPipelineAgent(
                inner_factory=inner_factory,
                provider=llm,
                spec=review_spec,
                prompt_manager=prompts,
            )
        return plain

    @staticmethod
    def _default_post_approval_agents(
        llm: BaseLLMProvider | None, prompts: PromptManager
    ) -> list[BaseAgent]:
        """Build the post-approval CVPA → Temporal design → code pipeline."""
        return [
            CVPAClassifierAgent(llm, prompt_manager=prompts),
            TemporalGeneratorAgent(llm, prompt_manager=prompts),
            TemporalCodeGeneratorAgent(),
        ]

    @property
    def llm_provider(self) -> BaseLLMProvider | None:
        """The injected LLM provider (accessed only via the abstract contract)."""
        return self._llm_provider

    @property
    def prompt_manager(self) -> PromptManager:
        """The prompt manager used to render agent prompts."""
        return self._prompt_manager

    @staticmethod
    async def _run_agents(
        agents: list[BaseAgent],
        state: WorkflowState,
        progress: ProgressCallback | None,
        *,
        phase: str = "agent",
    ) -> WorkflowState:
        """Run ``agents`` in order, emitting timed start/done progress events.

        An agent that exposes ``set_progress`` (e.g. :class:`ReviewPipelineAgent`)
        is handed a **nested** sub-reporter so its internal steps — the canonical
        generation and each review pass — surface in the same live log, indented
        under the agent's own start/done pair.
        """
        total = len(agents)
        for index, agent in enumerate(agents, start=1):
            name = getattr(agent, "name", agent.__class__.__name__)
            _emit(
                progress,
                ProgressEvent(phase=phase, name=name, status="start", index=index, total=total),
            )
            started = time.perf_counter()
            setter = getattr(agent, "set_progress", None)
            if callable(setter):
                setter(WorkflowCompiler._sub_reporter(progress))
            try:
                state = await agent.run(state)
            finally:
                if callable(setter):
                    setter(None)
            _emit(
                progress,
                ProgressEvent(
                    phase=phase,
                    name=name,
                    status="done",
                    index=index,
                    total=total,
                    seconds=time.perf_counter() - started,
                    stage=state.stage.value,
                ),
            )
        return state

    @staticmethod
    def _sub_reporter(progress: ProgressCallback | None) -> Callable[..., None]:
        """Return a callable an agent uses to emit nested ``review-pass`` events.

        The agent stays decoupled from :class:`ProgressEvent` — it calls
        ``report(name, status, index, total, seconds=?, stage=?)`` and this adapter
        builds the event (phase ``"review-pass"``) and forwards it to ``progress``.
        """

        def report(
            name: str,
            status: str,
            index: int,
            total: int,
            *,
            seconds: float | None = None,
            stage: str | None = None,
        ) -> None:
            _emit(
                progress,
                ProgressEvent(
                    phase="review-pass",
                    name=name,
                    status=status,
                    index=index,
                    total=total,
                    seconds=seconds,
                    stage=stage,
                ),
            )

        return report

    @staticmethod
    def _split_on_graph(agents: list[BaseAgent]) -> tuple[list[BaseAgent], list[BaseAgent]]:
        """Partition agents into those before the graph builder and from it onward.

        The readiness checklist is computed between fact extraction and graph
        building, so the graph builder (and anything after it) runs only once the
        gate is cleared.
        """
        pre: list[BaseAgent] = []
        post: list[BaseAgent] = []
        seen_graph = False
        for agent in agents:
            if isinstance(agent, GraphBuilderAgent):
                seen_graph = True
            (post if seen_graph else pre).append(agent)
        return pre, post

    async def compile_document(
        self,
        document_text: str,
        *,
        review_mode: bool = True,
        persist: bool = True,
        workflow_id: str | None = None,
        enforce_checklist: bool = False,
        progress: ProgressCallback | None = None,
    ) -> WorkflowState:
        """Compile a raw workflow document into a review-ready WorkflowState.

        Runs discovery → facts, computes the pre-generation readiness checklist,
        then (if cleared) builds the graph, reviews it, and sets ``approval_status``
        to ``PENDING``.

        When ``enforce_checklist`` is ``True`` and a **required** checklist item is
        unmet, compilation **halts at the checklist gate** (stage ``CHECKLISTED``)
        and returns before any graph/code is produced; the caller resumes via
        :meth:`resume_from_checklist` after the user fills in the report. The
        checklist is always computed and attached to ``state.checklist`` regardless.

        When ``review_mode`` is ``True`` (the default) compilation otherwise stops
        at the approval gate; when ``False`` the graph is auto-approved and the full
        pipeline runs end-to-end in one call.
        """
        if not document_text or not document_text.strip():
            raise CompilationError("Cannot compile an empty document.")

        state = WorkflowState(document_text=document_text)
        if workflow_id is not None:
            state.workflow_id = workflow_id

        pre_agents, post_agents = self._split_on_graph(self._agents)
        state = await self._run_agents(pre_agents, state, progress)

        # Pre-generation readiness gate: always compute, optionally enforce.
        state.checklist = ChecklistValidator().validate(state)
        if enforce_checklist and not state.checklist.is_satisfied():
            state.stage = CompilationStage.CHECKLISTED
            state.touch()
            if persist:
                await self._state_store.save(state)
            return state

        return await self._continue_after_checklist(
            state, post_agents, progress, review_mode=review_mode, persist=persist
        )

    async def resume_from_checklist(
        self,
        workflow_id: str,
        answers: dict[str, str],
        *,
        accept_as_is: bool = False,
        review_mode: bool = True,
        persist: bool = True,
        progress: ProgressCallback | None = None,
    ) -> WorkflowState:
        """Apply checklist answers to a halted run and continue if the gate clears.

        Loads the state saved at the checklist gate, folds ``answers`` in as
        deterministic local amendments (no LLM), and re-validates. If required
        items remain unmet the run stays halted (the refreshed checklist is
        persisted so a new report can be written); otherwise the graph is built and
        the pipeline continues exactly as :meth:`compile_document` would have.
        """
        state = await self._state_store.load(workflow_id)
        state = checklist_amend.apply(state, answers, accept_as_is=accept_as_is)
        if state.checklist is not None and not state.checklist.is_satisfied():
            if persist:
                await self._state_store.save(state)
            return state

        _pre, post_agents = self._split_on_graph(self._agents)
        return await self._continue_after_checklist(
            state, post_agents, progress, review_mode=review_mode, persist=persist
        )

    async def _continue_after_checklist(
        self,
        state: WorkflowState,
        post_agents: list[BaseAgent],
        progress: ProgressCallback | None,
        *,
        review_mode: bool,
        persist: bool,
    ) -> WorkflowState:
        """Build the graph, review it, and (optionally) run the full pipeline."""
        state = await self._run_agents(post_agents, state, progress)

        _emit(
            progress,
            ProgressEvent(phase="review", name="review", status="start", index=1, total=1),
        )
        started = time.perf_counter()
        report = await self._review_manager.review(state)
        state.review_report = report
        state.approval_status = ApprovalStatus.PENDING
        state.stage = CompilationStage.REVIEWED
        state.touch()
        _emit(
            progress,
            ProgressEvent(
                phase="review",
                name="review",
                status="done",
                index=1,
                total=1,
                seconds=time.perf_counter() - started,
                stage=state.stage.value,
            ),
        )

        if persist:
            await self._state_store.save(state)

        if review_mode:
            return state

        # Fully automated run: clear the gate and produce downstream artifacts
        # in-process (no reload), persisting once at the end if requested.
        state = await self._finalize_approval(state, reviewer="auto", progress=progress)
        if persist:
            await self._state_store.save(state)
        return state

    async def _finalize_approval(
        self,
        state: WorkflowState,
        *,
        reviewer: str | None,
        progress: ProgressCallback | None = None,
    ) -> WorkflowState:
        """Approve the graph and run the downstream CVPA → Temporal pipeline."""
        if state.workflow_graph is None:
            raise ApprovalError(f"Workflow {state.workflow_id!r} has no graph to approve.")
        _emit(
            progress,
            ProgressEvent(phase="approve", name="approve", status="start", index=1, total=1),
        )
        started = time.perf_counter()
        state = await self._review_manager.approve(state, reviewer=reviewer)
        _emit(
            progress,
            ProgressEvent(
                phase="approve",
                name="approve",
                status="done",
                index=1,
                total=1,
                seconds=time.perf_counter() - started,
            ),
        )
        state = await self._run_agents(self._post_approval_agents, state, progress)
        state.stage = CompilationStage.COMPLETED
        state.touch()
        return state

    async def approve_graph(
        self,
        workflow_id: str,
        *,
        reviewer: str | None = None,
        persist: bool = True,
        progress: ProgressCallback | None = None,
    ) -> WorkflowState:
        """Approve a stored workflow graph and produce downstream artifacts.

        Clearing the gate runs the post-approval pipeline (CVPA classification →
        Temporal design → code) and marks the run ``COMPLETED``.
        """
        state = await self._state_store.load(workflow_id)
        state = await self._finalize_approval(state, reviewer=reviewer, progress=progress)
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

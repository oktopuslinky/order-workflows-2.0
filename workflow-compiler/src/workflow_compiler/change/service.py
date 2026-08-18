"""ChangeRequestService — the façade the API and CLI call (load → engine → save).

Mirrors ``ProjectCompiler`` for change requests: it owns the store, builds the
per-request LLM provider through the injected factory (``(provider_name |
None, model | None) -> BaseLLMProvider`` — the same signature ``KgService``
uses, cloud Nemotron by default in the API), and drives
:class:`~workflow_compiler.change.engine.ChangeWizardEngine`. Every public
method persists the change request before returning, so a job that is
cancelled mid-call leaves the previous state intact.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from workflow_compiler.agents.change_analyst import ChangeAnalystAgent
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.ingestion import DocumentParserFactory
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.kg.service import KgService
from workflow_compiler.models.change import (
    Artifact,
    ArtifactKind,
    ArtifactVersion,
    ChangeRequest,
    WizardStep,
)
from workflow_compiler.storage.change_store import ChangeRequestStore

from . import bcr as bcrmod
from .engine import AnswerOutcome, ChangeWizardEngine, ProgressFn

ProviderFactory = Callable[[str | None, str | None], BaseLLMProvider]

_TEXT_SUFFIXES = (".md", ".markdown", ".txt")


class ChangeRequestService:
    """Create change requests and run their wizard (see module docstring)."""

    def __init__(
        self,
        store: ChangeRequestStore,
        kg: KgService,
        provider_factory: ProviderFactory | None = None,
        *,
        kg_budget: int = 9000,
        per_query_budget: int = 1000,
    ) -> None:
        self._store = store
        self._kg = kg
        self._provider_factory = provider_factory
        self._kg_budget = kg_budget
        self._per_query_budget = per_query_budget

    @property
    def store(self) -> ChangeRequestStore:
        return self._store

    @property
    def kg(self) -> KgService:
        return self._kg

    # ------------------------------------------------------------ plumbing
    def _engine(self, cr: ChangeRequest) -> ChangeWizardEngine:
        if self._provider_factory is None:
            raise CompilationError("ChangeRequestService has no LLM provider factory configured.")
        provider = self._provider_factory(cr.wizard.provider, cr.wizard.model)
        return ChangeWizardEngine(
            ChangeAnalystAgent(provider),
            self._kg,
            per_query_budget=self._per_query_budget,
            total_budget=self._kg_budget,
        )

    def _offline_engine(self) -> ChangeWizardEngine:
        """Engine for the LLM-free transitions (skip/edit/approve)."""
        return ChangeWizardEngine(ChangeAnalystAgent(None), self._kg)

    async def _save(self, cr: ChangeRequest) -> ChangeRequest:
        cr.updated_at = datetime.now(UTC)
        await self._store.save(cr)
        return cr

    # -------------------------------------------------------------- create
    async def create(
        self,
        kb_id: str,
        *,
        data: bytes | None = None,
        text: str | None = None,
        filename: str | None = None,
        title: str | None = None,
        owner_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> ChangeRequest:
        """Register a change request from an uploaded document (docx/md/txt) or text."""
        kb = await self._kg.get(kb_id)
        if data is not None:
            lower = (filename or "").lower()
            if lower.endswith(_TEXT_SUFFIXES):
                document_text = data.decode("utf-8", errors="replace")
            else:
                content = DocumentParserFactory().parse(data, filename=filename)
                document_text = content.text
        elif text is not None:
            document_text = text
        else:
            raise CompilationError("A change request needs a document (file or text).")
        document_text = document_text.replace("\r\n", "\n").strip()
        if not document_text:
            raise CompilationError("The change request document is empty.")
        meta = bcrmod.parse_meta(document_text)
        requirements = bcrmod.parse_requirements(document_text)
        cr = ChangeRequest(
            kb_id=kb.kb_id,
            kb_name=kb.name,
            owner_id=owner_id,
            title=(title or "").strip()
            or bcrmod.parse_title(document_text, fallback=bcrmod.title_from_filename(filename)),
            document_text=document_text,
            source_filename=filename,
            bcr_meta=meta,
            requirements=requirements,
            impact_seed_terms=bcrmod.seed_terms(document_text, requirements),
        )
        cr.wizard.provider = provider
        cr.wizard.model = model
        if not requirements:
            cr.warnings.append(
                "No numbered requirements (BCR-NN-NN | text) were found in the document; "
                "the wizard will work from the prose only."
            )
        return await self._save(cr)

    async def get(self, cr_id: str) -> ChangeRequest:
        return await self._store.load(cr_id)

    async def list_all(self) -> list[ChangeRequest]:
        items = [await self._store.load(cr_id) for cr_id in await self._store.list_ids()]
        items.sort(key=lambda c: c.updated_at, reverse=True)
        return items

    async def delete(self, cr_id: str) -> None:
        await self._store.delete(cr_id)

    # -------------------------------------------------------------- wizard
    async def start(
        self, cr_id: str, *, provider: str | None = None, model: str | None = None
    ) -> ChangeRequest:
        """LLM-free half of starting: reserve ids + impact traversal, mark started."""
        cr = await self.get(cr_id)
        if provider is not None:
            cr.wizard.provider = provider
        if model is not None:
            cr.wizard.model = model
        await self._offline_engine().initialize(cr)
        return await self._save(cr)

    async def start_questions(
        self, cr_id: str, kind: ArtifactKind | str | None = None
    ) -> ChangeRequest:
        """Draft the current (or given) step's clarifying questions (LLM; run as a job)."""
        cr = await self.get(cr_id)
        engine = self._engine(cr)
        await engine.start_step(cr, kind)
        return await self._save(cr)

    async def answer(
        self, cr_id: str, answer: str, *, option: str | None = None
    ) -> tuple[ChangeRequest, AnswerOutcome]:
        cr = await self.get(cr_id)
        engine = self._engine(cr)
        outcome = await engine.answer(cr, answer, option=option)
        await self._save(cr)
        return cr, outcome

    async def skip(self, cr_id: str) -> ChangeRequest:
        cr = await self.get(cr_id)
        self._offline_engine().skip(cr)
        return await self._save(cr)

    async def draft(
        self,
        cr_id: str,
        kind: ArtifactKind | str | None = None,
        *,
        progress: ProgressFn | None = None,
    ) -> ChangeRequest:
        cr = await self.get(cr_id)
        engine = self._engine(cr)
        try:
            await engine.draft(cr, kind, progress=progress)
        finally:
            # A failed draft still records the error/turn on the step.
            await self._save(cr)
        return cr

    async def revise(self, cr_id: str, kind: ArtifactKind | str, message: str) -> ChangeRequest:
        cr = await self.get(cr_id)
        engine = self._engine(cr)
        try:
            await engine.revise(cr, kind, message)
        finally:
            await self._save(cr)
        return cr

    async def edit(
        self, cr_id: str, kind: ArtifactKind | str, markdown: str, *, note: str = ""
    ) -> ChangeRequest:
        cr = await self.get(cr_id)
        self._offline_engine().edit(cr, kind, markdown, note=note)
        return await self._save(cr)

    async def approve(self, cr_id: str, kind: ArtifactKind | str | None = None) -> ChangeRequest:
        cr = await self.get(cr_id)
        self._offline_engine().approve(cr, kind)
        return await self._save(cr)

    async def artifact(
        self, cr_id: str, kind: ArtifactKind | str, *, version: int | None = None
    ) -> tuple[ChangeRequest, Artifact, ArtifactVersion | None]:
        cr = await self.get(cr_id)
        artifact = cr.artifacts.get(kind)
        if version is None:
            return cr, artifact, None
        entry = artifact.get_version(version)
        if entry is None:
            raise CompilationError(
                f"{artifact.kind.value} has no version {version} (latest is {artifact.version})."
            )
        return cr, artifact, entry

    @staticmethod
    def current_step(cr: ChangeRequest) -> WizardStep | None:
        return cr.wizard.current

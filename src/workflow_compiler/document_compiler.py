"""DocumentCompiler: the outer, multi-workflow orchestration surface.

This is a thin front-end composed over the existing single-workflow
:class:`~workflow_compiler.compiler.WorkflowCompiler`, which it reuses unchanged:

- :meth:`author_document` — segment a document into N workflows, run the existing
  discovery + fact extraction on each slice, and render an editable **master
  document** whose per-workflow sections are shaped like
  ``examples/ideal_temporal_workflow.md``. It then halts for human editing.
- :meth:`compile_authored` — split an edited master document into per-workflow
  ideal documents and compile each through the existing pipeline, gating each
  workflow independently. Cross-workflow ``invokes`` links ride along as authored
  prose and are modelled as Temporal child workflows by the design stage.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from workflow_compiler.agents.ideal_prose import IdealProseAgent
from workflow_compiler.agents.segmenter import WorkflowSegmenterAgent
from workflow_compiler.authoring import (
    assemble_master,
    parse_master,
    render_ideal_section,
    split_master,
)
from workflow_compiler.compiler import WorkflowCompiler
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    DocumentCompilation,
    DocumentStage,
    WorkflowChecklist,
    WorkflowSegment,
    WorkflowState,
)
from workflow_compiler.prompts import PromptManager
from workflow_compiler.storage import DocumentStore

if TYPE_CHECKING:
    from workflow_compiler.config import Settings


class DocumentCompiler:
    """Compile a (possibly multi-workflow) document via author → edit → recompile."""

    def __init__(
        self,
        *,
        compiler: WorkflowCompiler,
        segmenter: WorkflowSegmenterAgent,
        document_store: DocumentStore | None = None,
        prose: IdealProseAgent | None = None,
    ) -> None:
        """Wire the outer compiler to the reused single-workflow compiler.

        ``prose`` is the optional grounding-checked polish agent; when absent (or when
        :meth:`author_document` is called with ``polish=False``) authoring is purely
        deterministic.
        """
        self._compiler = compiler
        self._segmenter = segmenter
        self._doc_store = document_store or DocumentStore()
        self._prose = prose

    @classmethod
    def from_settings(
        cls,
        *,
        llm_provider: BaseLLMProvider | None = None,
        settings: Settings | None = None,
    ) -> DocumentCompiler:
        """Build a fully wired document compiler from application settings / ``.env``."""
        from workflow_compiler.config import get_settings
        from workflow_compiler.llm import ProviderFactory

        resolved = settings or get_settings()
        provider = llm_provider or ProviderFactory().from_settings(resolved)
        prompts = PromptManager()
        compiler = WorkflowCompiler.from_settings(llm_provider=provider, settings=resolved)
        return cls(
            compiler=compiler,
            segmenter=WorkflowSegmenterAgent(provider, prompt_manager=prompts),
            document_store=DocumentStore(resolved.state_store_path),
            prose=IdealProseAgent(provider, prompt_manager=prompts),
        )

    async def author_document(
        self, document_text: str, *, persist: bool = True, polish: bool = False
    ) -> DocumentCompilation:
        """Segment, extract per workflow, and author the editable master document.

        When ``polish`` is ``True`` and a prose agent is wired, each activity's
        deterministic wording is replaced by a grounded natural sentence (ungrounded
        rewrites are discarded — see :class:`IdealProseAgent`); otherwise authoring is
        fully deterministic.
        """
        segments, clarifications = await self._segmenter.segment(document_text)
        sections, checklists = await self._build_sections(segments, polish=polish)
        master = assemble_master(
            segments=segments,
            sections=sections,
            checklists=checklists,
            clarifications=clarifications,
        )
        doc = DocumentCompilation(
            source_text=document_text,
            master_document=master,
            segments=segments,
            clarifications=clarifications,
            stage=DocumentStage.AUTHORED,
        )
        if persist:
            await self._doc_store.save(doc)
        return doc

    async def reauthor(
        self, master_text: str, *, persist: bool = True, polish: bool = False
    ) -> DocumentCompilation:
        """Refine an edited master document into an updated master (another round).

        Skips segmentation — the workflows are already the ``# `` headings — and
        re-extracts each workflow from **the edited section plus the human's
        ``## Notes to the compiler`` and per-workflow ``### Guidance``**, which are fed
        to the extraction so they steer the result (the original document is not
        re-consulted). The user's notes, guidance, and open questions are preserved in
        the regenerated document so the dialogue survives across rounds.
        """
        parsed = parse_master(master_text)
        segments = [
            WorkflowSegment(
                id=f"w{i}",
                name=pw.name,
                source_text=pw.ideal_content,
                invokes=pw.invokes,
                questions=pw.open_questions,
            )
            for i, pw in enumerate(parsed.workflows, start=1)
        ]
        guidance = {seg.id: pw.guidance for seg, pw in zip(segments, parsed.workflows, strict=True)}
        # Feed the human's notes into extraction so they guide the result.
        extra = {
            seg.id: self._guidance_context(pw.guidance, parsed.global_notes)
            for seg, pw in zip(segments, parsed.workflows, strict=True)
        }
        sections, checklists = await self._build_sections(
            segments, polish=polish, extra_context=extra
        )
        master = assemble_master(
            segments=segments,
            sections=sections,
            checklists=checklists,
            clarifications=[],
            global_notes=parsed.global_notes,
            guidance=guidance,
            open_questions={seg.id: seg.questions for seg in segments},
        )
        doc = DocumentCompilation(
            source_text=master_text,
            master_document=master,
            segments=segments,
            stage=DocumentStage.AUTHORED,
        )
        if persist:
            await self._doc_store.save(doc)
        return doc

    async def _build_sections(
        self,
        segments: list[WorkflowSegment],
        *,
        polish: bool,
        extra_context: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], dict[str, WorkflowChecklist | None]]:
        """Extract each segment and render its ideal section (shared by author/reauthor).

        ``extra_context`` (keyed by segment id) is appended to the extraction text so a
        re-author round's notes/guidance steer discovery + facts. Graph/review run but
        are discarded; nothing is persisted here.
        """
        extra_context = extra_context or {}
        states = await asyncio.gather(
            *(
                self._compiler.compile_document(
                    seg.source_text + extra_context.get(seg.id, ""),
                    review_mode=True,
                    persist=False,
                    enforce_checklist=False,
                )
                for seg in segments
            )
        )
        sections: dict[str, str] = {}
        checklists: dict[str, WorkflowChecklist | None] = {}
        for seg, state in zip(segments, states, strict=True):
            descriptions = await self._describe(seg.source_text, state) if polish else None
            sections[seg.id] = render_ideal_section(
                state, name=seg.name, invokes=seg.invokes, descriptions=descriptions
            )
            checklists[seg.id] = state.checklist
        return sections, checklists

    @staticmethod
    def _guidance_context(guidance: str, global_notes: str) -> str:
        """Compose the notes appended to a section's text before re-extraction."""
        pieces = [p for p in (guidance.strip(), global_notes.strip()) if p]
        if not pieces:
            return ""
        joined = "\n".join(pieces)
        return f"\n\n## Author guidance (incorporate this into the workflow)\n{joined}\n"

    async def _describe(
        self, source_text: str, state: WorkflowState
    ) -> dict[str, str] | None:
        """Return grounded activity descriptions for the polish pass, or ``None``."""
        if self._prose is None:
            return None
        facts = state.workflow_facts
        structure = facts.structure if facts else None
        if structure is None or not structure.activities:
            return None
        names = [a.name for a in structure.activities]
        return await self._prose.describe_activities(
            activity_names=names, source_text=source_text
        )

    async def compile_authored(
        self,
        master_text: str,
        *,
        auto_approve: bool = False,
        persist: bool = True,
        document_id: str | None = None,
    ) -> tuple[DocumentCompilation, list[tuple[str, WorkflowState]]]:
        """Split the master document and compile each workflow independently.

        Returns the outer :class:`DocumentCompilation` and a list of
        ``(slug, WorkflowState)`` — one per workflow. A workflow that trips its
        readiness checklist halts at ``CHECKLISTED`` without blocking the others.
        """
        parts = split_master(master_text)
        results: list[tuple[str, WorkflowState]] = []
        for slug, doc_text in parts:
            state = await self._compiler.compile_document(
                doc_text, review_mode=not auto_approve, persist=persist, enforce_checklist=True
            )
            results.append((slug, state))

        doc = DocumentCompilation(
            source_text=master_text,
            master_document=master_text,
            workflow_ids=[state.workflow_id for _, state in results],
            stage=DocumentStage.COMPLETED,
        )
        if document_id is not None:
            doc.document_id = document_id
        if persist:
            await self._doc_store.save(doc)
        return doc, results

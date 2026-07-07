"""WorkflowSegmentationAgent: discover every workflow in a document and slice it.

This is the spec-centric front-end's first stage. Where
:class:`~workflow_compiler.agents.discovery.WorkflowDiscoveryAgent` extracts one
workflow's metadata, this agent enumerates **every** distinct workflow the
document describes, which document sections belong to each, and any typed
output→input dependencies between them. Deterministic code then assembles each
workflow's document slice (a :class:`WorkflowSegment`) so downstream fact
extraction sees only its own workflow's text — the scope-isolation win.

The agent operates on raw document text (not a ``WorkflowState``): it belongs to
the project level, above the per-workflow pipeline. Its LLM output is optionally
improved by the same three-pass review discipline as the other LLM stages
(completeness → grounding → consistency), reusing :class:`ReviewPass` and the
patch vocabulary with a deterministic :class:`SegmentationPatchApplier`.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.agents.review_pipeline import (
    ReviewPass,
    _grounded,
    _norm,
    _payload_value,
)
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    CrossReference,
    Patch,
    PatchAction,
    ReviewResult,
    WorkflowSegment,
)
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "discover_workflows"
_SYSTEM = (
    "You are a precise business-process analyst. Identify only workflows the "
    "document supports and respond with strict JSON."
)
_REVIEW_SYSTEM = (
    "You are a meticulous reviewer in a deterministic compiler. You never rewrite "
    "the artifact. You emit only minimal patches that are explicitly supported by "
    "the document, or an empty patch list / a single no_change patch when nothing "
    "needs to change. Respond with strict JSON."
)

_REVIEW_PASSES: tuple[ReviewPass, ...] = (
    ReviewPass("review_segmentation_completeness", "completeness"),
    ReviewPass("review_segmentation_grounding", "grounding"),
    ReviewPass("review_segmentation_consistency", "consistency"),
)


# --------------------------------------------------------------------------- #
# LLM output schemas (permissive, like the other agents' output models)
# --------------------------------------------------------------------------- #


class DiscoveredWorkflow(BaseModel):
    """One workflow the model found, with its claimed document coverage."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    purpose: str = Field(default="")
    section_titles: list[str] = Field(default_factory=list)
    excerpt_start: str = Field(default="")
    excerpt_end: str = Field(default="")
    confidence: float = Field(default=0.5)


class DiscoveredDependency(BaseModel):
    """An output→input link between two discovered workflows."""

    model_config = ConfigDict(extra="ignore")

    source_workflow: str = Field(default="")
    output_field: str = Field(default="")
    target_workflow: str = Field(default="")
    input_field: str = Field(default="")
    description: str = Field(default="")


class WorkflowsDiscovery(BaseModel):
    """Structured LLM output: every workflow plus cross-workflow dependencies."""

    model_config = ConfigDict(extra="ignore")

    workflows: list[DiscoveredWorkflow] = Field(default_factory=list)
    dependencies: list[DiscoveredDependency] = Field(default_factory=list)
    confidence: float = Field(default=0.5)


# --------------------------------------------------------------------------- #
# Deterministic helpers: slugs, section splitting, segment assembly
# --------------------------------------------------------------------------- #


def slugify(name: str) -> str:
    """Reduce ``name`` to a filename-safe kebab-case slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "workflow"


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class _Section:
    """One heading-delimited slice of the document (title '' = preamble)."""

    title: str
    start: int  # offset of the heading line (or 0 for the preamble)
    end: int  # exclusive offset where the next section begins


def _split_sections(text: str) -> list[_Section]:
    """Split ``text`` into heading-delimited sections, preamble first."""
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [_Section(title="", start=0, end=len(text))]
    sections: list[_Section] = []
    if matches[0].start() > 0:
        sections.append(_Section(title="", start=0, end=matches[0].start()))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(_Section(title=match.group(2), start=match.start(), end=end))
    return sections


def _title_key(title: str) -> str:
    """Normalize a heading for matching: lowercase alphanumeric words only."""
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def _titles_match(a: str, b: str) -> bool:
    """True when two normalized headings are equal or one contains the other."""
    if not a or not b:
        return False
    return a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a)


def _find_anchor(document: str, needle: str) -> int:
    """Best-effort locate ``needle`` in ``document``; -1 when not found."""
    cleaned = needle.strip()
    if not cleaned:
        return -1
    idx = document.find(cleaned)
    if idx == -1 and len(cleaned) > 60:
        idx = document.find(cleaned[:60].strip())
    return idx


# --------------------------------------------------------------------------- #
# Deterministic patch applier for the segmentation review passes
# --------------------------------------------------------------------------- #


class SegmentationPatchApplier:
    """Fold review patches into a :class:`WorkflowsDiscovery`, deterministically.

    Patches address workflows by name (``workflow:<name>``; ``add`` uses the bare
    target ``workflow``). An ``add`` whose name already exists or is not grounded
    in the document is dropped — the same idempotency/anti-hallucination rule as
    the other appliers. ``merge`` keeps the first-named workflow, unions the
    section titles, and repoints dependencies from the dropped name.
    """

    def apply(
        self, artifact: object, patches: list[Patch], document_text: str
    ) -> tuple[WorkflowsDiscovery, str]:
        assert isinstance(artifact, WorkflowsDiscovery)
        discovery = artifact.model_copy(deep=True)
        applied = dropped = flagged = 0

        for patch in patches:
            if patch.action == PatchAction.FLAG:
                flagged += 1
                continue
            ok = self._apply_one(patch, discovery, document_text)
            applied += int(ok)
            dropped += int(not ok)

        return discovery, f"{applied} applied, {dropped} dropped, {flagged} flagged"

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _index_by_name(workflows: list[DiscoveredWorkflow], name: str) -> int:
        low = _norm(name).lower()
        return next((i for i, w in enumerate(workflows) if _norm(w.name).lower() == low), -1)

    def _apply_one(
        self, patch: Patch, discovery: WorkflowsDiscovery, document_text: str
    ) -> bool:
        kind, _, ref = patch.target.partition(":")
        if kind.strip().lower() != "workflow":
            return False
        ref = ref.strip()
        workflows = discovery.workflows

        if patch.action == PatchAction.ADD:
            name = _payload_value(patch, "name", "value")
            if not name or self._index_by_name(workflows, name) != -1:
                return False
            if not _grounded(name, patch.evidence, document_text):
                return False
            raw_titles = patch.payload.get("section_titles", [])
            titles = (
                [_norm(t) for t in raw_titles if _norm(t)]
                if isinstance(raw_titles, list)
                else []
            )
            workflows.append(
                DiscoveredWorkflow(
                    name=name,
                    purpose=_payload_value(patch, "purpose"),
                    section_titles=titles,
                )
            )
            return True

        if patch.action == PatchAction.REMOVE:
            idx = self._index_by_name(workflows, ref)
            if idx == -1:
                return False
            removed = workflows.pop(idx)
            low = _norm(removed.name).lower()
            discovery.dependencies = [
                d
                for d in discovery.dependencies
                if _norm(d.source_workflow).lower() != low
                and _norm(d.target_workflow).lower() != low
            ]
            return True

        if patch.action == PatchAction.MODIFY:
            idx = self._index_by_name(workflows, ref)
            if idx == -1:
                return False
            allowed = ("name", "purpose", "section_titles", "excerpt_start", "excerpt_end")
            updates: dict[str, object] = {}
            for key in allowed:
                if key not in patch.payload:
                    continue
                value = patch.payload[key]
                if key == "section_titles" and isinstance(value, list):
                    updates[key] = [_norm(t) for t in value if _norm(t)]
                elif isinstance(value, str) and _norm(value):
                    updates[key] = _norm(value)
            if not updates:
                return False
            workflows[idx] = workflows[idx].model_copy(update=updates)
            return True

        if patch.action == PatchAction.MERGE:
            keep_name, _, drop_name = ref.partition("+")
            keep = self._index_by_name(workflows, keep_name)
            drop = self._index_by_name(workflows, drop_name)
            if keep == -1 or drop == -1 or keep == drop:
                return False
            kept, dropped_wf = workflows[keep], workflows[drop]
            titles = list(kept.section_titles)
            for title in dropped_wf.section_titles:
                if _title_key(title) not in {_title_key(t) for t in titles}:
                    titles.append(title)
            workflows[keep] = kept.model_copy(update={"section_titles": titles})
            workflows.pop(drop)
            drop_low = _norm(dropped_wf.name).lower()
            for dep in discovery.dependencies:
                if _norm(dep.source_workflow).lower() == drop_low:
                    dep.source_workflow = kept.name
                if _norm(dep.target_workflow).lower() == drop_low:
                    dep.target_workflow = kept.name
            return True

        return False


# --------------------------------------------------------------------------- #
# The agent
# --------------------------------------------------------------------------- #


class WorkflowSegmentationAgent:
    """Discover every workflow in a document and assemble per-workflow segments.

    Not a :class:`BaseAgent`: it consumes raw document text and produces
    project-level artifacts (segments + cross-references), sitting above the
    per-workflow ``WorkflowState`` pipeline.
    """

    name = "workflow-segmentation"

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
        review_enabled: bool = True,
    ) -> None:
        """Store the provider, prompts, and whether the review passes run."""
        self._llm = llm
        self._prompts = prompt_manager or PromptManager()
        self._review_enabled = review_enabled
        self._applier = SegmentationPatchApplier()
        #: Optional nested progress reporter (same contract as ReviewPipelineAgent).
        self._report: Callable[..., None] | None = None

    def set_progress(self, report: Callable[..., None] | None) -> None:
        """Receive (or clear) a nested progress reporter for the inner steps."""
        self._report = report

    def _emit(self, name: str, status: str, index: int, total: int, **extra: object) -> None:
        if self._report is not None:
            self._report(name, status, index, total, **extra)

    async def run(
        self, document_text: str
    ) -> tuple[list[WorkflowSegment], list[CrossReference], list[str]]:
        """Discover workflows, review the discovery, and assemble segments.

        Returns ``(segments, cross_references, warnings)``. A document that
        describes a single workflow yields one segment holding the full document
        text, so the single-workflow path is byte-identical to compiling the
        document directly.
        """
        if self._llm is None:
            raise CompilationError("WorkflowSegmentationAgent requires an LLM provider.")
        if not document_text or not document_text.strip():
            raise CompilationError("Cannot segment an empty document.")

        steps = 1 + (len(_REVIEW_PASSES) if self._review_enabled else 0)
        self._emit("discover", "start", 1, steps)
        started = time.perf_counter()
        prompt = self._prompts.render(_PROMPT_NAME, document_text=document_text)
        discovery = await self._llm.structured(prompt, WorkflowsDiscovery, system=_SYSTEM)
        self._emit("discover", "done", 1, steps, seconds=time.perf_counter() - started)

        if self._review_enabled:
            discovery = await self._review(discovery, document_text, steps)

        return self.assemble(discovery, document_text)

    async def _review(
        self, discovery: WorkflowsDiscovery, document_text: str, steps: int
    ) -> WorkflowsDiscovery:
        """Run the three sequential review passes over the discovery."""
        assert self._llm is not None
        for offset, review_pass in enumerate(_REVIEW_PASSES, start=2):
            self._emit(f"review:{review_pass.label}", "start", offset, steps)
            pass_started = time.perf_counter()
            serialized = discovery.model_dump_json(indent=2)
            prompt = self._prompts.render(
                review_pass.prompt_name, document_text=document_text, current=serialized
            )
            result = await self._llm.structured(prompt, ReviewResult, system=_REVIEW_SYSTEM)
            discovery, _provenance = self._applier.apply(
                discovery, result.effective_patches(), document_text
            )
            self._emit(
                f"review:{review_pass.label}", "done", offset, steps,
                seconds=time.perf_counter() - pass_started,
            )
        return discovery

    # -- deterministic assembly ----------------------------------------------

    def assemble(
        self, discovery: WorkflowsDiscovery, document_text: str
    ) -> tuple[list[WorkflowSegment], list[CrossReference], list[str]]:
        """Deterministically slice the document per discovered workflow."""
        workflows = [w for w in discovery.workflows if _norm(w.name)]
        if not workflows:
            raise CompilationError("Workflow discovery found no workflows in the document.")

        warnings: list[str] = []
        sections = _split_sections(document_text)
        segments: list[WorkflowSegment] = []
        used_slugs: set[str] = set()

        for index, workflow in enumerate(workflows, start=1):
            slug = slugify(workflow.name)
            if slug in used_slugs:
                slug = f"{slug}-{index}"
            used_slugs.add(slug)

            if len(workflows) == 1:
                text = document_text
            else:
                text = self._segment_text(workflow, sections, document_text, warnings)

            segments.append(
                WorkflowSegment(
                    id=f"w{index}",
                    slug=slug,
                    name=_norm(workflow.name),
                    purpose=_norm(workflow.purpose) or None,
                    section_titles=[_norm(t) for t in workflow.section_titles if _norm(t)],
                    text=text,
                )
            )

        slug_by_name = {_norm(s.name).lower(): s.slug for s in segments}
        cross_references: list[CrossReference] = []
        for dep in discovery.dependencies:
            source = slug_by_name.get(_norm(dep.source_workflow).lower())
            target = slug_by_name.get(_norm(dep.target_workflow).lower())
            if source is None or target is None or source == target:
                warnings.append(
                    "Dependency "
                    f"'{dep.source_workflow} -> {dep.target_workflow}' references an "
                    "unknown workflow — dropped."
                )
                continue
            if not (_norm(dep.output_field) and _norm(dep.input_field)):
                warnings.append(
                    f"Dependency '{source} -> {target}' is missing field names — dropped."
                )
                continue
            cross_references.append(
                CrossReference(
                    source_workflow=source,
                    output_field=_norm(dep.output_field),
                    target_workflow=target,
                    input_field=_norm(dep.input_field),
                    description=_norm(dep.description) or None,
                )
            )

        return segments, cross_references, warnings

    @staticmethod
    def _segment_text(
        workflow: DiscoveredWorkflow,
        sections: list[_Section],
        document_text: str,
        warnings: list[str],
    ) -> str:
        """Assemble one workflow's text from matched sections or excerpt anchors."""
        wanted = [_title_key(t) for t in workflow.section_titles if _title_key(t)]
        matched = [
            s
            for s in sections
            if s.title and any(_titles_match(_title_key(s.title), w) for w in wanted)
        ]
        if matched:
            return "\n".join(document_text[s.start : s.end].rstrip() for s in matched) + "\n"

        start = _find_anchor(document_text, workflow.excerpt_start)
        end = _find_anchor(document_text, workflow.excerpt_end)
        if start != -1 and end != -1 and end >= start:
            line_start = document_text.rfind("\n", 0, start) + 1
            line_end = document_text.find("\n", end)
            line_end = len(document_text) if line_end == -1 else line_end
            return document_text[line_start:line_end] + "\n"

        warnings.append(
            f"Could not locate document sections for workflow '{workflow.name}' — "
            "using the full document as its segment."
        )
        return document_text

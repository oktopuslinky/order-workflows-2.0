"""Sequential review pipelines: generate once, then review in three passes.

This is the compiler-style alternative to the consensus-merge ensemble
(:mod:`workflow_compiler.agents.ensemble`). Where the ensemble runs a stage N
times and merges the candidates, a review pipeline runs the stage **once** to
produce a canonical output and then improves it with three specialized,
sequential review passes:

1. **completeness** — add elements explicitly in the document but missing;
2. **grounding** — remove/flag elements not supported by the document;
3. **consistency** — merge duplicates, rename to a canonical label, fix relations.

Each pass emits **minimal patches or ``no_change``** (never a full rewrite), and a
deterministic *applier* folds those patches into the artifact. Because the passes
only ever request minimal, grounded edits and the appliers drop duplicates /
ungrounded additions, the passes are **idempotent**: re-running a pass over an
already-reviewed artifact returns ``no_change``.

The machinery is generic. A concrete stage is described by a :class:`ReviewSpec`
(how to extract / serialize / apply the artifact, plus its three prompts and its
applier), exactly mirroring the ensemble's :class:`~workflow_compiler.agents.ensemble.StageSpec`.
Adding a review pipeline for a future stage (Mermaid, Temporal) is a new spec —
no engine changes.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    ActivityNode,
    CompensationNode,
    ConfidenceScores,
    DecisionNode,
    EventNode,
    ExceptionNode,
    FactCategory,
    Patch,
    PatchAction,
    ReviewResult,
    WorkflowFact,
    WorkflowFacts,
    WorkflowMetadata,
    WorkflowState,
    WorkflowStructure,
)
from workflow_compiler.models.patch import Evidence
from workflow_compiler.prompts import PromptManager

_REVIEW_SYSTEM = (
    "You are a meticulous reviewer in a deterministic compiler. You never rewrite "
    "the artifact. You emit only minimal patches that are explicitly supported by "
    "the document, or an empty patch list / a single no_change patch when nothing "
    "needs to change. Every non-no_change patch must cite evidence from the document. "
    "Respond with strict JSON."
)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _norm(text: object) -> str:
    """Collapse whitespace and strip surrounding quotes / trailing periods."""
    out = " ".join(str(text or "").split())
    previous = ""
    while out != previous:
        previous = out
        out = out.strip().strip("\"'").rstrip(".").strip()
    return out


def _grounded(text: str, evidence: Evidence | None, document_text: str) -> bool:
    """Deterministic, reference-free grounding check for an added element.

    Accept the addition when its supporting quote is a literal substring of the
    document, or when a clear majority of the element's significant words appear
    in the document. This is the same family of signal the ensemble uses; it
    cannot certify truth but it filters obvious hallucinations and is what makes
    the completeness pass idempotent and safe.
    """
    doc = document_text.lower()
    if evidence is not None and evidence.quote:
        quote = _norm(evidence.quote).lower()
        if quote and quote in doc:
            return True
    needle = _norm(text).lower()
    if not needle:
        return False
    words = [w for w in re.findall(r"[a-z0-9]+", needle) if len(w) > 2]
    if not words:
        return needle in doc
    hits = sum(1 for w in words if w in doc)
    return hits / len(words) >= 0.6


def _payload_value(patch: Patch, *keys: str) -> str:
    """Return the first present payload value among ``keys`` (normalized)."""
    for key in keys:
        if key in patch.payload and patch.payload[key] not in (None, ""):
            return _norm(patch.payload[key])
    return ""


# --------------------------------------------------------------------------- #
# Patch appliers (deterministic, pure)
# --------------------------------------------------------------------------- #


class PatchApplier(Protocol):
    """Folds a list of patches into an artifact, deterministically.

    Implementations must be pure (no I/O), must drop patches that would create a
    duplicate or that are not grounded in the document, and must return a short
    provenance summary describing what they did.
    """

    def apply(
        self, artifact: object, patches: list[Patch], document_text: str
    ) -> tuple[object, str]:
        """Return ``(new_artifact, provenance_summary)``."""
        ...


_METADATA_LIST_FIELDS = (
    "actors",
    "systems",
    "trigger_events",
    "start_states",
    "end_states",
    "tags",
)
_METADATA_SCALAR_FIELDS = ("name", "purpose", "description", "domain", "owner")


class MetadataPatchApplier:
    """Apply patches to a :class:`WorkflowMetadata` (the workflow-discovery artifact).

    List fields (actors/systems/triggers/states) accept add/remove/modify/merge;
    scalar fields (name/purpose) accept modify. ``flag`` only records a note. An
    ``add`` whose value already exists (case-insensitively) or is not grounded in
    the document is dropped — which is exactly what makes the pass idempotent.
    """

    def apply(
        self, artifact: object, patches: list[Patch], document_text: str
    ) -> tuple[WorkflowMetadata, str]:
        assert isinstance(artifact, WorkflowMetadata)
        data = artifact.model_dump()
        applied = dropped = flagged = 0

        for patch in patches:
            field = patch.target.strip()
            if patch.action == PatchAction.FLAG:
                flagged += 1
                continue
            if field in _METADATA_LIST_FIELDS:
                items: list[str] = list(data.get(field) or [])
                changed = self._apply_list(patch, items, document_text)
                if changed:
                    data[field] = items
                    applied += 1
                else:
                    dropped += 1
            elif field in _METADATA_SCALAR_FIELDS and patch.action == PatchAction.MODIFY:
                value = _payload_value(patch, "value", "new", "to")
                if value and _grounded(value, patch.evidence, document_text):
                    data[field] = value
                    applied += 1
                else:
                    dropped += 1
            else:
                dropped += 1

        return WorkflowMetadata.model_validate(data), (
            f"{applied} applied, {dropped} dropped, {flagged} flagged"
        )

    @staticmethod
    def _index_ci(items: list[str], value: str) -> int:
        low = value.lower()
        for i, item in enumerate(items):
            if item.lower() == low:
                return i
        return -1

    def _apply_list(self, patch: Patch, items: list[str], document_text: str) -> bool:
        """Mutate ``items`` in place; return True if anything changed."""
        if patch.action == PatchAction.ADD:
            value = _payload_value(patch, "value", "item", "name")
            if not value or self._index_ci(items, value) != -1:
                return False
            if not _grounded(value, patch.evidence, document_text):
                return False
            items.append(value)
            return True
        if patch.action == PatchAction.REMOVE:
            value = _payload_value(patch, "value", "item", "name")
            idx = self._index_ci(items, value)
            if idx == -1:
                return False
            items.pop(idx)
            return True
        if patch.action == PatchAction.MODIFY:
            old = _payload_value(patch, "old", "from", "value")
            new = _payload_value(patch, "new", "to")
            idx = self._index_ci(items, old)
            if idx == -1 or not new:
                return False
            if self._index_ci(items, new) not in (-1, idx):
                items.pop(idx)  # target already present → collapse duplicate
                return True
            items[idx] = new
            return True
        if patch.action == PatchAction.MERGE:
            sources = [_norm(v) for v in patch.payload.get("values", []) if _norm(v)]
            canonical = _payload_value(patch, "into", "canonical") or (
                sources[0] if sources else ""
            )
            if not canonical or not sources:
                return False
            changed = False
            for src in sources:
                idx = self._index_ci(items, src)
                if idx != -1:
                    items.pop(idx)
                    changed = True
            if self._index_ci(items, canonical) == -1:
                items.append(canonical)
            return changed
        return False


#: Categories whose canonical home is the flat fact list (not the structure).
_SCALAR_CATEGORIES: dict[str, FactCategory] = {
    "input": FactCategory.INPUT,
    "output": FactCategory.OUTPUT,
    "rule": FactCategory.RULE,
    "api": FactCategory.API,
    "system": FactCategory.SYSTEM,
    "timer": FactCategory.TIMER,
    "retry": FactCategory.RETRY,
}

#: Structure entity kinds and the id prefix used when minting a new id.
_ENTITY_PREFIX = {
    "activity": "a",
    "decision": "d",
    "exception": "e",
    "compensation": "c",
    "event": "v",
}


def _next_id(prefix: str, existing: set[str]) -> str:
    """Mint the next ``<prefix><n>`` id not already used."""
    n = 1
    while f"{prefix}{n}" in existing:
        n += 1
    return f"{prefix}{n}"


def rebuild_facts(structure: WorkflowStructure, scalar: list[WorkflowFact]) -> WorkflowFacts:
    """Re-derive a :class:`WorkflowFacts` from a structure + scalar facts.

    The relational categories (activities, decisions, …) are projected from the
    validated structure; the scalar categories (inputs, rules, …) are carried
    over from the existing flat facts. This mirrors
    :meth:`FactExtractionAgent._facts_from_structure` so downstream consumers see
    the same shape, and it re-runs :meth:`WorkflowStructure.validated` so any
    relation a patch left dangling is dropped.
    """
    structure, _ = structure.validated()
    activity_name = {a.id: a.name for a in structure.activities}
    compensations = [
        (f"{c.name} compensates {activity_name[c.compensates]}"
         if c.compensates in activity_name else c.name)
        for c in structure.compensations
    ]
    scalar_by_cat: dict[FactCategory, list[str]] = {}
    for fact in scalar:
        scalar_by_cat.setdefault(fact.category, []).append(fact.statement)

    ordered: list[tuple[FactCategory, list[str]]] = [
        (FactCategory.INPUT, scalar_by_cat.get(FactCategory.INPUT, [])),
        (FactCategory.OUTPUT, scalar_by_cat.get(FactCategory.OUTPUT, [])),
        (FactCategory.ACTIVITY, [a.name for a in structure.activities]),
        (FactCategory.DECISION, [d.question for d in structure.decisions]),
        (FactCategory.RULE, scalar_by_cat.get(FactCategory.RULE, [])),
        (FactCategory.EVENT, [v.name for v in structure.events]),
        (FactCategory.API, scalar_by_cat.get(FactCategory.API, [])),
        (FactCategory.SYSTEM, scalar_by_cat.get(FactCategory.SYSTEM, [])),
        (FactCategory.EXCEPTION, [x.reason for x in structure.exceptions]),
        (
            FactCategory.STATE_TRANSITION,
            [f"{t.source} -> {t.target}" for t in structure.transitions],
        ),
        (FactCategory.TIMER, scalar_by_cat.get(FactCategory.TIMER, [])),
        (FactCategory.RETRY, scalar_by_cat.get(FactCategory.RETRY, [])),
        (FactCategory.COMPENSATION, compensations),
    ]

    facts: list[WorkflowFact] = []
    for category, raw_items in ordered:
        seen: set[str] = set()
        index = 0
        for raw in raw_items:
            statement = _norm(raw)
            key = statement.lower()
            if not statement or key in seen:
                continue
            seen.add(key)
            index += 1
            facts.append(
                WorkflowFact(
                    id=f"{category.value}-{index}",
                    statement=statement,
                    category=category,
                    confidence=0.6,
                )
            )
    return WorkflowFacts(facts=facts, structure=structure)


class FactsPatchApplier:
    """Apply patches to a :class:`WorkflowFacts` (the fact-discovery artifact).

    Patches address either a structure entity (``activity:a3``), a flat scalar
    category (``rule``), or — for ``merge`` — two ids (``a2+a5``). After applying,
    the facts are rebuilt via :func:`rebuild_facts`, which re-runs the referential
    integrity guard so links can only point at declared entities. ``add`` of an
    entity whose normalized name already exists, or that is not grounded, is
    dropped (idempotency + anti-hallucination).
    """

    def apply(
        self, artifact: object, patches: list[Patch], document_text: str
    ) -> tuple[WorkflowFacts, str]:
        assert isinstance(artifact, WorkflowFacts)
        structure = (artifact.structure or WorkflowStructure()).model_copy(deep=True)
        scalar = [f for f in artifact.facts if f.category in _SCALAR_CATEGORIES.values()]
        applied = dropped = flagged = 0

        for patch in patches:
            kind, _, ref = patch.target.partition(":")
            kind = kind.strip().lower()
            ref = ref.strip()
            if patch.action == PatchAction.FLAG:
                flagged += 1
                continue
            if kind in _ENTITY_PREFIX:
                ok = self._apply_entity(kind, ref, patch, structure, document_text)
            elif kind in _SCALAR_CATEGORIES:
                ok = self._apply_scalar(_SCALAR_CATEGORIES[kind], patch, scalar, document_text)
            else:
                ok = False
            applied += int(ok)
            dropped += int(not ok)

        rebuilt = rebuild_facts(structure, scalar)
        return rebuilt, f"{applied} applied, {dropped} dropped, {flagged} flagged"

    # -- structure entities -------------------------------------------------

    @staticmethod
    def _entity_list(kind: str, structure: WorkflowStructure) -> list:
        return {
            "activity": structure.activities,
            "decision": structure.decisions,
            "exception": structure.exceptions,
            "compensation": structure.compensations,
            "event": structure.events,
        }[kind]

    @staticmethod
    def _entity_label(kind: str, node: object) -> str:
        if isinstance(node, DecisionNode):
            return node.question
        if isinstance(node, ExceptionNode):
            return node.reason
        return getattr(node, "name", "")

    def _apply_entity(
        self,
        kind: str,
        ref: str,
        patch: Patch,
        structure: WorkflowStructure,
        document_text: str,
    ) -> bool:
        items = self._entity_list(kind, structure)

        if patch.action == PatchAction.ADD:
            return self._add_entity(kind, patch, structure, document_text)
        if patch.action == PatchAction.REMOVE:
            idx = next((i for i, n in enumerate(items) if n.id == ref), -1)
            if idx == -1:
                return False
            items.pop(idx)
            return True
        if patch.action == PatchAction.MODIFY:
            idx = next((i for i, n in enumerate(items) if n.id == ref), -1)
            if idx == -1:
                return False
            updates = {k: _norm(v) if isinstance(v, str) else v
                       for k, v in patch.payload.items()
                       if k in items[idx].model_fields and k != "id"}
            if not updates:
                return False
            items[idx] = items[idx].model_copy(update=updates)
            return True
        if patch.action == PatchAction.MERGE:
            keep, _, drop = ref.partition("+")
            return self._merge_entities(kind, keep.strip(), drop.strip(), structure)
        return False

    def _add_entity(
        self,
        kind: str,
        patch: Patch,
        structure: WorkflowStructure,
        document_text: str,
    ) -> bool:
        items = self._entity_list(kind, structure)
        existing_ids = {n.id for n in items}
        label_key = {"decision": ("question",), "exception": ("reason",)}.get(kind, ("name",))
        label = _payload_value(patch, *label_key, "value")
        if not label or not _grounded(label, patch.evidence, document_text):
            return False
        if any(self._entity_label(kind, n).lower() == label.lower() for n in items):
            return False  # idempotent: already present
        new_id = _norm(patch.payload.get("id", "")) or _next_id(_ENTITY_PREFIX[kind], existing_ids)
        if new_id in existing_ids:
            new_id = _next_id(_ENTITY_PREFIX[kind], existing_ids)
        p = patch.payload
        node: object
        if kind == "activity":
            node = ActivityNode(id=new_id, name=label,
                                parallel_group=_norm(p.get("parallel_group")) or None)
        elif kind == "decision":
            node = DecisionNode(id=new_id, question=label,
                                after=_norm(p.get("after")) or None,
                                yes_target=_norm(p.get("yes_target")) or None,
                                no_target=_norm(p.get("no_target")) or None)
        elif kind == "exception":
            node = ExceptionNode(id=new_id, reason=label,
                                 raised_by=_norm(p.get("raised_by")) or None)
        elif kind == "compensation":
            node = CompensationNode(id=new_id, name=label,
                                    compensates=_norm(p.get("compensates")) or None)
        else:  # event
            node = EventNode(id=new_id, name=label,
                             emitted_by=_norm(p.get("emitted_by")) or None)
        items.append(node)
        return True

    def _merge_entities(
        self, kind: str, keep: str, drop: str, structure: WorkflowStructure
    ) -> bool:
        items = self._entity_list(kind, structure)
        ids = {n.id for n in items}
        if not keep or drop not in ids or keep not in ids or keep == drop:
            return False  # idempotent: nothing to merge
        # Drop the merged-away node.
        kept = [n for n in items if n.id != drop]
        items.clear()
        items.extend(kept)
        # Repoint every reference from the dropped id to the kept id.
        if kind == "activity":
            for d in structure.decisions:
                self._repoint(d, ("after", "yes_target", "no_target"), drop, keep)
            for x in structure.exceptions:
                self._repoint(x, ("raised_by",), drop, keep)
            for c in structure.compensations:
                self._repoint(c, ("compensates",), drop, keep)
            for v in structure.events:
                self._repoint(v, ("emitted_by",), drop, keep)
        elif kind in ("exception", "event"):
            for d in structure.decisions:
                self._repoint(d, ("yes_target", "no_target"), drop, keep)
        return True

    @staticmethod
    def _repoint(node: object, fields: tuple[str, ...], drop: str, keep: str) -> None:
        for field in fields:
            if getattr(node, field, None) == drop:
                setattr(node, field, keep)

    # -- flat scalar facts --------------------------------------------------

    def _apply_scalar(
        self,
        category: FactCategory,
        patch: Patch,
        scalar: list[WorkflowFact],
        document_text: str,
    ) -> bool:
        in_cat = [f for f in scalar if f.category == category]

        def index_ci(value: str) -> int:
            low = value.lower()
            return next((i for i, f in enumerate(scalar)
                         if f.category == category and f.statement.lower() == low), -1)

        if patch.action == PatchAction.ADD:
            value = _payload_value(patch, "value", "statement", "name")
            if not value or index_ci(value) != -1:
                return False
            if not _grounded(value, patch.evidence, document_text):
                return False
            scalar.append(
                WorkflowFact(
                    id=f"{category.value}-{len(in_cat) + 1}",
                    statement=value,
                    category=category,
                    confidence=0.6,
                )
            )
            return True
        if patch.action == PatchAction.REMOVE:
            idx = index_ci(_payload_value(patch, "value", "statement", "name"))
            if idx == -1:
                return False
            scalar.pop(idx)
            return True
        if patch.action == PatchAction.MODIFY:
            old = _payload_value(patch, "old", "from", "value", "statement")
            new = _payload_value(patch, "new", "to")
            idx = index_ci(old)
            if idx == -1 or not new:
                return False
            scalar[idx] = scalar[idx].model_copy(update={"statement": new})
            return True
        return False


# --------------------------------------------------------------------------- #
# Review passes, spec, and the engine
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReviewPass:
    """One review pass: a prompt + the deterministic patches it produces."""

    prompt_name: str
    label: str

    async def run(
        self,
        provider: BaseLLMProvider,
        prompts: PromptManager,
        document_text: str,
        current: str,
    ) -> ReviewResult:
        """Render the pass prompt and return the model's :class:`ReviewResult`."""
        prompt = prompts.render(self.prompt_name, document_text=document_text, current=current)
        return await provider.structured(prompt, ReviewResult, system=_REVIEW_SYSTEM)


@dataclass(frozen=True)
class ReviewSpec:
    """Binds a generic review pipeline to a concrete artifact (mirrors StageSpec)."""

    note_key: str
    extract: Callable[[WorkflowState], object | None]
    serialize: Callable[[object], str]
    apply_to_state: Callable[[WorkflowState, object], None]
    applier: PatchApplier
    passes: tuple[ReviewPass, ...]


class ReviewPipelineAgent(BaseAgent):
    """Generate a canonical artifact, then improve it with sequential review passes."""

    def __init__(
        self,
        *,
        inner_factory: Callable[[BaseLLMProvider], BaseAgent],
        provider: BaseLLMProvider,
        spec: ReviewSpec,
        prompt_manager: PromptManager | None = None,
        name: str | None = None,
    ) -> None:
        """Wrap an inner generator agent with the three-pass review pipeline."""
        super().__init__(provider)
        self._inner_factory = inner_factory
        self._provider = provider
        self._spec = spec
        self._prompts = prompt_manager or PromptManager()
        self.name = name or f"review-pipeline:{spec.note_key}"
        #: Optional nested progress reporter set by the compiler's ``_run_agents``;
        #: signature ``report(name, status, index, total, *, seconds=?, stage=?)``.
        self._report: Callable[..., None] | None = None

    def set_progress(self, report: Callable[..., None] | None) -> None:
        """Receive (or clear) a nested progress reporter for the inner steps.

        The compiler calls this around :meth:`run` so the canonical generation and
        each review pass appear as their own timed lines in the live step log.
        """
        self._report = report

    def _emit(self, name: str, status: str, index: int, total: int, **extra: object) -> None:
        if self._report is not None:
            self._report(name, status, index, total, **extra)

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Run the inner generator once, then completeness → grounding → consistency."""
        if self._provider is None:
            raise CompilationError(f"{self.name} requires an LLM provider.")

        # Step 1 of N: the single canonical generation.
        steps = len(self._spec.passes) + 1
        self._emit("generate", "start", 1, steps)
        started = time.perf_counter()
        state = await self._inner_factory(self._provider).run(state)
        self._emit(
            "generate", "done", 1, steps,
            seconds=time.perf_counter() - started, stage=state.stage.value,
        )

        artifact = self._spec.extract(state)
        if artifact is None:
            return state

        # Steps 2..N: the sequential review passes, each emitting its own line.
        notes: list[str] = []
        for offset, review_pass in enumerate(self._spec.passes, start=2):
            self._emit(f"review:{review_pass.label}", "start", offset, steps)
            pass_started = time.perf_counter()
            serialized = self._spec.serialize(artifact)
            result = await review_pass.run(
                self._provider, self._prompts, state.document_text, serialized
            )
            artifact, provenance = self._spec.applier.apply(
                artifact, result.effective_patches(), state.document_text
            )
            notes.append(f"{review_pass.label}: {provenance}")
            self._emit(
                f"review:{review_pass.label}", "done", offset, steps,
                seconds=time.perf_counter() - pass_started,
            )

        self._spec.apply_to_state(state, artifact)
        scores = state.confidence_scores or ConfidenceScores()
        merged = {**scores.notes, self._spec.note_key: "; ".join(notes)}
        state.confidence_scores = scores.model_copy(update={"notes": merged})
        state.touch()
        return state


# --------------------------------------------------------------------------- #
# Ready-made specs for the two LLM discovery stages
# --------------------------------------------------------------------------- #


def _metadata_apply(state: WorkflowState, artifact: object) -> None:
    assert isinstance(artifact, WorkflowMetadata)
    state.workflow_metadata = artifact


def _facts_apply(state: WorkflowState, artifact: object) -> None:
    assert isinstance(artifact, WorkflowFacts)
    state.workflow_facts = artifact


METADATA_REVIEW_SPEC = ReviewSpec(
    note_key="metadata_review",
    extract=lambda s: s.workflow_metadata,
    serialize=lambda a: a.model_dump_json(indent=2, exclude_none=True),
    apply_to_state=_metadata_apply,
    applier=MetadataPatchApplier(),
    passes=(
        ReviewPass("review_workflow_completeness", "completeness"),
        ReviewPass("review_workflow_grounding", "grounding"),
        ReviewPass("review_workflow_consistency", "consistency"),
    ),
)

FACTS_REVIEW_SPEC = ReviewSpec(
    note_key="facts_review",
    extract=lambda s: s.workflow_facts,
    serialize=lambda a: a.model_dump_json(indent=2, exclude_none=True),
    apply_to_state=_facts_apply,
    applier=FactsPatchApplier(),
    passes=(
        ReviewPass("review_facts_completeness", "completeness"),
        ReviewPass("review_facts_grounding", "grounding"),
        ReviewPass("review_facts_consistency", "consistency"),
    ),
)

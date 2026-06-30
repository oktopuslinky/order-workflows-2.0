"""Consensus merge of ensemble candidates (reference-free).

When discovery / fact extraction is run N times, each candidate proposes a set of
*parts*. These mergers combine the parts across candidates rather than picking one
winner, using only **reference-free** signals (no gold answer exists for an
arbitrary document):

* **agreement** — how many candidates proposed a part (the vote count);
* **referential integrity** — :meth:`WorkflowStructure.validated` drops dangling /
  leaked references from the merged result;
* **evidence grounding** — whether a part's text is supported by a span in the
  source document (local substring + token-overlap; embeddings optional).

Policy: *majority backbone + flagged singletons*. A part with ``>= accept_votes``
votes is accepted; a single-vote part is kept only if it grounds in the document,
and is flagged low-confidence; conflicting attributions are resolved by vote
count. The merge raises grounding/consistency/soundness — it does **not** certify
truth; the human approval gate remains the oracle.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from workflow_compiler.models import (
    ActivityNode,
    CompensationNode,
    DecisionNode,
    EventNode,
    ExceptionNode,
    FactCategory,
    TransitionEdge,
    WorkflowFact,
    WorkflowFacts,
    WorkflowMetadata,
    WorkflowStructure,
)
from workflow_compiler.models.structure import TERMINAL_TARGETS

_WORD = re.compile(r"[a-z0-9]+")

#: Scalar fact categories merged by voting (the non-structural vocabulary).
_SCALAR_CATEGORIES: tuple[FactCategory, ...] = (
    FactCategory.INPUT,
    FactCategory.OUTPUT,
    FactCategory.RULE,
    FactCategory.API,
    FactCategory.SYSTEM,
    FactCategory.TIMER,
    FactCategory.RETRY,
)


# --- grounding --------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _local_ground(text: str, doc_lower: str, doc_tokens: set[str]) -> float:
    """Reference-free support score in [0,1] of ``text`` against the document."""
    norm = text.strip().lower()
    if norm and norm in doc_lower:
        return 1.0
    toks = _tokens(text)
    if not toks:
        return 0.0
    return len(toks & doc_tokens) / len(toks)


def local_grounder(document_text: str) -> Callable[[str], float]:
    """Build a synchronous grounder bound to ``document_text``."""
    doc_lower = document_text.lower()
    doc_tokens = _tokens(document_text)

    def score(text: str) -> float:
        return _local_ground(text, doc_lower, doc_tokens)

    return score


async def ground_scores(
    texts: Sequence[str],
    document_text: str,
    embed: Callable[[Sequence[str]], object] | None = None,
) -> dict[str, float]:
    """Return text→support score, optionally enhanced with embeddings.

    Always computes the local score; if ``embed`` is provided and usable, blends
    in cosine similarity to the document vector. Any embedding failure (including
    ``NotImplementedError`` for providers without embeddings) silently falls back
    to the local score, so grounding works for every provider.
    """
    grounder = local_grounder(document_text)
    scores = {text: grounder(text) for text in texts}
    if embed is None or not texts:
        return scores
    try:
        vectors = await embed([document_text, *texts])  # type: ignore[misc]
    except Exception:
        return scores
    if not vectors or len(vectors) != len(texts) + 1:
        return scores
    doc_vec = vectors[0]
    for text, vec in zip(texts, vectors[1:], strict=False):
        sim = _cosine(doc_vec, vec)
        scores[text] = max(scores[text], sim)
    return scores


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, dot / (na * nb))


# --- provenance -------------------------------------------------------------


@dataclass
class MergeProvenance:
    """Human-readable record of how the consensus merge resolved the candidates."""

    candidates: int = 0
    accepted: Counter[str] = field(default_factory=Counter)
    flagged_singletons: list[str] = field(default_factory=list)
    dropped_singletons: list[str] = field(default_factory=list)
    dangling_dropped: int = 0

    def summary(self) -> str:
        """One-line note suitable for ``confidence_scores.notes``."""
        acc = ", ".join(f"{n} {k}" for k, n in sorted(self.accepted.items())) or "nothing"
        return (
            f"{self.candidates} candidate(s) merged; accepted {acc}; "
            f"{len(self.flagged_singletons)} single-vote part(s) flagged; "
            f"{len(self.dropped_singletons)} ungrounded singleton(s) dropped; "
            f"{self.dangling_dropped} dangling ref(s) dropped."
        )


# --- entity indexing --------------------------------------------------------


def _key(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


@dataclass
class _Index:
    order: list[str]
    votes: dict[str, int]
    name: dict[str, str]
    canon_id: dict[str, str]
    local_to_key: dict[tuple[int, str], str]
    occ: dict[str, list[tuple[int, object]]]


def _index_entities[T](
    per_candidate: list[list[T]],
    display: Callable[[T], str],
    id_prefix: str,
) -> _Index:
    """Match id-bearing entities across candidates by normalized display name."""
    order: list[str] = []
    cands: dict[str, set[int]] = defaultdict(set)
    names: dict[str, Counter[str]] = defaultdict(Counter)
    local_to_key: dict[tuple[int, str], str] = {}
    occ: dict[str, list[tuple[int, object]]] = defaultdict(list)
    for ci, items in enumerate(per_candidate):
        for entity in items:
            shown = display(entity)
            k = _key(shown)
            if not k:
                continue
            if k not in cands:
                order.append(k)
            cands[k].add(ci)
            names[k][shown] += 1
            occ[k].append((ci, entity))
            local_id = getattr(entity, "id", None)
            if local_id:
                local_to_key[(ci, local_id)] = k
    canon_id = {k: f"{id_prefix}{i + 1}" for i, k in enumerate(order)}
    votes = {k: len(cands[k]) for k in order}
    name = {k: names[k].most_common(1)[0][0] for k in order}
    return _Index(order, votes, name, canon_id, local_to_key, occ)


def _accept(
    key: str,
    index: _Index,
    ground: Callable[[str], float],
    accept_votes: int,
    singleton_min_ground: float,
    prov: MergeProvenance,
    kind: str,
) -> bool:
    """Apply 'majority backbone + flagged singletons' to one entity key."""
    votes = index.votes[key]
    label = f"{kind}:{index.name[key]}"
    if votes >= accept_votes:
        prov.accepted[kind] += 1
        return True
    # single vote: keep only if grounded in the document; flag either way.
    if ground(index.name[key]) >= singleton_min_ground:
        prov.accepted[kind] += 1
        prov.flagged_singletons.append(label)
        return True
    prov.dropped_singletons.append(label)
    return False


def _vote_ref(
    occ_list: list[tuple[int, object]],
    attr: str,
    remap: Callable[[int, str | None], str | None],
) -> str | None:
    """Pick the most-voted remapped value of ``attr`` across candidates."""
    counter: Counter[str] = Counter()
    for ci, entity in occ_list:
        mapped = remap(ci, getattr(entity, attr, None))
        if mapped is not None:
            counter[mapped] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


# --- structure merge --------------------------------------------------------


def merge_structures(
    candidates: list[WorkflowStructure],
    *,
    document_text: str = "",
    ground: Callable[[str], float] | None = None,
    accept_votes: int = 2,
    singleton_min_ground: float = 0.3,
) -> tuple[WorkflowStructure, MergeProvenance]:
    """Merge N structures into a consensus structure + provenance."""
    ground = ground or local_grounder(document_text)
    prov = MergeProvenance(candidates=len(candidates))
    if len(candidates) == 1:
        clean, warnings = candidates[0].validated()
        prov.dangling_dropped = len(warnings)
        return clean, prov

    acts = _index_entities([s.activities for s in candidates], lambda a: a.name, "a")
    decs = _index_entities([s.decisions for s in candidates], lambda d: d.question, "d")
    excs = _index_entities([s.exceptions for s in candidates], lambda x: x.reason, "e")
    comps = _index_entities([s.compensations for s in candidates], lambda c: c.name, "c")
    evts = _index_entities([s.events for s in candidates], lambda v: v.name, "v")

    # Combined (candidate, local id) -> canonical id for any legal target.
    target_map: dict[tuple[int, str], str] = {}
    for index in (acts, excs, evts):
        for (ci, lid), k in index.local_to_key.items():
            target_map[(ci, lid)] = index.canon_id[k]

    def remap_activity(ci: int, ref: str | None) -> str | None:
        if not ref:
            return None
        k = acts.local_to_key.get((ci, ref))
        return acts.canon_id[k] if k else None

    def remap_target(ci: int, ref: str | None) -> str | None:
        if not ref:
            return None
        if ref in TERMINAL_TARGETS:
            return ref
        return target_map.get((ci, ref))

    kept_act = [
        k
        for k in acts.order
        if _accept(k, acts, ground, accept_votes, singleton_min_ground, prov, "activity")
    ]
    groups = _merge_parallel_groups(candidates, acts, kept_act)
    activities = [
        ActivityNode(
            id=acts.canon_id[k],
            name=acts.name[k],
            parallel_group=groups.get(acts.canon_id[k]),
        )
        for k in kept_act
    ]
    decisions = [
        DecisionNode(
            id=decs.canon_id[k],
            question=decs.name[k],
            after=_vote_ref(decs.occ[k], "after", remap_activity),
            yes_target=_vote_ref(decs.occ[k], "yes_target", remap_target),
            no_target=_vote_ref(decs.occ[k], "no_target", remap_target),
        )
        for k in decs.order
        if _accept(k, decs, ground, accept_votes, singleton_min_ground, prov, "decision")
    ]
    exceptions = [
        ExceptionNode(
            id=excs.canon_id[k],
            reason=excs.name[k],
            raised_by=_vote_ref(excs.occ[k], "raised_by", remap_activity),
        )
        for k in excs.order
        if _accept(k, excs, ground, accept_votes, singleton_min_ground, prov, "exception")
    ]
    compensations = [
        CompensationNode(
            id=comps.canon_id[k],
            name=comps.name[k],
            compensates=_vote_ref(comps.occ[k], "compensates", remap_activity),
        )
        for k in comps.order
        if _accept(k, comps, ground, accept_votes, singleton_min_ground, prov, "compensation")
    ]
    events = [
        EventNode(
            id=evts.canon_id[k],
            name=evts.name[k],
            emitted_by=_vote_ref(evts.occ[k], "emitted_by", remap_target),
        )
        for k in evts.order
        if _accept(k, evts, ground, accept_votes, singleton_min_ground, prov, "event")
    ]
    transitions = _merge_transitions(
        candidates, ground, accept_votes, singleton_min_ground, prov
    )

    merged = WorkflowStructure(
        activities=activities,
        decisions=decisions,
        exceptions=exceptions,
        compensations=compensations,
        events=events,
        transitions=transitions,
    )
    clean, warnings = merged.validated()
    prov.dangling_dropped = len(warnings)
    return clean, prov


def _merge_parallel_groups(
    candidates: list[WorkflowStructure], acts: _Index, kept: list[str]
) -> dict[str, str]:
    """Assign canonical parallel groups voted by >=2 candidates (by member set)."""
    set_votes: Counter[frozenset[str]] = Counter()
    for ci, structure in enumerate(candidates):
        by_group: dict[str, set[str]] = defaultdict(set)
        for a in structure.activities:
            if a.parallel_group:
                k = acts.local_to_key.get((ci, a.id))
                if k and k in kept:
                    by_group[a.parallel_group].add(acts.canon_id[k])
        for members in by_group.values():
            if len(members) >= 2:
                set_votes[frozenset(members)] += 1
    group_of: dict[str, str] = {}
    gid = 0
    for members, votes in set_votes.items():
        if votes >= 2:
            gid += 1
            for canon in members:
                group_of[canon] = f"g{gid}"
    return group_of


def _merge_transitions(
    candidates: list[WorkflowStructure],
    ground: Callable[[str], float],
    accept_votes: int,
    singleton_min_ground: float,
    prov: MergeProvenance,
) -> list[TransitionEdge]:
    votes: Counter[tuple[str, str]] = Counter()
    sample: dict[tuple[str, str], TransitionEdge] = {}
    for structure in candidates:
        seen: set[tuple[str, str]] = set()
        for t in structure.transitions:
            key = (_key(t.source), _key(t.target))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            votes[key] += 1
            sample.setdefault(key, t)
    out: list[TransitionEdge] = []
    for key, count in votes.items():
        edge = sample[key]
        label = f"transition:{edge.source} -> {edge.target}"
        if count >= accept_votes or ground(f"{edge.source} {edge.target}") >= singleton_min_ground:
            out.append(edge)
            prov.accepted["transition"] += 1
            if count < accept_votes:
                prov.flagged_singletons.append(label)
        else:
            prov.dropped_singletons.append(label)
    return out


# --- facts merge (structure + scalar vocabulary) ----------------------------


def merge_facts(
    candidates: list[WorkflowFacts],
    *,
    document_text: str = "",
    ground: Callable[[str], float] | None = None,
    accept_votes: int = 2,
    singleton_min_ground: float = 0.3,
) -> tuple[WorkflowFacts, MergeProvenance]:
    """Merge candidate ``WorkflowFacts`` (relational structure + scalar facts)."""
    ground = ground or local_grounder(document_text)
    structures = [f.structure for f in candidates if f.structure is not None]
    if structures:
        merged_structure, prov = merge_structures(
            structures,
            document_text=document_text,
            ground=ground,
            accept_votes=accept_votes,
            singleton_min_ground=singleton_min_ground,
        )
    else:
        merged_structure, prov = None, MergeProvenance(candidates=len(candidates))

    n = max(len(candidates), 1)
    scalar_facts = _merge_scalar_facts(
        candidates, ground, accept_votes, singleton_min_ground, prov, n
    )
    structural_facts = _facts_from_structure(merged_structure, n) if merged_structure else []
    return WorkflowFacts(facts=scalar_facts + structural_facts, structure=merged_structure), prov


def _merge_scalar_facts(
    candidates: list[WorkflowFacts],
    ground: Callable[[str], float],
    accept_votes: int,
    singleton_min_ground: float,
    prov: MergeProvenance,
    n: int,
) -> list[WorkflowFact]:
    facts: list[WorkflowFact] = []
    for category in _SCALAR_CATEGORIES:
        votes: Counter[str] = Counter()
        display: dict[str, str] = {}
        for cand in candidates:
            seen: set[str] = set()
            for fact in cand.by_category(category):
                k = _key(fact.statement)
                if not k or k in seen:
                    continue
                seen.add(k)
                votes[k] += 1
                display.setdefault(k, fact.statement)
        index = 0
        for k, count in votes.items():
            statement = display[k]
            if count < accept_votes and ground(statement) < singleton_min_ground:
                prov.dropped_singletons.append(f"{category.value}:{statement}")
                continue
            if count < accept_votes:
                prov.flagged_singletons.append(f"{category.value}:{statement}")
            index += 1
            facts.append(
                WorkflowFact(
                    id=f"{category.value}-{index}",
                    statement=statement,
                    category=category,
                    confidence=round(count / n, 3),
                )
            )
    return facts


def _facts_from_structure(structure: WorkflowStructure, n: int) -> list[WorkflowFact]:
    """Derive the structural-category flat facts from a merged structure."""
    comp_target = {a.id: a.name for a in structure.activities}
    items: list[tuple[FactCategory, list[str]]] = [
        (FactCategory.ACTIVITY, [a.name for a in structure.activities]),
        (FactCategory.DECISION, [d.question for d in structure.decisions]),
        (FactCategory.EVENT, [v.name for v in structure.events]),
        (FactCategory.EXCEPTION, [x.reason for x in structure.exceptions]),
        (
            FactCategory.STATE_TRANSITION,
            [f"{t.source} -> {t.target}" for t in structure.transitions],
        ),
        (
            FactCategory.COMPENSATION,
            [
                f"{c.name} compensates {comp_target[c.compensates]}"
                if c.compensates in comp_target
                else c.name
                for c in structure.compensations
            ],
        ),
    ]
    facts: list[WorkflowFact] = []
    for category, statements in items:
        for index, statement in enumerate(statements, start=1):
            facts.append(
                WorkflowFact(
                    id=f"{category.value}-{index}",
                    statement=statement,
                    category=category,
                    confidence=round(2 / n, 3) if n > 1 else 1.0,
                )
            )
    return facts


# --- metadata merge ---------------------------------------------------------


def merge_metadata(
    candidates: list[WorkflowMetadata],
    *,
    document_text: str = "",
    ground: Callable[[str], float] | None = None,
    accept_votes: int = 2,
    singleton_min_ground: float = 0.3,
) -> tuple[WorkflowMetadata, MergeProvenance]:
    """Merge candidate metadata: majority scalars, vote-thresholded list unions."""
    ground = ground or local_grounder(document_text)
    prov = MergeProvenance(candidates=len(candidates))
    if len(candidates) == 1:
        return candidates[0], prov

    name = _majority_scalar([c.name for c in candidates]) or candidates[0].name
    purpose = _majority_scalar([c.purpose or "" for c in candidates]) or None

    def merge_list(values: list[list[str]], kind: str) -> list[str]:
        return _vote_union(values, kind, ground, accept_votes, singleton_min_ground, prov)

    return (
        WorkflowMetadata(
            name=name,
            purpose=purpose,
            description=purpose,
            actors=merge_list([c.actors for c in candidates], "actor"),
            systems=merge_list([c.systems for c in candidates], "system"),
            trigger_events=merge_list([c.trigger_events for c in candidates], "trigger"),
            start_states=merge_list([c.start_states for c in candidates], "start_state"),
            end_states=merge_list([c.end_states for c in candidates], "end_state"),
        ),
        prov,
    )


def _majority_scalar(values: list[str]) -> str:
    counter: Counter[str] = Counter(v.strip() for v in values if v.strip())
    if not counter:
        return ""
    top = counter.most_common()
    best = max(top, key=lambda kv: (kv[1], len(kv[0])))
    return best[0]


def _vote_union(
    per_candidate: list[list[str]],
    kind: str,
    ground: Callable[[str], float],
    accept_votes: int,
    singleton_min_ground: float,
    prov: MergeProvenance,
) -> list[str]:
    votes: Counter[str] = Counter()
    display: dict[str, str] = {}
    for items in per_candidate:
        seen: set[str] = set()
        for item in items:
            k = _key(item)
            if not k or k in seen:
                continue
            seen.add(k)
            votes[k] += 1
            display.setdefault(k, item.strip())
    out: list[str] = []
    for k, count in votes.items():
        value = display[k]
        if count < accept_votes and ground(value) < singleton_min_ground:
            prov.dropped_singletons.append(f"{kind}:{value}")
            continue
        if count < accept_votes:
            prov.flagged_singletons.append(f"{kind}:{value}")
        prov.accepted[kind] += 1
        out.append(value)
    return out

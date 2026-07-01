"""Relational workflow structure: id-referenced entities and their relations.

Where :class:`~workflow_compiler.models.facts.WorkflowFacts` is a flat list of
statements, :class:`WorkflowStructure` captures the *edges* between them — which
activity raises which exception, which compensation reverses which activity,
which decision gates which branch, and which activities run in parallel.

Every relation references another entity by **id**. :meth:`WorkflowStructure.validated`
enforces referential integrity: any relation pointing at an id that was never
declared is dropped (the node is kept, the dangling reference is nulled). This is
the core anti-hallucination guard — the graph can only be wired from links the
model actually grounded in declared entities.
"""

from __future__ import annotations

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel

#: Branch / emission targets that are valid without referencing a declared id.
TERMINAL_TARGETS: frozenset[str] = frozenset(
    {"end", "start", "reject", "rejected", "fail", "failed", "complete", "completed"}
)


class ActivityNode(WorkflowBaseModel):
    """A unit of work. ``parallel_group`` labels activities that run concurrently."""

    id: str = Field(..., description="Stable id (e.g. 'a1') referenced by relations.")
    name: str = Field(..., description="Imperative activity name.")
    parallel_group: str | None = Field(
        default=None, description="Shared label for activities that run in parallel."
    )


class DecisionNode(WorkflowBaseModel):
    """A branch point. References the activity it follows and its branch targets."""

    id: str = Field(..., description="Stable id (e.g. 'd1').")
    question: str = Field(..., description="The yes/no question being decided.")
    after: str | None = Field(
        default=None, description="Activity id this decision evaluates the result of."
    )
    yes_target: str | None = Field(
        default=None, description="Node id taken when the answer is yes (default: continue)."
    )
    no_target: str | None = Field(
        default=None, description="Node id taken when the answer is no (often an exception)."
    )


class ExceptionNode(WorkflowBaseModel):
    """An error condition, attributed to the activity that raises it."""

    id: str = Field(..., description="Stable id (e.g. 'e1').")
    reason: str = Field(..., description="Error reason / code.")
    raised_by: str | None = Field(
        default=None, description="Activity id that can raise this exception."
    )


class CompensationNode(WorkflowBaseModel):
    """A saga rollback action, tied to the activity it reverses."""

    id: str = Field(..., description="Stable id (e.g. 'c1').")
    name: str = Field(..., description="Compensation action name.")
    compensates: str | None = Field(
        default=None, description="Activity id this compensation reverses."
    )


class EventNode(WorkflowBaseModel):
    """An emitted event, attributed to the activity (or point) that emits it."""

    id: str = Field(..., description="Stable id (e.g. 'v1').")
    name: str = Field(..., description="Event name.")
    emitted_by: str | None = Field(
        default=None, description="Activity id (or terminal token) that emits this event."
    )


class TransitionEdge(WorkflowBaseModel):
    """A state transition between two named states."""

    source: str = Field(..., description="Source state name.")
    target: str = Field(..., description="Target state name.")
    trigger: str | None = Field(default=None, description="What causes the transition.")


class WorkflowStructure(WorkflowBaseModel):
    """Id-referenced entities and the relations that connect them."""

    activities: list[ActivityNode] = Field(default_factory=list)
    decisions: list[DecisionNode] = Field(default_factory=list)
    exceptions: list[ExceptionNode] = Field(default_factory=list)
    compensations: list[CompensationNode] = Field(default_factory=list)
    events: list[EventNode] = Field(default_factory=list)
    transitions: list[TransitionEdge] = Field(default_factory=list)

    def is_empty(self) -> bool:
        """True when no entities were captured (caller should fall back to flat facts)."""
        return not (
            self.activities
            or self.decisions
            or self.exceptions
            or self.compensations
            or self.events
            or self.transitions
        )

    def activity_ids(self) -> set[str]:
        """Ids of declared activities."""
        return {a.id for a in self.activities}

    def node_ids(self) -> set[str]:
        """Ids that a branch / emission may legitimately target."""
        return (
            self.activity_ids()
            | {e.id for e in self.exceptions}
            | {v.id for v in self.events}
        )

    def all_ids(self) -> set[str]:
        """Every declared entity id (used to detect ids leaking into state names)."""
        return (
            self.activity_ids()
            | {d.id for d in self.decisions}
            | {e.id for e in self.exceptions}
            | {c.id for c in self.compensations}
            | {v.id for v in self.events}
        )

    def validated(self) -> tuple[WorkflowStructure, list[str]]:
        """Return a copy with dangling references nulled, plus a list of warnings.

        Referential-integrity guard (anti-hallucination): a relation may only
        point at a declared id (or a recognized terminal token). Any reference to
        an unknown id is dropped — the entity is kept, the bad link is removed.
        """
        activities = self.activity_ids()
        targets = self.node_ids() | TERMINAL_TARGETS
        warnings: list[str] = []

        def keep_activity(ref: str | None, owner: str) -> str | None:
            if ref and ref not in activities:
                warnings.append(f"{owner} references unknown activity '{ref}' — dropped.")
                return None
            return ref

        def keep_target(ref: str | None, owner: str) -> str | None:
            if ref and ref not in targets:
                warnings.append(f"{owner} references unknown target '{ref}' — dropped.")
                return None
            return ref

        # The first exception each activity can raise — used to repair a
        # degenerate decision whose 'no' branch was never wired distinctly.
        exc_by_activity: dict[str, str] = {}
        for x in self.exceptions:
            if x.raised_by and x.raised_by not in exc_by_activity:
                exc_by_activity[x.raised_by] = x.id

        decisions: list[DecisionNode] = []
        for d in self.decisions:
            after = keep_activity(d.after, f"decision {d.id}")
            yes_target = keep_target(d.yes_target, f"decision {d.id} (yes)")
            no_target = keep_target(d.no_target, f"decision {d.id} (no)")
            if yes_target is not None and yes_target == no_target:
                # Identical branches mean the 'no' path was never modeled; route it
                # to the exception the gated activity raises, else null it so the
                # builder can terminate the branch instead of looping back.
                alt = exc_by_activity.get(after or "")
                warnings.append(
                    f"decision {d.id} has identical yes/no targets — "
                    + (f"re-routing 'no' to {alt}." if alt else "dropping 'no'.")
                )
                no_target = alt
            decisions.append(
                d.model_copy(
                    update={"after": after, "yes_target": yes_target, "no_target": no_target}
                )
            )
        exceptions = [
            x.model_copy(update={"raised_by": keep_activity(x.raised_by, f"exception {x.id}")})
            for x in self.exceptions
        ]
        compensations = [
            c.model_copy(
                update={"compensates": keep_activity(c.compensates, f"compensation {c.id}")}
            )
            for c in self.compensations
        ]
        events = [
            v.model_copy(update={"emitted_by": keep_target(v.emitted_by, f"event {v.id}")})
            for v in self.events
        ]

        # Strip parallel-group membership from activities whose control flow is
        # gated by a decision (its anchor or a branch target). Such activities
        # have ordering/data dependencies and must not be folded into a fork —
        # this is what stops dependent steps being mis-parallelized.
        gated: set[str] = set()
        for d in decisions:
            for ref in (d.after, d.yes_target, d.no_target):
                if ref in activities:
                    gated.add(ref)
        normalized_activities: list[ActivityNode] = []
        for a in self.activities:
            if a.parallel_group is not None and a.id in gated:
                warnings.append(
                    f"activity {a.id} is gated by a decision — removed from parallel group."
                )
                normalized_activities.append(a.model_copy(update={"parallel_group": None}))
            else:
                normalized_activities.append(a)

        # Drop "state transitions" whose endpoints are actually entity ids — the
        # model leaking the control flow (a1 -> a2 -> d1 …) into the state graph,
        # which otherwise builds a junk subgraph that duplicates the real flow.
        ids = self.all_ids()
        transitions = []
        for t in self.transitions:
            if t.source in ids or t.target in ids:
                warnings.append(
                    f"transition '{t.source} -> {t.target}' references an entity id — dropped."
                )
                continue
            transitions.append(t)

        clean = self.model_copy(
            update={
                "activities": normalized_activities,
                "decisions": decisions,
                "exceptions": exceptions,
                "compensations": compensations,
                "events": events,
                "transitions": transitions,
            }
        )
        return clean, warnings

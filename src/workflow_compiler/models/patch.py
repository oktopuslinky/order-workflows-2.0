"""Deterministic patch vocabulary for the sequential review pipelines.

A *review pass* never regenerates an artifact. It inspects the canonical output
(plus the source document) and emits a :class:`ReviewResult` — a list of minimal
:class:`Patch` operations, or nothing at all (``no_change``). A deterministic
*applier* then folds those patches into the artifact.

These models are **LLM output schemas**, so unlike the rest of the domain models
they are permissive (``extra="ignore"``): a slightly-off model response still
parses, and the applier does the strict, deterministic work.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PatchAction(StrEnum):
    """The deterministic operations a review pass may request.

    * ``ADD`` — introduce a workflow element explicitly present in the document
      but missing from the artifact (completeness pass).
    * ``REMOVE`` — delete an element not supported by the document (grounding pass).
    * ``MODIFY`` — change a field of an existing element (e.g. fix a relation).
    * ``MERGE`` — collapse two semantically-equivalent elements into one.
    * ``FLAG`` — mark an element as suspect without changing it (records a note).
    * ``NO_CHANGE`` — explicit "nothing to do"; makes idempotency observable.
    """

    ADD = "add"
    REMOVE = "remove"
    MODIFY = "modify"
    MERGE = "merge"
    FLAG = "flag"
    NO_CHANGE = "no_change"


class Evidence(BaseModel):
    """Where a patch is grounded in the source document.

    Every non-``no_change`` patch should cite evidence. All fields are optional —
    "include where practical" — but a patch with no quote/section is treated as
    weakly grounded by the appliers and may be dropped on the grounding pass.
    """

    model_config = ConfigDict(extra="ignore")

    source_section: str | None = Field(default=None, description="Section/path in the document.")
    heading: str | None = Field(default=None, description="Nearest heading above the evidence.")
    workflow_step: str | None = Field(default=None, description="Named step the evidence concerns.")
    quote: str | None = Field(default=None, description="Verbatim supporting text from the doc.")
    char_start: int | None = Field(default=None, description="Start offset of the quote, if known.")
    char_end: int | None = Field(default=None, description="End offset of the quote, if known.")


class Patch(BaseModel):
    """One minimal, deterministic edit to a reviewed artifact.

    ``target`` addresses what the patch acts on; its meaning is interpreted by
    the artifact's applier:

    * for **metadata** — a field name (``actors``, ``systems``, ``name`` …);
    * for **facts** — an entity kind + id (``activity:a3``), a flat category
      (``rule``), or — for ``MERGE`` — two ids joined by ``+`` (``a2+a5``).

    ``payload`` carries the data for ``ADD`` / ``MODIFY`` (e.g.
    ``{"value": "Warehouse"}`` or ``{"name": "Ship order", "raised_by": "a3"}``).
    """

    model_config = ConfigDict(extra="ignore")

    action: PatchAction = Field(default=PatchAction.NO_CHANGE)
    target: str = Field(default="", description="Field name, entity ref, or 'idA+idB' for merge.")
    payload: dict[str, object] = Field(
        default_factory=dict, description="Data for add/modify operations."
    )
    evidence: Evidence | None = Field(
        default=None, description="Source grounding for this patch (required for non-no_change)."
    )

    def is_noop(self) -> bool:
        """True when this patch requests no change."""
        return self.action == PatchAction.NO_CHANGE


class ReviewResult(BaseModel):
    """The output of a single review pass: zero or more patches.

    An empty list — or a list containing only ``no_change`` patches — means the
    pass found nothing to do. This is the idempotent fixed point: a second pass
    over an already-reviewed artifact should return exactly this.
    """

    model_config = ConfigDict(extra="ignore")

    patches: list[Patch] = Field(default_factory=list)
    note: str = Field(default="", description="Optional free-text rationale from the pass.")

    def effective_patches(self) -> list[Patch]:
        """Patches that actually request a change (drops ``no_change`` entries)."""
        return [p for p in self.patches if not p.is_noop()]

    def is_no_change(self) -> bool:
        """True when the pass requested no effective change."""
        return not self.effective_patches()

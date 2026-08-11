"""Regression: a MODIFY patch must not write a raw string onto an enum field.

Found by the first live browser run of the dialogue. An answer modified an
event's ``kind``; the applier used ``model_copy(update=...)``, which bypasses
pydantic entirely, so the payload's plain string landed on ``EventNode.kind``
(typed :class:`EventKind`). Nothing failed at the time — it surfaced much later
and far away, as ``'str' object has no attribute 'value'`` inside the spec
renderer, returned to the browser as an opaque 500.

The fix re-validates the node, so the value is either coerced to the enum or the
patch is dropped. These tests pin both halves, plus the end-to-end property that
actually broke: a modified spec must still render.
"""

from __future__ import annotations

from workflow_compiler.agents.review_pipeline import FactsPatchApplier
from workflow_compiler.models import (
    EventKind,
    EventNode,
    Patch,
    PatchAction,
    WorkflowFacts,
    WorkflowMetadata,
    WorkflowSpec,
    WorkflowStructure,
)
from workflow_compiler.spec.renderer import render_spec

_DOCUMENT = "The order workflow emits Payment Confirmed when the payment clears."


def _facts() -> WorkflowFacts:
    return WorkflowFacts(
        structure=WorkflowStructure(
            events=[
                EventNode(id="e1", name="Payment Confirmed", kind=EventKind.OUTPUT_EMIT)
            ]
        )
    )


def _modify_kind(value: object) -> Patch:
    return Patch(action=PatchAction.MODIFY, target="event:e1", payload={"kind": value})


def test_a_string_kind_is_coerced_to_the_enum() -> None:
    facts, _ = FactsPatchApplier().apply(_facts(), [_modify_kind("signal_wait")], _DOCUMENT)

    assert facts.structure is not None
    kind = facts.structure.events[0].kind
    assert isinstance(kind, EventKind)
    # The whole point: this attribute access is what the renderer does.
    assert kind.value == "signal_wait"


def test_an_unparseable_kind_drops_the_patch_instead_of_corrupting_the_node() -> None:
    facts, _ = FactsPatchApplier().apply(_facts(), [_modify_kind("not-a-kind")], _DOCUMENT)

    assert facts.structure is not None
    assert facts.structure.events[0].kind is EventKind.OUTPUT_EMIT


def test_a_modified_spec_still_renders() -> None:
    """The end-to-end property that actually failed, in one assertion."""
    facts, _ = FactsPatchApplier().apply(_facts(), [_modify_kind("trigger")], _DOCUMENT)
    spec = WorkflowSpec(
        slug="order-fulfillment",
        metadata=WorkflowMetadata(name="Order Fulfillment", purpose="Fulfill orders."),
        facts=facts,
    )

    markdown = render_spec(spec, [], [])

    assert "Payment Confirmed" in markdown


def test_other_fields_still_modify_normally() -> None:
    """The re-validation must not break the ordinary string-field path."""
    facts, _ = FactsPatchApplier().apply(
        _facts(),
        [Patch(action=PatchAction.MODIFY, target="event:e1", payload={"name": "Paid"})],
        _DOCUMENT,
    )

    assert facts.structure is not None
    assert facts.structure.events[0].name == "Paid"

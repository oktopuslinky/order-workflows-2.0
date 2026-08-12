"""Regression: every ``arg.<field>`` the generated workflow reads must exist.

Found by running a generated bundle against a real Temporal dev server -- the
only thing that actually proves codegen worked. The workflow crashed on its
first activity with::

    AttributeError: 'WorkflowInput' object has no attribute 'customer_order_items'
                    Did you mean: 'customer_order'?

``WorkflowInput`` is built from ``design.workflow_inputs``, but the ``arg.<ref>``
expressions come from step *bindings*. Those two halves of the design are
produced together and can disagree, and the emitter wrote the reference without
checking the field was declared -- so the bundle imported cleanly, passed every
static check, and then failed at runtime.

The invariant asserted here is the one that matters and is cheap to check
statically: the set of ``arg.X`` reads in workflow.py is a subset of the fields
declared on WorkflowInput in shared.py.
"""

from __future__ import annotations

import re

from workflow_compiler.codegen.temporal import TemporalPythonCodeGenerator
from workflow_compiler.models import (
    BindingSource,
    StepKind,
    TemporalActivityDesign,
    TemporalParam,
    TemporalStep,
    TemporalWorkflowDesign,
)
from workflow_compiler.models.temporal import InputBinding

_ARG_READ = re.compile(r"\barg\.([a-z_][a-z0-9_]*)")


def _design() -> TemporalWorkflowDesign:
    """A design whose binding cites a workflow input it never declares."""
    return TemporalWorkflowDesign(
        workflow_name="OrderFulfillmentWorkflow",
        # Note: no `customer_order_items` here...
        workflow_inputs=[TemporalParam(name="customer_order", type="dict")],
        activities=[
            TemporalActivityDesign(
                name="ReserveInventory",
                params=[TemporalParam(name="order_items", type="list")],
            )
        ],
        plan=[
            TemporalStep(
                id="s1",
                kind=StepKind.ACTIVITY,
                ref="ReserveInventory",
                result_name="reserved",
                bindings=[
                    # ...but the binding reads it anyway.
                    InputBinding(
                        param="order_items",
                        source=BindingSource.WORKFLOW_INPUT,
                        ref="customer_order_items",
                    )
                ],
            )
        ],
    )


def _generate(design: TemporalWorkflowDesign) -> dict[str, str]:
    bundle = TemporalPythonCodeGenerator().generate(design)
    return {f.path.split("/")[-1]: f.content for f in bundle.files}


def _declared_fields(shared_py: str) -> set[str]:
    body = shared_py.split("class WorkflowInput:", 1)[1].split("@dataclass", 1)[0]
    return set(re.findall(r"^\s{4}([a-z_][a-z0-9_]*)\s*:", body, re.MULTILINE))


def test_every_arg_read_is_a_declared_workflow_input_field() -> None:
    files = _generate(_design())

    reads = set(_ARG_READ.findall(files["workflow.py"]))
    declared = _declared_fields(files["shared.py"])

    assert reads, "the fixture should produce at least one arg.<field> read"
    assert reads <= declared, f"undeclared workflow input(s): {sorted(reads - declared)}"


def test_the_undeclared_reference_is_recovered_with_its_used_type() -> None:
    """Recovered from the activity param it feeds, not defaulted to str."""
    files = _generate(_design())

    shared = files["shared.py"]
    assert "customer_order_items: list" in shared
    # The declared input is still there — recovery adds, never replaces.
    assert "customer_order: dict" in shared


def test_a_consistent_design_is_unchanged() -> None:
    """Recovery must not widen WorkflowInput when the design already agrees."""
    design = _design()
    design.workflow_inputs.append(TemporalParam(name="customer_order_items", type="list"))

    declared = _declared_fields(_generate(design)["shared.py"])

    assert declared == {"customer_order", "customer_order_items"}


# --------------------------------------------------------------------------- #
# Signals and queries must register under the DESIGN's name
# --------------------------------------------------------------------------- #


def _signal_design() -> TemporalWorkflowDesign:
    from workflow_compiler.models import TemporalQueryDesign, TemporalSignalDesign

    return TemporalWorkflowDesign(
        workflow_name="OrderFulfillmentWorkflow",
        workflow_inputs=[TemporalParam(name="order_id", type="str")],
        signals=[TemporalSignalDesign(name="SLABreachAlert", payload=["order_id", "delay_reason"])],
        queries=[TemporalQueryDesign(name="OrderStatus", returns="str")],
    )


def test_signals_register_under_the_designs_name() -> None:
    """Without an explicit name the SDK uses the snake_cased method, so a caller
    signalling the documented 'SLABreachAlert' is silently ignored and a bounded
    wait hangs to its timeout. Verified against a live Temporal server."""
    workflow_py = _generate(_signal_design())["workflow.py"]

    assert '@workflow.signal(name="SLABreachAlert")' in workflow_py
    assert '@workflow.query(name="OrderStatus")' in workflow_py


def test_signal_payload_params_have_defaults() -> None:
    """A signal delivered with fewer args than declared must not raise
    TypeError inside the handler and fail the workflow task."""
    workflow_py = _generate(_signal_design())["workflow.py"]

    line = next(
        src
        for src in workflow_py.splitlines()
        if src.strip().startswith("def slabreach_alert(")
    )
    assert 'order_id: str = ""' in line
    assert 'delay_reason: str = ""' in line

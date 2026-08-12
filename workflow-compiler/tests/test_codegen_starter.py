"""``starter.py`` ships sample input, so a fresh bundle runs with one command.

Before this, every generated starter contained::

    WorkflowInput(),  # TODO: populate the workflow input fields.

so a first run drove the whole workflow with empty strings, empty dicts and
``False``. The spec already knows the input names and types, so the values are
derived from them -- deterministically, no LLM.

The load-bearing invariant is the mirror image of the one in
``test_codegen_workflow_input.py``: there, every ``arg.X`` the workflow *reads*
must be a declared field; here, every kwarg the starter *writes* must be one
too. A kwarg naming a field that does not exist is a ``TypeError`` on the first
line of the first run -- invisible to ruff, mypy and every import-level check.
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


def _generate(design: TemporalWorkflowDesign) -> dict[str, str]:
    bundle = TemporalPythonCodeGenerator().generate(design)
    return {f.path.split("/")[-1]: f.content for f in bundle.files}


def _declared_fields(shared_py: str) -> set[str]:
    body = shared_py.split("class WorkflowInput:", 1)[1].split("@dataclass", 1)[0]
    return set(re.findall(r"^\s{4}([a-z_][a-z0-9_]*)\s*:", body, re.MULTILINE))


def _starter_kwargs(starter_py: str) -> dict[str, str]:
    """``{field: literal}`` from the ``WorkflowInput(...)`` call in starter.py."""
    call = starter_py.split("WorkflowInput(", 1)[1].split("\n        )", 1)[0]
    return {
        match.group(1): match.group(2).strip()
        for match in re.finditer(r"^\s+([a-z_][a-z0-9_]*)=(.+),$", call, re.MULTILINE)
    }


def _typed_design() -> TemporalWorkflowDesign:
    """One workflow input of every type the sample table covers."""
    return TemporalWorkflowDesign(
        workflow_name="OrderFulfillmentWorkflow",
        workflow_inputs=[
            TemporalParam(name="order_id", type="str"),
            TemporalParam(name="customer_email", type="str"),
            TemporalParam(name="customer_order", type="dict"),
            TemporalParam(name="line_items", type="list"),
            TemporalParam(name="retry_count", type="int"),
            TemporalParam(name="order_total", type="float"),
            TemporalParam(name="is_expedited", type="bool"),
        ],
    )


def test_starter_passes_a_sample_for_every_declared_input() -> None:
    files = _generate(_typed_design())

    kwargs = _starter_kwargs(files["starter.py"])

    assert set(kwargs) == _declared_fields(files["shared.py"])


def test_sample_values_are_typed_and_plausible() -> None:
    kwargs = _starter_kwargs(_generate(_typed_design())["starter.py"])

    assert kwargs == {
        # Identifier-shaped str fields read as ids.
        "order_id": '"ORD-1"',
        # Any other str is unmistakably placeholder data.
        "customer_email": '"sample-customer-email"',
        # No honest sample element exists for a container, so it stays empty.
        "customer_order": "{}",
        "line_items": "[]",
        "retry_count": "1",
        "order_total": "1.0",
        # True, not False -- same reasoning as the activity return placeholders:
        # a branch gating on this must take the main path, not the reject lane.
        "is_expedited": "True",
    }


def test_the_todo_marker_survives() -> None:
    """The values are placeholders and must keep saying so."""
    starter = _generate(_typed_design())["starter.py"]

    assert "# TODO: replace these placeholder values with real input." in starter


def test_generated_starter_is_syntactically_valid() -> None:
    """The kwargs are rendered by a template; a stray comma breaks every bundle."""
    starter = _generate(_typed_design())["starter.py"]

    compile(starter, "starter.py", "exec")


def test_a_design_with_no_inputs_still_renders_a_runnable_starter() -> None:
    """WorkflowInput() has no fields to pass, so the old form is still correct."""
    starter = _generate(TemporalWorkflowDesign(workflow_name="EmptyWorkflow"))["starter.py"]

    assert "WorkflowInput()," in starter
    compile(starter, "starter.py", "exec")


def test_recovered_inputs_get_samples_too() -> None:
    """A field recovered from a binding (the fix in test_codegen_workflow_input)
    is a real constructor field, so omitting its sample would leave the two
    halves disagreeing again -- just in the other direction."""
    design = TemporalWorkflowDesign(
        workflow_name="OrderFulfillmentWorkflow",
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
                    InputBinding(
                        param="order_items",
                        source=BindingSource.WORKFLOW_INPUT,
                        ref="customer_order_items",
                    )
                ],
            )
        ],
    )

    files = _generate(design)
    kwargs = _starter_kwargs(files["starter.py"])

    assert set(kwargs) == _declared_fields(files["shared.py"])
    assert kwargs["customer_order_items"] == "[]"

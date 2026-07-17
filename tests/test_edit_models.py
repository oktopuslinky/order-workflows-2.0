"""Tests for the edit-request models (models/edit.py) and the project edit log."""

from __future__ import annotations

from workflow_compiler.models import (
    CompilationProject,
    EditPlan,
    EditRecord,
    Patch,
    PatchAction,
    TriggerOp,
    WiringAction,
    WorkflowTrigger,
    XrefOp,
)


def test_edit_record_round_trip() -> None:
    record = EditRecord(
        document="# Edit Request\n\n## Workflow: order\n\n### Add\n- something",
        author="devansh",
        resolved_patches={
            "order": [Patch(action=PatchAction.ADD, target="rule", payload={"value": "x"})]
        },
        trigger_ops=[
            TriggerOp(
                action=WiringAction.REMOVE,
                source_workflow="order",
                target_workflow="ship",
            )
        ],
        workflows_added=["returns"],
        workflows_removed=["legacy"],
        summary={"order": ["added rule 'x'"]},
    )
    restored = EditRecord.model_validate_json(record.model_dump_json())
    assert restored == record
    assert restored.edit_id == record.edit_id
    assert restored.resolved_patches["order"][0].action is PatchAction.ADD


def test_edit_plan_is_permissive_llm_schema() -> None:
    # Slightly-off model output (extra keys) must still parse.
    plan = EditPlan.model_validate(
        {
            "patches": [{"action": "modify", "target": "activity:a3", "payload": {}}],
            "trigger_ops": [
                {
                    "action": "add",
                    "source_workflow": "order",
                    "target_workflow": "ship",
                    "trigger": {"source_workflow": "order", "target_workflow": "ship"},
                    "confidence": 0.9,
                }
            ],
            "xref_ops": [],
            "unresolved": [],
            "hallucinated_extra": True,
        }
    )
    assert plan.patches[0].target == "activity:a3"
    assert isinstance(plan.trigger_ops[0].trigger, WorkflowTrigger)
    assert plan.trigger_ops[0].action is WiringAction.ADD


def test_xref_op_defaults() -> None:
    op = XrefOp.model_validate({"action": "remove"})
    assert op.reference is None


def test_project_edit_log_backwards_compatible() -> None:
    # Project JSON written before the edit_log field existed must still load.
    project = CompilationProject(document_text="doc")
    dumped = project.model_dump(mode="json")
    dumped.pop("edit_log")
    restored = CompilationProject.model_validate(dumped)
    assert restored.edit_log == []


def test_project_edit_log_round_trip() -> None:
    project = CompilationProject(document_text="doc")
    project.edit_log.append(EditRecord(document="# Edit Request"))
    restored = CompilationProject.model_validate_json(project.model_dump_json())
    assert len(restored.edit_log) == 1
    assert restored.edit_log[0].document == "# Edit Request"

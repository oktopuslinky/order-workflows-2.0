"""Project-level composition of per-workflow Temporal bundles.

Each workflow still generates (and runs) as a fully standalone bundle — this
module only adds the **project glue** written next to those bundles:

* ``contracts.py`` — every workflow's typed ``WorkflowInput`` dataclass in one
  place, so trigger payloads and worker/deploy code can share one source of
  truth for the cross-workflow hand-off shapes.
* ``README.md`` — the deployment topology: every workflow, its task queue, and
  the trigger edges between workflows (mode + condition).

Deterministic: no LLM, pure functions of the approved designs.
"""

from __future__ import annotations

from workflow_compiler.codegen.temporal.generator import (
    _default_for,
    _pascal,
    _snake,
)
from workflow_compiler.models import (
    GeneratedFile,
    TemporalWorkflowDesign,
    WorkflowTrigger,
)


def generate_project_files(
    designs: dict[str, TemporalWorkflowDesign],
    triggers: list[WorkflowTrigger] | None = None,
) -> list[GeneratedFile]:
    """Render the shared project files for ``designs`` (keyed by workflow slug)."""
    ordered = sorted(designs.items())
    return [
        GeneratedFile(path="contracts.py", content=_contracts(ordered)),
        GeneratedFile(
            path="README.md",
            language="markdown",
            content=_readme(ordered, triggers or []),
        ),
    ]


def _contracts(ordered: list[tuple[str, TemporalWorkflowDesign]]) -> str:
    """One typed input dataclass per workflow, mirroring each bundle's shared.py."""
    lines = [
        '"""Shared cross-workflow contracts for this project.',
        "",
        "One typed input dataclass per workflow. Each workflow's own bundle",
        "defines the identical shape in its shared.py (bundles stay standalone);",
        "this file is the single project-wide reference for trigger payloads.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass, field",
        "from typing import Any",
        "",
    ]
    for slug, design in ordered:
        class_name = f"{_pascal(design.workflow_name)}Input"
        lines += ["", "@dataclass", f"class {class_name}:"]
        lines.append(f'    """Input to the standalone \'{slug}\' workflow."""')
        lines.append("")
        if design.workflow_inputs:
            seen: set[str] = set()
            for param in design.workflow_inputs:
                name = _snake(param.name)
                if not name or name in seen:
                    continue
                seen.add(name)
                annotation = (param.type or "str").strip() or "str"
                default = _default_for(annotation)
                if default == "None":
                    annotation = f"{annotation} | None"
                lines.append(f"    {name}: {annotation} = {default}")
        else:
            lines.append(
                "    payload: dict[str, Any] = field(default_factory=dict)"
                "  # TODO: define real fields"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _readme(
    ordered: list[tuple[str, TemporalWorkflowDesign]],
    triggers: list[WorkflowTrigger],
) -> str:
    """The project topology: workflows, task queues, and trigger edges."""
    lines = [
        "# Project workflows",
        "",
        "Every workflow below is standalone: each has its own bundle directory,",
        "worker, and task queue, and can be started independently. Cross-workflow",
        "relationships are explicit triggers (a generated activity starts the",
        "target by name) — never parent/child ownership.",
        "",
        "| Workflow | Bundle | Task queue |",
        "| --- | --- | --- |",
    ]
    for slug, design in ordered:
        queue = design.task_queue or f"{_snake(design.workflow_name)}-task-queue"
        lines.append(
            f"| {_pascal(design.workflow_name)} | `{slug.replace('-', '_')}/` | `{queue}` |"
        )
    lines.append("")
    if triggers:
        lines += ["## Trigger topology", ""]
        for trigger in triggers:
            mode = trigger.mode.value.replace("_", "-")
            condition = f" when `{trigger.condition}`" if trigger.condition else ""
            result = f" → `{trigger.result_binding}`" if trigger.result_binding else ""
            lines.append(
                f"- `{trigger.source_workflow}` —({mode}{condition})→ "
                f"`{trigger.target_workflow}`{result}"
            )
        lines += [
            "",
            "Run every worker (one per bundle) so triggers can start their targets.",
            "Workers read `TEMPORAL_ADDRESS` (default `localhost:7233`).",
        ]
    return "\n".join(lines).rstrip() + "\n"

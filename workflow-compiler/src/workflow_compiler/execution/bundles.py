"""Locate the on-disk bundle for a generated workflow, and describe how to run it.

Two facts drive everything here.

**The API never writes generated code to disk.** ``approve-spec`` stores the
bundle on the workflow state; only the CLI's ``--out-dir`` materializes it. So a
project approved through the UI has no directory to run, and the runner has to
create one.

**Execution reads from disk.** §3 of ``RUN_WORKFLOWS_HANDOFF.md`` is explicit
that the activity stubs are meant to be replaced by hand. Running the stored
bundle instead would silently execute placeholders and ignore the user's real
implementations. So the rule is: materialize **once**, never overwrite, always
execute what is on disk.

The workflow type and task queue are derived with the code generator's own
helpers rather than re-implemented. Two independent spellings of the same name
is precisely the failure mode of handoff §6.1 and §6.2 — a bundle that imports
cleanly, passes every static check, and then does not dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from workflow_compiler.codegen.temporal.generator import (
    TemporalPythonCodeGenerator,
    _pascal,
    _snake,
    workflow_input_summary,
)
from workflow_compiler.interfaces.executor import (
    RunnableWorkflow,
    SignalDescriptor,
    WorkflowInputField,
)
from workflow_compiler.models import TemporalWorkflowDesign, WorkflowState

#: Files that must be present for a directory to count as a runnable bundle.
_REQUIRED = ("worker.py", "workflow.py", "activities.py", "shared.py")

#: Proof that a generated ``worker.py`` connects to the *configured* Temporal
#: address rather than a baked-in one.
_ADDRESS_MARKER = 'os.environ.get("TEMPORAL_ADDRESS"'

#: The address older templates hardcoded. A bundle that predates
#: ``TEMPORAL_ADDRESS`` support always connects here, whatever the app is
#: configured to use.
LEGACY_WORKER_ADDRESS = "localhost:7233"


@dataclass(frozen=True)
class MaterializeResult:
    """What :func:`materialize_bundle` did, so the caller can report it."""

    directory: Path
    written: list[str]
    kept: list[str]

    @property
    def created(self) -> bool:
        return bool(self.written)


def bundle_dir(root: str | Path, project_id: str, slug: str) -> Path:
    """Where the bundle for one workflow lives: ``<root>/<project-id>/<slug>``."""
    return Path(root) / project_id / slug


def is_materialized(directory: Path) -> bool:
    """``True`` when ``directory`` holds a bundle that can actually be run."""
    return all((directory / name).is_file() for name in _REQUIRED)


def worker_honors_address(directory: Path) -> bool:
    """Whether ``directory``'s ``worker.py`` reads ``TEMPORAL_ADDRESS``.

    Bundles generated before that support connect to a hardcoded
    ``localhost:7233`` no matter what the app is configured with. Because runs
    execute the files on disk and never overwrite them, such a bundle can
    outlive the fix — and it fails in the worst possible way: the worker starts
    happily, connects to a *different* server, and the execution sits in
    ``running`` forever because nothing is polling its queue. Detecting it is
    the difference between an explanation and an unexplained hang.
    """
    try:
        return _ADDRESS_MARKER in (directory / "worker.py").read_text(encoding="utf-8")
    except OSError:
        return False


def materialize_bundle(
    state: WorkflowState, directory: Path, *, graph_ordered: bool = True
) -> MaterializeResult:
    """Write the bundle to ``directory``, **never overwriting an existing file**.

    Not overwriting is the whole point: the second run of a workflow whose
    ``activities.py`` the user has implemented must run *their* code. A file that
    is already there is therefore reported as ``kept``, never replaced — the
    caller can surface that, and a user who wants the pristine bundle back can
    delete the directory.

    The bundle is **re-rendered from the stored design**, not replayed from the
    stored ``temporal_code``. That distinction is load-bearing. ``temporal_code``
    is whatever codegen produced at approve time, and §6 of the handoff records
    that every bundle generated before 2026-08-12 carries real defects — signals
    registered under the wrong name, ``WorkflowInput`` missing fields the
    workflow reads. Writing those to disk would resurrect fixed bugs in code the
    user is about to run.

    It is also how this was caught: replaying the stored bundle wrote a
    ``worker.py`` predating the ``TEMPORAL_ADDRESS`` support, so the worker
    connected to the default address instead of the configured one, silently
    served a different server, and the execution sat in ``Running`` with its
    first workflow task never polled.

    Re-rendering is deterministic and LLM-free (§4.3). The stored files are kept
    only as a fallback for a state that has code but no design.
    """
    directory.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}
    if state.temporal_design is not None:
        bundle = TemporalPythonCodeGenerator().generate(
            state.temporal_design,
            graph=state.workflow_graph if graph_ordered else None,
        )
        files = {f.path: f.content for f in bundle.files}
    elif state.temporal_code is not None and state.temporal_code.files:
        files = {f.path: f.content for f in state.temporal_code.files}

    written: list[str] = []
    kept: list[str] = []
    for path, content in sorted(files.items()):
        target = directory / path
        if target.exists():
            kept.append(path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(path)

    return MaterializeResult(directory=directory, written=written, kept=kept)


def describe_runnable(
    *,
    slug: str,
    state: WorkflowState,
    root: str | Path,
    project_id: str,
) -> RunnableWorkflow:
    """Everything the UI needs to offer a Run of ``slug``.

    ``bundle_dir`` is ``None`` when nothing is on disk *and* nothing could be
    materialized — i.e. the workflow never reached codegen. That is a disabled
    control in the UI, not an error at click time (§5.4).
    """
    design = state.temporal_design
    directory = bundle_dir(root, project_id, slug)

    has_code = bool(state.temporal_code and state.temporal_code.files)
    available = is_materialized(directory) or has_code or design is not None

    if design is None:
        return RunnableWorkflow(
            slug=slug,
            workflow_id=state.workflow_id,
            workflow_type="",
            task_queue="",
            bundle_dir=str(directory) if is_materialized(directory) else None,
            inputs=[],
            signals=[],
        )

    return RunnableWorkflow(
        slug=slug,
        workflow_id=state.workflow_id,
        workflow_type=workflow_type_of(design),
        task_queue=task_queue_of(design),
        bundle_dir=str(directory) if available else None,
        inputs=input_fields_of(design),
        signals=signals_of(design),
    )


def workflow_type_of(design: TemporalWorkflowDesign) -> str:
    """The registered workflow type — the generated class name."""
    return _pascal(design.workflow_name)


def task_queue_of(design: TemporalWorkflowDesign) -> str:
    """The task queue the generated ``worker.py`` listens on."""
    return design.task_queue or f"{_snake(design.workflow_name)}-task-queue"


def input_fields_of(design: TemporalWorkflowDesign) -> list[WorkflowInputField]:
    """The ``WorkflowInput`` fields, with the §7 sample values as form defaults.

    Uses the generator's own field resolution, so a field recovered from a step
    binding (handoff §6.1) appears in the form exactly as it appears in
    ``shared.py``.
    """
    return [
        WorkflowInputField(name=name, type=annotation, sample=sample)
        for name, annotation, sample in workflow_input_summary(design)
    ]


def signals_of(design: TemporalWorkflowDesign) -> list[SignalDescriptor]:
    """Declared signals, under the names the **spec** gives them (§6.2)."""
    return [
        SignalDescriptor(name=signal.name, params=list(signal.payload or []))
        for signal in design.signals
    ]

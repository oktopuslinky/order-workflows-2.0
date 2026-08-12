"""Running generated Temporal bundles from inside the app.

The compiler emits code; this package executes it. It sits behind
:mod:`workflow_compiler.interfaces.executor` so no vendor SDK reaches the
compiler or the agents — ``execution.temporal`` is the single module that
imports ``temporalio``, and it does so lazily, because the SDK is an optional
extra (``pip install workflow-compiler[run]``).

Nothing here is imported at package-import time that would pull the SDK in, so
``from workflow_compiler.execution import ...`` is safe without it installed.
"""

from __future__ import annotations

from workflow_compiler.execution.bundles import (
    MaterializeResult,
    bundle_dir,
    describe_runnable,
    is_materialized,
    materialize_bundle,
)
from workflow_compiler.execution.fake import FakeExecutor
from workflow_compiler.execution.runs import Run, RunRegistry

__all__ = [
    "FakeExecutor",
    "MaterializeResult",
    "Run",
    "RunRegistry",
    "bundle_dir",
    "describe_runnable",
    "is_materialized",
    "materialize_bundle",
]

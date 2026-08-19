"""Bundle smoke test: compile + import the exported code base in a subprocess.

After the code stage every rewritten file has passed ``ast.parse`` and the sibling /
dataclass / ruff checks *individually*. What those checks cannot see is whether the
bundle **as a whole** imports — a circular import, a name a test double registers twice,
a decorator argument the SDK does not accept, ``from src.x import y`` against a module
that was rewritten differently. This module materialises the bundle in the export
layout (``src/…``, ``tests/…``) under a temporary directory and runs one child Python
process that ``py_compile``s every file and then imports every module in bundle order,
reporting per-module errors as JSON. Nothing runs inside the server process, and the
interpreter is configurable (``Settings.change_outputs_smoke_python``) so the smoke can
use a venv that has ``temporalio`` even when the server's does not.

The result is recorded on ``CodeChangeBundle.smoke`` and shown in the UI; it is a
*verdict about the draft*, never a gate — the human still reviews the diff.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from workflow_compiler.change_outputs.export import zip_code_path
from workflow_compiler.change_outputs.models import CodeChangeBundle, FileStatus, SmokeResult

_RUNNER = r"""
import importlib, json, py_compile, sys, traceback
root, files, modules = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
sys.path.insert(0, root)
out = {"compiled": 0, "compile_errors": [], "imported": [], "import_errors": {}}
for rel in files:
    try:
        py_compile.compile(root + "/" + rel, doraise=True)
        out["compiled"] += 1
    except Exception as exc:  # noqa: BLE001
        out["compile_errors"].append(f"{rel}: {exc}")
for mod in modules:
    try:
        importlib.import_module(mod)
        out["imported"].append(mod)
    except BaseException as exc:  # noqa: BLE001 - report SystemExit etc. too
        tb = traceback.format_exception_only(type(exc), exc)
        out["import_errors"][mod] = "".join(tb).strip()[-600:]
print(json.dumps(out))
"""


def bundle_layout(bundle: CodeChangeBundle) -> dict[str, str]:
    """``zip path → text`` for every non-removed Python file (README layout)."""
    layout: dict[str, str] = {}
    for f in bundle.files:
        if f.status is FileStatus.REMOVED or not f.path.endswith(".py"):
            continue
        layout[
            zip_code_path(f.path, code_root=bundle.code_root, import_root=bundle.import_root)
        ] = f.updated
    return layout


def module_names(layout: dict[str, str], bundle: CodeChangeBundle) -> list[str]:
    """Dotted module names to import, bundle order first, tests last, ``__init__`` as package."""
    order = [
        zip_code_path(p, code_root=bundle.code_root, import_root=bundle.import_root)
        for p in bundle.order
    ]
    seen: list[str] = []
    for zpath in order + sorted(layout):
        if zpath not in layout or zpath in seen:
            continue
        seen.append(zpath)
    names: list[str] = []
    for zpath in seen:
        parts = zpath[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        name = ".".join(parts)
        if name not in names:
            names.append(name)
    return names


def _ensure_packages(root: Path, layout: dict[str, str]) -> None:
    """Add ``__init__.py`` to every directory on the way to a module when the corpus lacks it."""
    for zpath in list(layout):
        parts = zpath.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            init = "/".join(parts[:depth]) + "/__init__.py"
            if init not in layout and not (root / init).exists():
                (root / init).parent.mkdir(parents=True, exist_ok=True)
                (root / init).write_text("", encoding="utf-8")


def _run_sync(bundle: CodeChangeBundle, python: str, timeout: float) -> SmokeResult:
    layout = bundle_layout(bundle)
    started = time.perf_counter()
    if not layout:
        return SmokeResult(status="skipped", note="no Python files in the bundle", python=python)
    with tempfile.TemporaryDirectory(prefix="wc-smoke-") as tmp:
        root = Path(tmp)
        for zpath, text in layout.items():
            target = root / zpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        _ensure_packages(root, layout)
        runner = root / "_smoke_runner.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        modules = module_names(layout, bundle)
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("PYTHONPATH", None)
        try:
            proc = subprocess.run(
                [
                    python,
                    str(runner),
                    root.as_posix(),
                    json.dumps(sorted(layout)),
                    json.dumps(modules),
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return SmokeResult(
                status="failed",
                python=python,
                note=f"smoke test timed out after {timeout:.0f}s",
                seconds=time.perf_counter() - started,
            )
        except OSError as exc:
            return SmokeResult(
                status="skipped",
                python=python,
                note=f"could not start the smoke interpreter: {exc}",
                seconds=time.perf_counter() - started,
            )
        line = (proc.stdout or "").strip().splitlines()
        payload: dict[str, object] = {}
        if line:
            try:
                parsed = json.loads(line[-1])
                if isinstance(parsed, dict):
                    payload = parsed
            except ValueError:
                payload = {}
        if not payload:
            return SmokeResult(
                status="failed",
                python=python,
                note=(
                    "smoke runner produced no verdict"
                    + (f": {proc.stderr.strip()[-600:]}" if proc.stderr else "")
                ),
                seconds=time.perf_counter() - started,
            )
        def _strings(key: str) -> list[str]:
            value = payload.get(key)
            return [str(v) for v in value] if isinstance(value, list) else []

        compile_errors = _strings("compile_errors")
        imported = _strings("imported")
        raw_import_errors = payload.get("import_errors")
        pairs = raw_import_errors.items() if isinstance(raw_import_errors, dict) else []
        import_errors = {str(k): str(v) for k, v in pairs}
        raw_compiled = payload.get("compiled")
        compiled = raw_compiled if isinstance(raw_compiled, int) else 0
        status = "failed" if compile_errors or import_errors else "passed"
        return SmokeResult(
            status=status,
            python=python,
            compiled=compiled,
            compile_errors=compile_errors,
            imported=imported,
            import_errors=import_errors,
            modules=modules,
            seconds=time.perf_counter() - started,
        )


async def run_smoke(
    bundle: CodeChangeBundle, *, python: str = "", timeout: float = 180.0
) -> SmokeResult:
    """Compile + import the bundle in a child interpreter (never raises)."""
    interpreter = python or sys.executable
    try:
        return await asyncio.to_thread(_run_sync, bundle, interpreter, timeout)
    except Exception as exc:  # pragma: no cover - defensive: a smoke must never break the stage
        return SmokeResult(status="skipped", python=interpreter, note=f"smoke test error: {exc}")


__all__ = ["bundle_layout", "module_names", "run_smoke"]

"""Reset the demo state: list (default) or delete knowledge bases, change requests and projects.

Dry run by default — nothing is removed unless ``--yes`` is given. Meant for the RUNBOOK's
"reset the demo state" recipe: it walks ``<state-root>`` (default ``.workflow_state``), shows what
would go, backs everything up to a zip first, and only then deletes. Users and generated bundles
are never touched (pass ``--generated`` to also remove ``generated/<project-id>/``).

Examples::

    python scripts/reset_demo_state.py                      # dry run: what is there
    python scripts/reset_demo_state.py --yes                # delete everything (after a backup zip)
    python scripts/reset_demo_state.py --yes --keep 86d9919378bd4ebe8329f8ff950a2a27 \
        --keep dfad0d257db847919029f11dbef3c47d              # keep the reference KB + CR
    python scripts/reset_demo_state.py --only projects --yes  # projects (+ their workflow states)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def _load(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--root", default=".workflow_state", help="state root (default .workflow_state)"
    )
    parser.add_argument("--yes", action="store_true", help="actually delete (default: dry run)")
    parser.add_argument("--keep", action="append", default=[], help="id to keep (repeatable)")
    parser.add_argument(
        "--only",
        choices=["all", "knowledge_bases", "change_requests", "projects"],
        default="all",
        help="restrict to one kind",
    )
    parser.add_argument(
        "--generated", action="store_true", help="also remove generated/<project-id>/"
    )
    parser.add_argument("--no-backup", action="store_true", help="skip the backup zip")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"no state root at {root.resolve()}")
        return 0
    keep = set(args.keep)
    wanted = (
        {"knowledge_bases", "change_requests", "projects"} if args.only == "all" else {args.only}
    )

    plan: list[tuple[str, str, list[Path]]] = []  # (kind, id, paths)
    if "knowledge_bases" in wanted:
        for record in sorted((root / "knowledge_bases").glob("*.json")):
            kb_id = record.stem
            if kb_id in keep:
                continue
            paths = [record]
            if (root / "knowledge_bases" / kb_id).is_dir():
                paths.append(root / "knowledge_bases" / kb_id)
            plan.append(("knowledge_base", f"{kb_id} ({_load(record).get('name', '?')})", paths))
    if "change_requests" in wanted:
        for record in sorted((root / "change_requests").glob("*.json")):
            if record.stem in keep:
                continue
            plan.append(
                ("change_request", f"{record.stem} ({_load(record).get('title', '?')})", [record])
            )
    if "projects" in wanted:
        for record in sorted((root / "projects").glob("*.json")):
            if record.stem in keep:
                continue
            payload = _load(record)
            paths = [record]
            workflow_ids = payload.get("workflow_ids")
            if isinstance(workflow_ids, dict):
                for wf_id in workflow_ids.values():
                    state = root / f"{wf_id}.json"
                    if state.is_file():
                        paths.append(state)
            if args.generated and (Path("generated") / record.stem).is_dir():
                paths.append(Path("generated") / record.stem)
            plan.append(
                (
                    "project",
                    f"{record.stem} ({payload.get('nickname') or payload.get('stage', '?')})",
                    paths,
                )
            )

    if not plan:
        print("nothing to remove")
        return 0
    for kind, label, paths in plan:
        print(f"{'DELETE' if args.yes else 'would delete'} {kind:15} {label}")
        for p in paths:
            print(f"    {p}")
    if not args.yes:
        print(
            f"\n{len(plan)} record(s) — dry run; add --yes to delete (backup zip first)."
        )
        return 0

    if not args.no_backup:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = root / f"backup-{stamp}.zip"
        with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
            for _kind, _label, paths in plan:
                for p in paths:
                    if p.is_dir():
                        for sub in p.rglob("*"):
                            if sub.is_file():
                                archive.write(sub, sub.relative_to(root.parent).as_posix())
                    elif p.is_file():
                        archive.write(
                            p,
                            p.relative_to(root.parent).as_posix()
                            if p.is_relative_to(root.parent)
                            else p.name,
                        )
        print(f"backup written: {backup}")
    for _kind, _label, paths in plan:
        for p in paths:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    print(f"deleted {len(plan)} record(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

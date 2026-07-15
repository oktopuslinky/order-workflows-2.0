"""Stage-1 recon: compile the multi-workflow example against live Nemotron and
dump the real findings, so the recorded take knows which edits actually clear them.

Not part of the shipped app. Run: python demo/recon.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import httpx

API = "http://localhost:8000"
DOC = pathlib.Path(__file__).parent.parent / "examples" / "multi_workflow.md"
OUT = pathlib.Path(__file__).parent / "recon-plain"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=1200.0)

    t0 = time.time()
    log(f"compile-upload {DOC.name} ...")
    with DOC.open("rb") as fh:
        resp = client.post(
            f"{API}/projects/compile-upload",
            files={"file": (DOC.name, fh, "text/markdown")},
            data={"persist": "true"},
        )
    resp.raise_for_status()
    payload = resp.json()
    compile_s = time.time() - t0
    project = payload["project"]
    pid = project["project_id"]
    log(f"compiled in {compile_s:.0f}s -> project {pid}")
    (OUT / "01-compile.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    slugs = [s.get("slug") for s in project.get("specs", [])]
    log(f"stage={project.get('stage')} specs={slugs}")
    log(f"cross_references={len(project.get('cross_references', []))} "
        f"triggers={len(project.get('triggers', []))}")

    t1 = time.time()
    log("validate ...")
    resp = client.post(f"{API}/projects/{pid}/validate", json={})
    resp.raise_for_status()
    payload = resp.json()
    validated = payload["project"]
    validate_s = time.time() - t1
    log(f"validated in {validate_s:.0f}s")
    (OUT / "02-validate.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Keep the rendered spec markdown -- the take edits these exact buffers.
    for slug, md in (payload.get("spec_markdown") or {}).items():
        (OUT / f"spec-{slug}.md").write_text(md, encoding="utf-8")

    # Human-readable findings digest -- this is what drives the shot list.
    findings_by_slug: dict[str, list[dict]] = validated.get("validation_findings", {}) or {}
    lines: list[str] = [
        f"# Recon findings — project {pid}",
        "",
        f"- compile: {compile_s:.0f}s",
        f"- validate: {validate_s:.0f}s",
        f"- stage: {validated.get('stage')}",
        f"- warnings: {validated.get('warnings') or 'none'}",
        "",
    ]
    for slug, findings in findings_by_slug.items():
        blocking = [f for f in findings if f.get("severity") == "blocking"]
        lines += [f"## {slug} — {len(blocking)} blocking / {len(findings)} total", ""]
        for f in findings:
            loc = " / ".join(x for x in (f.get("section"), f.get("field")) if x)
            lines.append(
                f"- **{f.get('severity')}** ({loc or 'general'}) {f.get('message')}"
                + (f"\n    - suggestion: {f['suggestion']}" if f.get("suggestion") else "")
            )
        lines.append("")

    digest = "\n".join(lines)
    (OUT / "findings.md").write_text(digest, encoding="utf-8")
    print("\n" + digest)

    log(f"project_id={pid}  (keep this for the take)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

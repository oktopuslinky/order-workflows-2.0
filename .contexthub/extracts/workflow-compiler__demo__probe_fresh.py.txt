"""One clean end-to-end run on a VIRGIN compile of the ideal doc.

The previous probe reused a project that had been through several validate passes,
and two of its three workflows scored 0.40/0.45 graph health -- below the 0.90 gate.
The suspicion is that repeated validation strips facts and degrades the graph, not
that the document is bad (the repo already contains a successful 3-bundle run of it).

This settles it: compile fresh, confirm, validate once, approve. Whatever comes out
here is what the recorded take will show.

Run: python demo/probe_fresh.py
"""

from __future__ import annotations

import collections
import json
import pathlib
import re
import sys
import time

import httpx

API = "http://localhost:8000"
DOC = pathlib.Path(__file__).parent.parent / "examples" / "ideal_multi_workflow.md"
OUT = pathlib.Path(__file__).parent / "recon"
ANSWER = "Confirmed — descriptive only; not used by code generation."


def confirm_all(md: str) -> str:
    md = md.replace("- [ ]", "- [x]")
    return re.sub(r"(?m)^(\s*)Answer:\s*$", rf"\1Answer: {ANSWER}", md)


def health(project: dict) -> None:
    for slug, findings in (project.get("validation_findings") or {}).items():
        sev = collections.Counter(f["severity"] for f in findings)
        print(f"  {slug}: {dict(sev)}")
        for f in findings:
            if f["severity"] == "blocking":
                print(f"      BLOCK: {f['message'][:110]}")


def main() -> int:
    client = httpx.Client(timeout=2400.0)

    t = time.time()
    print(f"compile {DOC.name} (fresh) ...")
    with DOC.open("rb") as fh:
        r = client.post(
            f"{API}/projects/compile-upload",
            files={"file": (DOC.name, fh, "text/markdown")},
            data={"persist": "true"},
        )
    r.raise_for_status()
    payload = r.json()
    pid = payload["project"]["project_id"]
    print(f"compiled in {time.time() - t:.0f}s -> {pid}")
    print(f"specs: {list(payload['spec_markdown'])}")

    edited = {s: confirm_all(m) for s, m in payload["spec_markdown"].items()}
    client.put(f"{API}/projects/{pid}/spec", json={"spec_markdown": edited})
    print("confirmed all deps / triggers / questions")

    t = time.time()
    print("\nvalidate ...")
    r = client.post(f"{API}/projects/{pid}/validate", json={})
    r.raise_for_status()
    print(f"validated in {time.time() - t:.0f}s")
    health(r.json()["project"])

    specs2 = client.get(f"{API}/projects/{pid}").json()["spec_markdown"]
    if sum(m.count("- [ ]") for m in specs2.values()):
        specs2 = {s: confirm_all(m) for s, m in specs2.items()}
        client.put(f"{API}/projects/{pid}/spec", json={"spec_markdown": specs2})
        print("re-confirmed boxes that validate re-opened")

    t = time.time()
    print("\napprove ...")
    r = client.post(
        f"{API}/projects/{pid}/approve",
        json={"reviewer": "demo", "spec_markdown": specs2},
    )
    if r.status_code >= 400:
        print(f"REFUSED {r.status_code}: {json.dumps(r.json())[:600]}")
        return 1
    proj = r.json()["project"]
    print(f"approved in {time.time() - t:.0f}s -> stage={proj['stage']}")
    health(proj)

    files = client.get(f"{API}/projects/{pid}/files").json()["files"]
    print(f"\n{len(files)} files:")
    for f in files:
        print("  ", f["path"])

    print(f"\nPROJECT_ID={pid}")
    (OUT / "06-fresh.json").write_text(json.dumps(r.json(), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

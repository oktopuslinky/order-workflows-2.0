"""Does the 400s timeout actually let approve finish, and what do the warnings look like?

Two questions the take must not discover on camera:
  1. Does codegen complete now that the LLM timeout is configurable? (It died at 60s before.)
  2. What is left in the Findings panel? The user does not want a wall of warnings on screen.

Run: python demo/probe_approve.py <project-id>
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys
import time

import httpx

API = "http://localhost:8000"
OUT = pathlib.Path(__file__).parent / "recon-plain"


def main() -> int:
    pid = sys.argv[1]
    client = httpx.Client(timeout=1800.0)

    proj = client.get(f"{API}/projects/{pid}").json()
    slugs = list(proj["spec_markdown"])
    print(f"project {pid}  specs={slugs}  stage={proj['project']['stage']}")

    t = time.time()
    print("approve (no overrides) ...")
    r = client.post(
        f"{API}/projects/{pid}/approve",
        json={"reviewer": "demo", "spec_markdown": proj["spec_markdown"]},
    )
    took = time.time() - t

    if r.status_code >= 400:
        print(f"APPROVE REFUSED in {took:.0f}s -> {r.status_code}")
        print(json.dumps(r.json(), indent=2)[:1200])
        return 1

    payload = r.json()
    project = payload["project"]
    print(f"APPROVE OK in {took:.0f}s")
    print(f"  stage       : {project['stage']}")
    print(f"  workflow_ids: {project.get('workflow_ids')}")

    # What will the Findings panel show?
    print("\n--- findings that would be on screen ---")
    for slug, findings in (project.get("validation_findings") or {}).items():
        by_sev = collections.Counter(f["severity"] for f in findings)
        print(f"\n{slug}: {dict(by_sev)}")
        for f in findings:
            if f["severity"] != "info":
                loc = " / ".join(x for x in (f.get("section"), f.get("field")) if x)
                print(f"  [{f['severity']}] ({loc or 'general'}) {f['message'][:110]}")

    files = client.get(f"{API}/projects/{pid}/files").json()["files"]
    print(f"\n--- generated {len(files)} files ---")
    for f in files[:30]:
        print("  ", f["path"])

    (OUT / "04-approved.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

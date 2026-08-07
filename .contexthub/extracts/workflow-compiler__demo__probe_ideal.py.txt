"""Prove the whole ideal-doc path headlessly before spending an hour recording it.

Does exactly what the take will do in the UI, but over the API:
  1. tick every cross-workflow dependency + trigger checkbox
  2. answer every open question
  3. validate
  4. approve (no overrides)
  5. report the warnings that will be on screen, and the files generated

If this comes back clean, the take is a formality. If it does not, better to find
out here than 40 minutes into a recording.

Run: python demo/probe_ideal.py <project-id>
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
OUT = pathlib.Path(__file__).parent / "recon"

ANSWER = "Confirmed — descriptive only; state transitions are not used by code generation."


def confirm_all(md: str) -> str:
    """Tick every unchecked box and fill any blank `Answer:` line.

    This is precisely what the DependencyChecklist / TriggerCards / OpenQuestions
    widgets do in the UI -- the spec Markdown is the single source of truth, and
    the widgets are just a typed editor over it.
    """
    md = md.replace("- [ ]", "- [x]")
    # `Answer:` lines left blank by the model are what the approve gate refuses on.
    md = re.sub(r"(?m)^(\s*)Answer:\s*$", rf"\1Answer: {ANSWER}", md)
    return md


def show(project: dict, files: list[dict] | None = None) -> None:
    print(f"  stage       : {project['stage']}")
    print(f"  workflow_ids: {list((project.get('workflow_ids') or {}))}")
    total = collections.Counter()
    for slug, findings in (project.get("validation_findings") or {}).items():
        sev = collections.Counter(f["severity"] for f in findings)
        total.update(sev)
        print(f"  {slug}: {dict(sev)}")
        for f in findings:
            if f["severity"] == "blocking":
                print(f"      BLOCK: {f['message'][:110]}")
    print(f"  TOTAL: {dict(total)}")
    if files is not None:
        print(f"  files: {len(files)}")


def main() -> int:
    pid = sys.argv[1]
    client = httpx.Client(timeout=1800.0)

    proj = client.get(f"{API}/projects/{pid}").json()
    specs = proj["spec_markdown"]
    print(f"project {pid}  specs={list(specs)}  stage={proj['project']['stage']}")

    edited = {slug: confirm_all(md) for slug, md in specs.items()}
    unchecked = sum(md.count("- [ ]") for md in edited.values())
    print(f"\nticked all checkboxes / filled answers (remaining unchecked: {unchecked})")

    client.put(f"{API}/projects/{pid}/spec", json={"spec_markdown": edited})

    t = time.time()
    print("\nvalidate ...")
    r = client.post(f"{API}/projects/{pid}/validate", json={})
    r.raise_for_status()
    print(f"validated in {time.time() - t:.0f}s")
    show(r.json()["project"])

    # Re-read: validate re-renders the specs (and may strip ungrounded lines).
    specs2 = client.get(f"{API}/projects/{pid}").json()["spec_markdown"]
    still_open = sum(md.count("- [ ]") for md in specs2.values())
    if still_open:
        print(f"\nWARN: validate re-opened {still_open} checkbox(es); re-confirming")
        specs2 = {s: confirm_all(m) for s, m in specs2.items()}
        client.put(f"{API}/projects/{pid}/spec", json={"spec_markdown": specs2})

    t = time.time()
    print("\napprove (no overrides) ...")
    r = client.post(
        f"{API}/projects/{pid}/approve",
        json={"reviewer": "demo", "spec_markdown": specs2},
    )
    took = time.time() - t
    if r.status_code >= 400:
        print(f"APPROVE REFUSED in {took:.0f}s -> {r.status_code}")
        print(json.dumps(r.json(), indent=2)[:900])
        return 1

    payload = r.json()
    print(f"APPROVE OK in {took:.0f}s")
    files = client.get(f"{API}/projects/{pid}/files").json()["files"]
    show(payload["project"], files)

    print("\n--- warnings that will be on screen ---")
    for slug, findings in (payload["project"].get("validation_findings") or {}).items():
        for f in findings:
            if f["severity"] == "warning":
                print(f"  [{slug}] {f['message'][:100]}")

    print("\n--- generated ---")
    for f in files:
        print("  ", f["path"])

    (OUT / "05-ideal-approved.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

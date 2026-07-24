"""Prove the gate has teeth before we film it.

Question: does the validator actually emit a BLOCKING finding when a
cross-workflow hand-off is broken? project_compiler.py:344 says a trigger mapping
to an input the target does not declare is BLOCKING -- but claims in code are not
evidence. So: rename account-provisioning's `customer_record_id` input, validate,
and see what comes back.

If this goes blocking, Act III of the demo is a real correction loop:
break -> validate catches it -> fix -> validate clean -> approve unlocks.

Run: python demo/probe_gate.py <project-id>
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import httpx

API = "http://localhost:8000"
OUT = pathlib.Path(__file__).parent / "recon-plain"


def summarize(project: dict, title: str) -> None:
    print(f"\n=== {title} ===")
    print(f"stage: {project.get('stage')}")
    for slug, findings in (project.get("validation_findings") or {}).items():
        blocking = [f for f in findings if f.get("severity") == "blocking"]
        print(f"  {slug}: {len(blocking)} blocking / {len(findings)} total")
        for f in blocking:
            print(f"    BLOCK: {f.get('message')}")
            if f.get("suggestion"):
                print(f"           -> {f['suggestion']}")


def main() -> int:
    pid = sys.argv[1]
    client = httpx.Client(timeout=600.0)

    specs = {
        p.stem.replace("spec-", ""): p.read_text(encoding="utf-8")
        for p in OUT.glob("spec-*.md")
    }
    print("specs:", list(specs))

    # --- break the hand-off -------------------------------------------------
    ap = specs["account-provisioning"]
    assert "- customer_record_id" in ap, "input line not found; spec shape changed"
    broken = ap.replace("- customer_record_id", "- cust_record_id", 1)
    edited = dict(specs)
    edited["account-provisioning"] = broken

    print("\nPUT edited spec (account-provisioning input renamed -> cust_record_id)")
    r = client.put(f"{API}/projects/{pid}/spec", json={"spec_markdown": edited})
    r.raise_for_status()

    t = time.time()
    print("validate (broken) ...")
    r = client.post(f"{API}/projects/{pid}/validate", json={})
    r.raise_for_status()
    payload = r.json()
    summarize(payload["project"], f"BROKEN — validated in {time.time()-t:.0f}s")
    (OUT / "03-broken.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # --- put it back --------------------------------------------------------
    print("\nPUT original spec back")
    r = client.put(f"{API}/projects/{pid}/spec", json={"spec_markdown": specs})
    r.raise_for_status()

    t = time.time()
    print("validate (restored) ...")
    r = client.post(f"{API}/projects/{pid}/validate", json={})
    r.raise_for_status()
    payload = r.json()
    summarize(payload["project"], f"RESTORED — validated in {time.time()-t:.0f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())

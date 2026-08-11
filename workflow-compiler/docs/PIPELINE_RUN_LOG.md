# Pipeline run log — Spark (local eGPU) verification, and the cloud runbook

Companion to `PIPELINE_HANDOFF.md`. That document is the plan; this one records what
was **actually measured** on 2026-08-11, corrects three things the handoff got wrong,
and leaves a runbook for the cloud half.

---

## 1. Corrections to `PIPELINE_HANDOFF.md`

Three claims in the handoff did not survive checking. None invalidate its plan.

### 1.1 §8 — "no new mypy errors (6 pre-existing …)". The baseline is **35**, not 6.

Verified by checking `HEAD` out into a separate worktree and diffing the error sets:

```bash
git worktree add C:/Users/devag/bh HEAD --detach     # short path: the repo's own
cd C:/Users/devag/bh/workflow-compiler                # paths overflow MAX_PATH
<venv>/Scripts/python -m mypy src                     # → Found 35 errors in 13 files
```

The working tree also reports 35, and the two sets are **identical** — so the §8 changes
and everything added since introduce zero new errors. But `mypy src` does **not** pass,
which contradicts `CLAUDE.md` ("`mypy --strict` must pass"). Either the gate is aspirational
or it regressed silently. Worth a decision; it is not a blocker.

### 1.2 §6.1 item 3 (the dialogue clobber) — real, but the prescribed fix was harder than needed.

The bug is **confirmed by construction**, not suspicion:

- `page.tsx` re-seeds `buffers` only when `project_id` changes (the `useEffect` guarded by
  `seededFor`), so a server-side spec change never reaches the editor.
- `DialoguePanel` only called `queryClient.invalidateQueries(["project", id])` — that
  refreshes `data`, not `buffers`.
- Approve posts `spec_markdown: buffers`. Stale buffers therefore overwrite the dialogue's
  applied answers.

The handoff said to reproduce it in a browser first, and implied the fix needs to wait for a
refetch. It missed that **`DialogueResponse` already carries freshly-rendered
`spec_markdown`** (`api/app.py::_dialogue_response`). So the fix hands the exact new content
straight to the parent — no refetch race, no ref-flag dance:

- `DialoguePanel` gained an `onSpecUpdated(specMarkdown)` prop, fired from `settle()` **only**
  when `changes.length > 0 || parked_as` — so a skip, or merely opening a session, does not
  disturb what the user is editing.
- `page.tsx::adoptDialogueSpec` adopts it and sets `dirty = true`, re-arming the gate so
  Approve waits for a fresh validate.

### 1.3 §6.3 item 7 (silent extraction) — right symptom, wrong mechanism.

The handoff says `extract_facts` is "called *without* a sub-reporter … unlike segmentation
which wires `set_progress(self._sub_reporter(progress))`". In fact `WorkflowCompiler._run_agents`
**already** wires `set_progress` onto every agent it runs, and `extract_facts` delegates to it.
The real defect is narrower: `project_compiler.py` never passed a `progress` **sink**, so
`_emit` had nothing to deliver to.

Also note `_sub_reporter` returns a *different shape* from `ProgressCallback` — it is the
`report(name, status, index, total, …)` adapter agents call, not a `Callable[[ProgressEvent], None]`.
Passing it where a `ProgressCallback` belongs would have failed. The fix is `_nested_progress()`,
which relays inner events under the `review-pass` phase that consumers already indent, prefixed
with the workflow slug.

---

## 2. What is now verified on the Spark (local eGPU)

Model used throughout: `NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` (the only one that serves).

| Stage | Result |
|---|---|
| Model health (§3.1) | **Unchanged**: 1 of 5 serving. `gpt-oss-120b/20b/8b`, `qwen3.5-9b` all HTTP 502 "Inference server unreachable" |
| `compile` (CLI, `--provider local`) | ✅ **936s** on `examples/multi_workflow.md` (§4.3 predicted 945s) |
| Segmentation | ✅ 90.18s (`discover` 52.6s + 3 review passes) |
| `extract:onboarding` | ✅ metadata_review 139.8s + facts_review; `extract:provisioning` 358.0s |
| 2 specs + cross-workflow dependency | ✅ `onboarding.customer_record_id → provisioning.customer_record_id` (UNCONFIRMED, as expected) |
| Nested progress (§6.3.7 fix) | ✅ Verified live — emits `onboarding:generate`, `onboarding:review:completeness`, … where it used to print nothing for ~7 min |
| Model health probe (§6.3.8 fix) | ✅ Verified live — 9.3s for all five, correctly flags 4 dead / 1 alive |

Spark project id: `3978f39e-85de-46a7-a55c-92d859082739` (spec dir `./specs-local`).

### Cloud, partially verified (off-GPU, so it ran in parallel)

| Check | Result |
|---|---|
| `nemotron` provider reachable + key valid | ✅ 3.3s round trip, `nvidia/llama-3.3-nemotron-super-49b-v1` |
| Cloud compile via the **UI's own routing** (`POST /projects/compile`, `provider=nemotron`) | ✅ HTTP 200 in **149s**, `spec_drafted` — project `6bd74f67-c355-4812-b03b-1af72837bbe3` |

This is the same endpoint and provider-selection path the browser's "Nemotron (cloud)" option
uses, so cloud **compile** is proven. Cloud **dialogue** is not — question drafting and answer
interpretation are separate LLM calls (§7.4) and remain untested.

> ⚠️ `NVIDIA_API_KEY` was **not** rotated before these runs, at the operator's instruction.
> It is still in git history (§1). Rotate at [build.nvidia.com](https://build.nvidia.com).

---

## 3. Fixes landed in this pass

All in the working tree, with tests. `471 passed` (up from 462), `ruff check src tests` clean,
`mypy src` unchanged at the 35-error baseline, frontend `tsc --noEmit` and `next build` clean.

| § | Fix | Files | Tests |
|---|---|---|---|
| 6.1.1 | Empty completions handled distinctly from malformed JSON: a clean re-ask instead of quoting a parse error back with an empty assistant turn, and a `ProviderResponseError` (not `SchemaValidationError`) when every attempt comes back empty | `llm/base.py` | 3 |
| 6.1.2 | Provider failures map to **502**, timeouts to **504** — not 500 | `api/app.py::_guard` | 5 (parametrized) |
| 6.1.3 | The dialogue clobber (see §1.2 above) | `components/DialoguePanel.tsx`, `app/projects/[id]/page.tsx` | UI acceptance |
| 6.3.7 | Fact extraction reports nested progress | `project_compiler.py::_nested_progress` | 1 |
| 6.3.8 | Opt-in, **serial** model health probe; dead models disabled in the picker | `api/app.py`, `api/schemas.py`, `api/dependencies.py`, `app/page.tsx`, `lib/api.ts`, `lib/types.ts` | live-verified |

The probe is opt-in and serial on purpose: the eGPU is a single card with no queueing (§3.2),
so probing on page load would compete with — and could time out — a running compile.

---

## 4. Runbook — the cloud pass

Prerequisites: rotate `NVIDIA_API_KEY` first, then start the stack.

```bash
# Terminal 1 — backend. Use `nemotron` explicitly; `local-fallback` would let a Spark
# hiccup silently satisfy a "cloud" run (§1 of the handoff).
PYTHONUTF8=1 WORKFLOW_COMPILER_LLM_PROVIDER=nemotron WORKFLOW_COMPILER_LLM_TIMEOUT=900 \
  .venv/Scripts/python -m uvicorn workflow_compiler.api.app:app --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

### 4.1 CLI chain

```bash
SPECS=./specs-cloud
M=nvidia/llama-3.3-nemotron-super-49b-v1

PYTHONUTF8=1 .venv/Scripts/workflow-compiler compile examples/multi_workflow.md \
  --provider nemotron --model $M --timeout 600 --spec-dir $SPECS
PYTHONUTF8=1 .venv/Scripts/workflow-compiler validate <project-id> --spec-dir $SPECS \
  --provider nemotron --model $M --timeout 600
PYTHONUTF8=1 .venv/Scripts/workflow-compiler approve-spec <project-id> --spec-dir $SPECS \
  --provider nemotron --model $M --timeout 600
```

Verify per §4.1's table — do not just check exit codes. In particular confirm the
**compensations** (`rollback provisioning`, `deconfigure account`) survive into the generated
saga; that is the field most at risk (§5).

### 4.2 The 8 acceptance cases (§7.4), driven through the real UI

Playwright is installed in `demo/capture2` (`npm install` + `npx playwright install chromium`
already run). The script drives the browser, never asserts on LLM wording, and writes its own
JSON report:

```bash
cd demo/capture2
node dialogue-acceptance.mjs <project-id> --provider-label=cloud
# → acceptance-cloud.json ; exit 0 = all cases passed
```

`validate` must have run first, or `POST /dialogue` returns 400 "Nothing to resolve" (§7.3).
Diff `acceptance-cloud.json` against `acceptance-local.json` — differences between providers
in grouping and follow-up behavior are exactly what §7.4 warns to look for.

### 4.3 Generated bundle against Temporal

```bash
temporal server start-dev --headless --port 7233     # terminal 1
cd generated/<project-id>/<slug>
python worker.py                                     # terminal 2
python starter.py                                    # terminal 3
```

---

## 5. Gotchas worth keeping

- **`local-fallback` invalidates a provider claim.** It silently succeeds via cloud. Use
  `local` or `nemotron` explicitly whenever a run is meant to prove something about one of them.
- **`--timeout` defaults to 120s**, far below what the Spark needs. Use 600.
- **`PYTHONUTF8=1`** for any redirected CLI output — the `→` progress glyph is not cp1252.
- **Never touch the gateway during a compile** (§3.2). One GPU, no queueing; a stray probe
  inflates latency past `llm_timeout` and kills the run.
- **`git worktree add` fails inside this repo's own tree** — the checked-in `generated/` and
  `.contexthub/` paths overflow Windows `MAX_PATH`. Use a short target like `C:/Users/<you>/bh`.
- **Reasoning must stay on** (§5). `enable_thinking=false` is 13x faster but drops
  compensations and hallucinates state transitions. The mechanism is preserved but disabled in
  `GatewaySessionProvider.EXTRA_BODY`; the `_resolve_content()` override that promotes
  `reasoning_content` is consequently **unreachable dead code** today — deliberate, but it means
  that seam ships untested.

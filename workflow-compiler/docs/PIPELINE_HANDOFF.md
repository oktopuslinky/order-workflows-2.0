# Pipeline Handoff — full-pipeline runs on local eGPU and cloud, and finishing the natural-language spec editor

**Status date:** 2026-08-11 · **Branch:** `feat/spec-dialogue` (based on `master` @ `ed7c343`)

Two jobs, in this order:

1. **Get the *entire* pipeline verified end to end on both providers** — the local DGX Spark
   eGPU gateway and the NVIDIA cloud API. Today only the front half is proven, and only on
   local, and only from the CLI.
2. **Finish the natural-language spec editing tool** (the "Resolve" chat). The code is built
   and committed; it has never been executed once, against any provider.

Everything below is measured, not assumed. Where something is a *suspicion* it says so —
please do not act on those without confirming first.

---

## 0. What is actually verified today

**Updated 2026-08-11 after a Spark verification session.** Measurements and three
corrections to this document are in **`docs/PIPELINE_RUN_LOG.md`** — read that first.

| Stage | Local eGPU | Cloud | Notes |
|---|---|---|---|
| Ingestion (`.md`) | ✅ | ✅ | `.docx/.pdf/.html/.txt` paths still untested on both |
| Segmentation (+3 review passes) | ✅ | ✅ | 90s local (was 113s) |
| Fact extraction per workflow | ✅ | ✅ | 358–420s *per workflow* local |
| Spec file render → human gate | ✅ | ✅ | 2 specs, cross-workflow dep detected |
| `validate` | 🟡 | ❌ | started, killed mid-run at end of session — **resume here** |
| **Dialogue / Resolve chat** | ❌ | ❌ | **still never run** — blocked on `validate` (§7.3) |
| `approve-spec` → graph → CVPA → Temporal design → codegen | ❌ | ❌ | never run; CVPA + design are LLM stages |
| Compile **via the UI** | ❌ | 🟡 | cloud proven at the **API** layer the UI calls; browser click itself untested |

Measured this session:

- **Spark CLI compile: ✅ 936s** on `examples/multi_workflow.md` (`--provider local`, strict).
  Project **`3978f39e-85de-46a7-a55c-92d859082739`**, spec dir **`./specs-local`**.
  Both specs written; `onboarding.customer_record_id → provisioning.customer_record_id`
  detected, UNCONFIRMED as expected.
- **Cloud compile: ✅ 149s** via `POST /projects/compile` with `provider=nemotron` — the same
  routing the UI's "Nemotron (cloud)" option uses. Project **`6bd74f67-c355-4812-b03b-1af72837bbe3`**.
- **Cloud provider health: ✅** `nvidia/llama-3.3-nemotron-super-49b-v1`, 3.3s round trip.
  (Key **not** rotated — still in git history, see §1.)
- **Spark model health: unchanged** — 1 of 5 serving, exactly as §3.1 describes.

So the front half is now proven on **both** providers. The back half — validate, dialogue,
approve-spec, codegen, and a real browser compile — remains unproven on both.

---

## 0.1 Resume point

Everything is persisted; nothing needs recompiling. Projects live as JSON under
`.workflow_state/`, spec files under `./specs-local`.

**Start here:**

```bash
# 1. Re-run validate (it was killed mid-flight, so it must run again;
#    it is idempotent — it re-reads the spec files from disk).
PYTHONUTF8=1 .venv/Scripts/workflow-compiler validate 3978f39e-85de-46a7-a55c-92d859082739 \
  --spec-dir ./specs-local --provider local \
  --model NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 --timeout 600
```

Then, in order: the 8 acceptance cases (§7.4) → re-validate → `approve-spec` → run the
generated bundle against Temporal → a browser compile to clear the UI row.

The acceptance run is scripted and drives the **real browser**:

```bash
cd demo/capture2      # playwright + chromium already installed here
node dialogue-acceptance.mjs 3978f39e-85de-46a7-a55c-92d859082739 --provider-label=local
# → acceptance-local.json ; exit 0 = all 8 cases passed
```

Stack needed for that: backend on :8000 (`WORKFLOW_COMPILER_LLM_PROVIDER=local`, **not**
`local-fallback` — see §1), frontend on :3000, and for the last step
`temporal server start-dev --headless --port 7233`.

Est. remaining: ~45 min on Spark, mostly unattended.

---

## 1. One-time environment setup

### Prerequisites
Python 3.12+, Node 20.9+, and this worktree's **own** `.venv` and `node_modules` (it does
not share them with the sibling `order-workflows-iterative-2.0` worktree).

```bash
cd "<repo>/workflow-compiler"
py -3.12 -m venv .venv
.venv/Scripts/Activate.ps1          # PowerShell
pip install -e ".[dev]"
cd frontend && npm install && cd ..
```

### Provider matrix

| `WORKFLOW_COMPILER_LLM_PROVIDER` | Uses | Needs |
|---|---|---|
| `local` | Spark gateway only — **fails loudly** if unreachable | `LLM_API_BASE`, `LLM_GATEWAY_EMAIL`, `LLM_GATEWAY_PASSWORD` |
| `nemotron` | NVIDIA cloud API | `NVIDIA_API_KEY` |
| `local-fallback` | Spark first, cloud on failure | both |
| `mock` | nothing (offline) | nothing |

**Use `local` (not `local-fallback`) whenever you are verifying the eGPU.** Fallback will
silently succeed via cloud and you will "prove" something that never touched the Spark.

⚠️ **Rotate `NVIDIA_API_KEY` before trusting cloud results.** A key was previously committed
and is still in git history (see `.env.example` history). Regenerate at
[build.nvidia.com](https://build.nvidia.com) and update `.env`.

### Windows console
Set `PYTHONUTF8=1` for any redirected CLI output — progress glyphs (`→`) are non-cp1252 and
will raise `UnicodeEncodeError` otherwise.

---

## 2. Clean-start checklist (do this *every* session)

Three of the failures in the last round were environment, not code. This checklist removes
all three.

1. **Kill stale servers, and verify the port actually freed.** A previous backend was
   running *old code with no `/dialogue` routes at all* — the chat feature cannot work
   against it, and it fails in a way that looks like a product bug.

   ```powershell
   Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
     Where-Object { $_.CommandLine -like "*uvicorn*workflow_compiler*" -or
                    $_.CommandLine -like "*multiprocessing.spawn*" } |
     ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
   Get-NetTCPConnection -State Listen -LocalPort 8000,3000 -ErrorAction SilentlyContinue
   ```

   `uvicorn --reload` spawns workers via `multiprocessing.spawn`; killing only the parent
   leaves an orphan holding port 8000. Match on both patterns.

2. **Confirm which worktree is serving each port.** `:3000` was serving the *other*
   worktree. Check `CommandLine` contains `order-workflows-dialogue`.

3. **Confirm the running backend has the dialogue routes** — this is the single fastest way
   to detect stale code:

   ```bash
   curl -s http://localhost:8000/openapi.json | python -c \
     "import sys,json;print([p for p in json.load(sys.stdin)['paths'] if 'dialogue' in p])"
   ```
   Must print three paths. Empty list ⇒ you are running old code; go back to step 1.

4. **Never touch the gateway while a compile is running** (see §3.2).

### Starting the stack

```bash
# Terminal 1 — backend. Note the timeout override; the API has no --timeout flag.
PYTHONUTF8=1 WORKFLOW_COMPILER_LLM_TIMEOUT=900 \
  .venv/Scripts/python -m uvicorn workflow_compiler.api.app:app --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Register an account at <http://localhost:3000> on first use (accounts are local, stored in
`.workflow_state/users/`).

---

## 3. Blockers to clear before anything else

### 3.1 Four of the five Spark models are dead — fix this first

`/auth/config` advertises five models; the UI dropdown lists whatever it advertises, with no
health check. Only one actually serves:

| Model | Status |
|---|---|
| `NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` | ✅ serving |
| `gpt-oss-120b` / `gpt-oss-20b` / `gpt-oss-8b` | ❌ HTTP 502 "Inference server unreachable" |
| `qwen3.5-9b` | ❌ HTTP 502 |

**This is the highest-value fix available.** A healthy larger model likely resolves both the
16-minute compile *and* the accuracy ceiling in §5, and it is Spark-side ops work, not code.
Re-probe after restarting those backends:

```bash
.venv/Scripts/python -c "
import asyncio
from workflow_compiler.config import get_settings
from workflow_compiler.llm.factory import build_local_provider
from workflow_compiler.llm.types import ChatMessage
async def main():
    s = get_settings()
    for m in ['gpt-oss-120b','gpt-oss-20b','gpt-oss-8b','qwen3.5-9b',
              'NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4']:
        p = build_local_provider(s, model_override=m, timeout=90)
        try:
            r = await p.chat([ChatMessage.user('Reply with exactly: OK')], max_tokens=512)
            print(f'{m:42s} OK   {r.text[:40]!r}')
        except Exception as e:
            print(f'{m:42s} FAIL {type(e).__name__}: {str(e)[:90]}')
asyncio.run(main())"
```

### 3.2 The gateway is a single GPU with no queueing

Any concurrent request inflates per-request latency past `llm_timeout` and **kills an
in-flight compile**. One of the "compile is broken" failures last round was caused by
running probe scripts against the gateway during a compile. Serialize all gateway access.

---

## 4. Running the ENTIRE pipeline

Run the same sequence twice — once with `--provider local`, once with `--provider nemotron`
— and record stage timings and outputs for both. Reference document: `examples/multi_workflow.md`
(2 workflows, deliberate gaps, ~4KB) — small enough to iterate on, rich enough to produce
findings for the dialogue.

### 4.1 CLI path (do this first — best logs, fastest feedback)

```bash
SPECS=./specs-local        # or ./specs-cloud

# 1. compile  — NOTE: --timeout default is 120s, far too low for the eGPU
PYTHONUTF8=1 .venv/Scripts/workflow-compiler compile examples/multi_workflow.md \
  --provider local --model NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
  --timeout 300 --spec-dir $SPECS

# 2. validate — folds spec edits back in, recomputes findings. Required before approve.
PYTHONUTF8=1 .venv/Scripts/workflow-compiler validate <project-id> --spec-dir $SPECS

# 3. approve-spec — graph → CVPA → Temporal design → codegen (LLM stages inside)
PYTHONUTF8=1 .venv/Scripts/workflow-compiler approve-spec <project-id> --spec-dir $SPECS
```

For cloud, swap: `--provider nemotron --model nvidia/llama-3.3-nemotron-super-49b-v1`.

**Verify at each stage — do not just check the exit code:**

| After | Check |
|---|---|
| compile | 2 spec files exist; each has non-empty Activities/Events/Exceptions; the `customer_record_id` cross-workflow dependency is reported |
| validate | findings are produced (blocking/warning) — the dialogue needs these as input |
| approve-spec | `generated/<project-id>/<slug>/` contains `workflow.py`, `activities.py`, `worker.py`, `starter.py` |

**Then actually run the generated bundle** — this is the only real proof codegen worked:

```bash
pip install temporalio
temporal server start-dev                 # terminal 1
cd generated/<project-id>/<slug>
python worker.py                          # terminal 2
python starter.py                         # terminal 3
```

Pay particular attention to whether **compensations** (`rollback provisioning`,
`deconfigure account`) survive into the generated saga — that is the field most at risk
(§5).

### 4.2 UI path (this is the one that has never succeeded)

<http://localhost:3000> → upload `examples/multi_workflow.md` → **Provider: "Spark (local
only)"**, **Model: the one model that works** → Compile. Expect ~16 min on the current
model; the overlay will sit on "Drafting editable specs" for ~7 min per workflow with no
further detail (see §6.3 — that silence is a real usability defect, not a hang).

Then: Spec tab → **Validate** → Resolve tab (§7) → **Validate again** → **Approve** →
Results tab → download bundle.

### 4.3 Expected timings — local, current model, reasoning on

| Stage | Time |
|---|---|
| segmentation (`discover` 75s + 3 review passes ~38s) | 113s |
| `extract:onboarding` | 412s |
| `extract:provisioning` | 420s |
| **total compile** | **945s (15m45s)** |

Anything materially slower means contention (§3.2) or an empty-completion retry (§6.1).

---

## 5. The reasoning trap — read before "optimizing" latency

~95% of generated tokens on the Spark are discarded chain-of-thought (7.5k–12.3k chars of
`reasoning_content` vs 33–327 chars of real answer). It is tempting to disable it.
**It has been tried and measured, and it must not be enabled:**

Sending `{"chat_template_kwargs": {"enable_thinking": false}}` makes a full compile
**71s instead of 945s (13.3x)** — but that path is *off-spec* on this gateway:

- The answer comes back in `reasoning_content` with `content` empty (`''`). This is the
  origin of the `No JSON object or array found in response: ''` schema failures.
- Extraction quality degrades materially:

  ```
  Activities (provisioning)
    ON : reserve, configure, activate, rollback provisioning, deconfigure account
    OFF: reserve, configure, activate            ← compensations LOST

  State Transitions (provisioning)
    ON : reserving→configuring→activating→completed / activating→failed
    OFF: active → upgrade_in_progress            ← HALLUCINATED, absent from input
  ```

Losing compensations silently corrupts the generated Temporal saga rollback.

Toggles that do **not** work here: system preambles `"detailed thinking off"` and
`"/no_think"` are ignored; `reasoning_effort` accepts only `low|medium|high` (no `none`),
and `low` changes nothing. Contrast `NemotronProvider`, which disables reasoning via a
system preamble — that works on the *cloud* 49B model, not on this gateway.

The mechanism is preserved but **disabled** in `GatewaySessionProvider.EXTRA_BODY`, with
this rationale in a comment. Legitimate ways to attack latency instead:
a healthy larger model (§3.1), tuning `WORKFLOW_COMPILER_REVIEW_STAGES` (the review
pipeline triples LLM calls per stage), or the cloud provider.

---

## 6. Fix list

> **Status 2026-08-11: items 1, 2, 3, 7 and 8 are now IMPLEMENTED** (in the working tree,
> uncommitted, with tests — see §8 and `docs/PIPELINE_RUN_LOG.md` §3). Items 4, 5 and 6
> (performance) are untouched. Two of the diagnoses below were wrong in their mechanism even
> though the symptoms were real — corrections in `PIPELINE_RUN_LOG.md` §1.

### 6.1 Correctness / reliability
1. **Intermittent empty completions** with reasoning on (`attempt 1/2 … response: ''`).
   `structured()` retries and usually recovers, but each retry costs a full slow call and
   there is no explicit "model returned nothing" handling. `llm/base.py:structured`.
2. **Provider errors surface as HTTP 500** from `POST /projects/compile-upload`. A dead
   upstream model should be 502/4xx. `api/app.py`.
3. **⚠️ SUSPECTED — confirm before acting.** In `frontend/app/projects/[id]/page.tsx`,
   `buffers` and `dirty` re-seed only when `project_id` changes (`useEffect`, ~line 230).
   A dialogue answer changes the spec **server-side**, so on the current reading:
   the Spec tab would show stale markdown, Approve would stay enabled without a
   re-validate, and Approve posts `spec_markdown: buffers` — meaning **stale buffers could
   overwrite the dialogue's changes**. This was found by reading code, *not* by running it.
   Reproduce first (§7.4 step 6); if confirmed it is the highest-severity bug in the tree.

### 6.2 Performance
4. 16 min per 4KB document — see §5 for what is and isn't a legitimate fix.
5. Review pipeline triples LLM calls per stage; `WORKFLOW_COMPILER_REVIEW_STAGES` already
   exists to scope it.
6. Per-workflow extraction is sequential (`project_compiler.py`, ~line 217) — little gain
   on one GPU, relevant on cloud.

### 6.3 Observability / UX
7. **The longest stage reports no progress.** `extract_facts` is called *without* a
   sub-reporter (`project_compiler.py:223`), unlike segmentation which wires
   `set_progress(self._sub_reporter(progress))` at line 197. Result: ~7 min of silence per
   workflow, indistinguishable from a hang. Wire the same sub-reporter through.
8. **Dead models are offered in the dropdown** (§3.1) — health-check or mark unavailable.

---

## 7. Completing the natural-language spec editing tool

### 7.1 What exists
Committed as `17b251b` (22 files, +2431 lines): `dialogue/engine.py`,
`agents/dialogue.py`, `models/dialogue.py`, `frontend/components/DialoguePanel.tsx`, and
four endpoints:

```
GET    /projects/{id}/dialogue          the open session, if any
POST   /projects/{id}/dialogue          open one (400 if nothing to ask)
POST   /projects/{id}/dialogue/answer   answer in prose
POST   /projects/{id}/dialogue/skip     pass, spec untouched
DELETE /projects/{id}/dialogue          close; applied answers stay applied
```

**It has never been executed.** Unit tests pass (462 green) but no live run, no browser
session, no LLM provider has ever seen a dialogue prompt.

### 7.2 Locked design decisions — do not re-litigate
1. Surface: frontend chat panel + FastAPI endpoints (not CLI).
2. Question source: BLOCKING **and** WARNING findings + unresolved `open_questions`.
   Excludes INFO and `llm_inferred`.
3. Apply path: direct spec patching — **not** routed through the edit-request pipeline.
4. Delivery: full implementation + tests (pytest, ruff, mypy --strict).
5. Base: master work committed first, then the worktree branch.
6. Question style: the LLM MAY group related findings and ask clarifying follow-ups.
7. Apply timing: after **each** answer (version bump per answer), not batched.
8. Unmappable answers: **one** clarifying follow-up, then park as a new open question.
   Never abort the session.

### 7.3 Prerequisite
The agenda is built from `project.validation_findings` + unresolved open questions, so
**`validate` must have run** or `POST /dialogue` returns 400 ("Nothing to resolve"). The
agenda is a snapshot taken at `start`; it does not grow mid-session, so a session always
terminates. Re-validate afterwards to get the next round.

### 7.4 Acceptance run — verify each locked behavior explicitly

With a compiled + validated project open on the **Resolve** tab, click *Start resolving*,
then drive these cases deliberately. Do it on **local first, then cloud** — question
drafting and answer interpretation are LLM calls and may differ by provider.

1. **Applies immediately** — answer a concrete question ("it goes to the shipping workflow,
   that one kicks off once payment clears"). Expect an *"Applied to the spec"* panel listing
   changes **and a patch-version bump**. Confirm decision 7.
2. **Grouping** — confirm related findings arrive as one question, not mechanically
   one-per-finding. Confirm decision 6.
3. **Exactly one follow-up** — answer vaguely ("depends"). Expect a `follow-up` pill and
   one clarifying question. Answer vaguely again — it must **park, not interrogate again**.
   Confirm decisions 6 + 8.
4. **Parking** — answer something unmappable ("ops owns that, not decided yet"). Expect
   *"Recorded as an open question"*; verify it lands in the spec's Open Questions as
   `HUMAN_PROVIDED`, unresolved, `ref="dialogue:<question_id>"`.
5. **Skip** — verify the spec is genuinely untouched.
6. **⚠️ The staleness check (§6.1 item 3)** — after ≥1 applied answer, switch to the Spec
   tab **without reloading**. Does it show the updated markdown or the pre-dialogue text?
   Is Approve still enabled? If it shows stale text, **do not click Approve** on a project
   you care about — that is the suspected clobber path. Capture the result either way.
7. **Session end** — "All done" summary counts answered/parked/skipped correctly.
8. **Re-validate → Approve** — specs changed, so validation must re-run; then approve
   through to generated code and confirm the dialogue's changes survive into the bundle.

### 7.5 Definition of done
- [ ] All 8 cases in §7.4 pass on **provider `local`**
- [ ] All 8 cases pass on **provider `nemotron`**
- [ ] §6.1 item 3 confirmed or refuted, and fixed if confirmed
- [ ] A dialogue-modified spec survives `validate` → `approve-spec` → generated bundle
- [ ] Generated bundle runs against a Temporal dev server (§4.1)
- [ ] `pytest`, `ruff check src tests`, `mypy src` all green
- [ ] Full pipeline table in §0 has no ❌ or ❔ left

---

## 8. Uncommitted changes currently in the working tree

**Updated 2026-08-11.** `471 passed` (was 462; +9 new tests), `ruff check src tests` clean,
frontend `tsc --noEmit` and `next build` clean.

⚠️ **Correction:** the mypy baseline is **35 errors, not 6.** Verified by checking `HEAD` out
into a separate worktree and diffing — the working tree reports the same 35, and the sets are
identical, so nothing added here introduces a new error. But `mypy src` does **not** pass,
contrary to `CLAUDE.md`. Decide whether that gate is real.

### Fixes added this session (all with tests)

- `llm/base.py` — empty completions handled distinctly from malformed JSON (§6.1.1).
- `api/app.py::_guard` — provider failures → **502**, timeouts → **504**, not 500 (§6.1.2).
- `components/DialoguePanel.tsx` + `app/projects/[id]/page.tsx` — the dialogue clobber
  (§6.1.3) is **confirmed and fixed**; see `PIPELINE_RUN_LOG.md` §1.2 for why the fix is
  simpler than this document assumed.
- `project_compiler.py::_nested_progress` — fact extraction reports nested progress (§6.3.7).
- `api/{app,schemas,dependencies}.py` + `app/page.tsx`, `lib/{api,types}.ts` — opt-in serial
  model health probe; dead models disabled in the picker (§6.3.8). Live-verified.
- `demo/capture2/dialogue-acceptance.mjs` — **new**, scripted 8-case §7.4 acceptance run
  driving the real browser. Written but **not yet executed**.

### Pre-existing (from the prior session)

Review and commit or discard:

- `llm/base.py` — `_timeout_message()`. Timeout errors previously rendered as the bare
  `local request timed out:` with nothing after the colon, because httpx timeout exceptions
  stringify to `''`. Now names the limit, the model, and how to raise it.
- `llm/providers/openai_compatible.py` — added `EXTRA_BODY` class hook (merged into every
  chat payload via `setdefault`) and a `_resolve_content()` seam.
- `llm/providers/gateway.py` — `EXTRA_BODY = {}` (reasoning-off deliberately **disabled**,
  with the §5 rationale in a comment) and a `_resolve_content()` override that promotes
  `reasoning_content` **only** when thinking was explicitly disabled. Scoped that way on
  purpose: with thinking on, the reasoning channel holds chain-of-thought prose, and
  promoting it feeds commentary to the structured parser instead of letting it retry.

---

## 9. Reference

- **`docs/PIPELINE_RUN_LOG.md`** — measured Spark results, corrections to this document,
  and the cloud runbook. **Read before acting on anything above.**
- `docs/HOW_IT_WORKS.md` — §9.2 CLI reference, §9.3 HTTP API reference
- `docs/architecture.md` — component + sequence diagrams
- `docs/EDIT_FORMAT_GUIDE.md` — edit-request document format (the *other* edit path)
- `docs/FRONTEND_HANDOFF.md`, `docs/EDIT_REQUESTS_HANDOFF.md` — prior handoffs

# Suggested answers + pre-drafted questions — build plan

**Started:** 2026-08-12 · **Branch:** `feat/spec-dialogue` · Builds on `docs/PIPELINE_HANDOFF.md` §7.

Two features, agreed with the user before any code was written:

- **A — Suggested options.** Each dialogue question carries 2–4 concrete candidate
  answers the drafting agent brainstormed from the spec, alongside the free-text box
  that already exists. Pick one, edit one, or ignore them entirely.
- **B — Pre-drafted agenda.** Question drafting runs in the background the moment
  `validate` succeeds, so opening the Resolve tab is instant. While it runs the UI
  says so. Nothing half-drafted is ever persisted, so an interrupted draft simply
  restarts next time.

## Locked decisions (do not re-litigate)

1. **Trigger: after `validate` succeeds**, not after compile. The agenda is built from
   `project.validation_findings`, which only exists post-validate. Plus a lazy re-kick
   when the Resolve tab opens with nothing fresh prepared — that one rule covers
   first-open, server-restart recovery, and "the spec changed since we drafted".
2. **Picking an option sends its text as a normal prose answer** through the same
   `interpret_answer` path as typed prose. No pre-computed patches, no second apply
   path. One LLM call per answer, exactly as today.
3. **Pre-drafting is cloud-on / local-off by default**, `WORKFLOW_COMPILER_PREDRAFT_QUESTIONS`
   = `off` | `cloud` (default) | `always`. Rationale: `PIPELINE_HANDOFF` §3.2 — the Spark
   gateway is a single GPU with no queueing and a concurrent request has already killed
   an in-flight compile once.
4. **Options must be grounded** in the spec/document (existing actors, states, workflows),
   not invented, and the session records *which option was picked*. The product's claim is
   that the human gate is the oracle; three plausible buttons make it easy to click through
   and end up with an LLM-authored spec stamped `HUMAN_PROVIDED`. The audit trail has to
   stay honest about that.
5. **Clicking an option fills the textarea and focuses it** — it does not send. Prevents a
   misclick from applying a spec change, and lets the user edit the suggestion. `option` is
   sent to the server only while the draft still matches the label verbatim.
6. **Pre-drafting must never block real work.** It is exempt from `JobManager`'s
   one-active-run-per-project rule and is auto-cancelled when any user-initiated job starts
   on that project.
7. **Verification: full** — unit tests, extended browser acceptance suite, and a fresh
   end-to-end cloud compile so the pre-draft chain fires from its real trigger. Cloud only;
   the Spark eGPU is unavailable.

## Phases

### Phase 1 — models + fingerprint (backend, no LLM)
- `models/dialogue.py`: `SuggestedOption{label, detail}`; `DraftedQuestion.options`;
  `DialogueQuestion.options` / `.followup_options` / `.chosen_option`;
  `AnswerPlan.followup_options`; `PreparedAgenda{fingerprint, questions, drafted_at}`.
- `DialogueQuestion.prompt_options` property — mirrors the existing `prompt` property:
  the options actually awaiting an answer (follow-up's if one is open, else the question's).
  The client must never have to work out which it is showing.
- `models/project.py`: `CompilationProject.prepared_dialogue: PreparedAgenda | None = None`
  (default-valued so legacy project JSON keeps loading).
- `dialogue/agenda.py`: `agenda_fingerprint(project) -> str`, pure sha256 over
  (slug, spec version, askable finding strings, unresolved open-question texts).
- Tests: fingerprint stability/sensitivity, model defaults, legacy JSON load.

### Phase 2 — prompts + agent + engine
- `prompts/templates/draft_dialogue_questions.md`: options rules (2–4, grounded in the
  spec, mutually exclusive, business language, omit rather than pad) + worked example.
- `prompts/templates/interpret_dialogue_answer.md`: `followup_options` on the follow-up
  disposition + example.
- `agents/dialogue.py`: no signature change — both schemas widen.
- `dialogue/engine.py`: factor the per-spec drafting loop out of `start()` into
  `_draft_agenda(project)`; add `prepare(project) -> PreparedAgenda | None`; `start()`
  consumes a fresh `prepared_dialogue` (fingerprint match) and drafts live otherwise,
  clearing it either way. `answer(..., chosen_option=None)` records the pick.
  `_dispose` stores `plan.followup_options` on the question when a follow-up is asked.
- Tests: prepared agenda consumed / stale agenda ignored / options round-trip through
  session state / `chosen_option` recorded / follow-up options surface via `prompt_options`.

### Phase 3 — compiler + jobs + API
- `config.py`: `predraft_questions: Literal["off","cloud","always"] = "cloud"`.
- `project_compiler.py`: `prepare_dialogue(project_id)`. **Reload the project from the
  store after drafting and re-check the fingerprint before saving** — drafting is minutes
  long and the spec can change underneath it via chat or an edit; write the agenda onto the
  fresh project or discard it. Never save the stale in-memory copy.
- `api/jobs.py`: `JobKind` gains `"predraft"`; exempt from the per-project conflict check;
  starting any other kind cancels an active predraft for that project first.
- `api/app.py`: `POST /projects/{id}/dialogue/prepare` (202, idempotent — no-op when a
  fresh agenda exists or one is already in flight); `DialogueResponse` gains
  `prepared` / `preparing` / `options`; the validate job fire-and-forgets a predraft job on
  success (never fails the validate job if predraft errors).
- Tests: API contract, idempotence, job exemption + auto-cancel, provider gating.

### Phase 4 — frontend
- `lib/types.ts` + `lib/api.ts`: new fields, `prepareDialogue(id)`.
- `DialoguePanel.tsx`: option chips above the textarea (click → fill + focus, clears
  `pickedOption` if the user then edits); no-session branch shows "Preparing questions…"
  while `preparing`, polls every 3s, and auto-fires `prepare` once on mount when nothing is
  prepared and nothing is running.
- `tsc --noEmit` + `next build`.

### Phase 5 — verification (cloud only; Spark unavailable)
1. `pytest`, `ruff check src tests`, `mypy src` (baseline is **35 errors** — must stay
   exactly 35, unchanged; see PIPELINE_HANDOFF §8).
2. Extend `demo/capture2/dialogue-acceptance.mjs`: options render on a question; picking one
   fills the box and applies on send with `chosen_option` recorded; the preparing→prepared
   transition is observed. Keep the existing 7 cases green.
3. Fresh cloud compile via `ui-compile-acceptance.mjs`, then validate through the API, then
   confirm the predraft chain fired **without being asked**, then run the dialogue suite
   against that project.

⚠️ `PIPELINE_HANDOFF` §0.0 is emphatic: *every* harness bug in that session produced a
confident wrong answer rather than an error. A new acceptance case must be seen to go red
for the right reason before its green is worth anything.

## Progress log

- [x] **Phase 1** — `SuggestedOption`, `PreparedAgenda`, `DialogueQuestion.options` /
      `.followup_options` / `.chosen_option` / `.prompt_options`,
      `CompilationProject.prepared_dialogue`, new `dialogue/agenda.py`
      (`askable_findings` moved out of the engine so the fingerprint and the agenda
      cannot disagree about what is askable).
- [x] **Phase 2** — both prompts carry options; `DialogueEngine._draft_agenda` factored
      out; `prepare()` added; `start()` consumes a fresh prepared agenda; `answer()` takes
      and validates `chosen_option`.
- [x] **Phase 3** — `predraft_questions` setting; `ProjectCompiler.prepare_dialogue` with
      the reload-and-recheck guard; `JobManager` speculative kind + `after` hook;
      `POST /projects/{id}/dialogue/prepare`; validate chains a pre-draft on success.
      **544 passed** (was 505), ruff clean, mypy 35 = baseline.
- [x] **Phase 4** — `SuggestedOption` type, `prepareDialogue`, `answerDialogue(id, text, option)`;
      `DialoguePanel` renders option chips (`data-testid="dialogue-options"`), fills-not-sends,
      drops the pick when the text is edited, shows "Preparing questions…", polls every 3s
      while preparing, and asks for a draft once per project when nothing is waiting.
      `tsc --noEmit` and `next build` both clean. (`--accent-soft` is the picked-state token;
      there is no `--surface-raised` in `globals.css`.)
- [x] **Phase 5** — verified on cloud, project **`8896fe13-0890-474f-b1f2-b0ebf0bb9856`**.
      `pytest` **544 passed** (was 505), `ruff check src tests` clean, `mypy src` **35 errors
      = the documented baseline, unchanged**. Browser: `ui-compile-acceptance` **7/7 (366s)`,
      `dialogue-acceptance` **10/10** (the 7 existing cases plus 8, 9, 10).

### Measured

| | |
|---|---|
| `dialogue:start` **before** (project `3ebba227`, drafted live) | **364s** |
| `dialogue:prepare` in the background | **433s** |
| "Start resolving" **after** a pre-draft | **0.1s** |
| Questions drafted | 8, from 32 findings + 4 open questions |
| Questions carrying suggested answers | **8 of 8** |

Case 9 `prepared=true preparing_ui=false start=0.1s`; case 8
`questions_with_options=8/8 on_screen=2 fills_without_sending=true`; case 10 recorded the
picked label verbatim. Options came back grounded rather than invented — one read
*"Retry up to 5 times (like Notify Customer) before marking 'failed'"*, which is a
cross-reference to a retry policy already in the spec.

### What was seen to fail, and what was not

Per PIPELINE_HANDOFF §0.0 — a green harness is worth nothing until it has gone red for the
right reason.

- **Seen red, correctly:** `test_prepare_drafts_the_agenda_so_start_is_instant` failed
  (`assert False is True`) because this worktree's `.env` provider is `local-fallback` and
  the default `cloud` setting suppressed pre-drafting — a real gate doing its job, fixed by
  making the test's setting explicit.
- **Seen red, correctly, live:** the first pre-draft *failed* on an upstream cloud error
  (below), and case 9's `prepared` flag read `false` throughout — so that assertion
  demonstrably distinguishes the two states rather than always reporting true.
- **Not seen red:** cases 8 and 10 have only ever run against an agenda that did carry
  options. They are written to fail rather than skip when they cannot run (`fillCheck`
  starts `null`, and case 10 records an explicit failure when no question offered options),
  but that path has not been exercised. The unit tests cover both negatives directly
  (`test_blank_options_are_dropped`, `test_an_unoffered_option_label_is_not_recorded`).

## Captured

`demo/capture2/shoot-guided.mjs <project-id>` captures the Guided tab against an
already-prepared agenda (it asserts nothing; it exists so the options can be *seen*).
Output in `demo/capture2/shots/`:

- `guided-ready.png` — the pre-draft state before a session is opened.
- `guided-options.png` — a WARN question with three grounded options above the free-text
  box: *"It's set after 3 failed identity verification retries."* / *"...if the application
  is incomplete after re-submission."* / *"...manually by Customer Service after assessing
  the case."* Every one references something already in the spec.
- `guided-picked.png` — after clicking the first: the option is highlighted, its text sits
  in the answer box, **Answer has become enabled, and nothing was sent.**

## Phase 6 — suggested replies in the free-form chat (added after review)

The guided dialogue and the free-form chat are the two doors to the same gate, and the
chat asks exactly one clarifying question per instruction — the same vague-answer moment
where concrete choices help most. So the chat's clarifying questions now carry options too.

- `InstructionPlan.clarifying_options`, `SpecChatSession.pending_options` (cleared by
  `clear_pending`, so a spent question's suggestions can never be re-offered),
  `SpecChatTurn.options` / `.chosen_option`.
- `interpret_spec_instruction.md` grew the same grounding rules and a worked example.
- `SpecChatEngine.send(..., chosen_option=)` validates the label against what was actually
  offered, exactly as the dialogue does.
- **`frontend/components/SuggestedAnswers.tsx` is now shared by both panels.** The
  duplicate in `DialoguePanel` was removed. Same reason `dialogue/spec_ops.py` is shared:
  the two doors must not be able to drift on how a suggestion behaves.

Gates after this phase: **547 passed**, ruff clean, mypy 35 = baseline, `tsc` + `next build`
clean.

## Phase 7 — cross-workflow dependencies enter the agenda (added after review)

**The bug.** `approve_spec` raises `ApprovalError` outright on an unconfirmed
cross-reference (`project_compiler.py:1480`) — no approval, no graph, no codegen, no
Temporal bundle. But `_validate_triggers_and_dependencies` flagged only two conditions on a
dependency (missing target = BLOCKING, type mismatch = WARNING) and **never that it was
unconfirmed** — even though the trigger loop ten lines above does exactly that check. So:

| | Emits a finding? | Hard-blocks approve? |
|---|---|---|
| Unconfirmed **trigger** | yes, WARNING | no |
| Unconfirmed **cross-reference** | **no** | **yes** |

The thing that actually stops you was the silent one. And because the dialogue agenda is
built from findings, the question was never drafted: you could answer everything in the
Resolve tab and still be refused at Approve. It also falsified `_gate_findings`'s own
docstring — "a spec that validates clean is a spec that will compile".

**The fix, in two halves.**

1. `_validate_triggers_and_dependencies` now emits a **WARNING** per unconfirmed
   dependency, attributed to `source_workflow` so it is asked **once**, not once per side.
   WARNING rather than BLOCKING deliberately: it reaches the agenda either way (the
   dialogue asks about blocking *and* warning), and BLOCKING would turn every freshly
   compiled project red, since every compile produces unconfirmed references by design.
2. `AnswerPlan` gained `xref_ops`, so an answer can act on it. A dependency belongs to the
   *project*, not to a spec, so it cannot be a `Patch` — this is the edit path's existing
   typed `XrefOp`. The applier moved to **`spec/wiring.py`** and is now shared by both
   paths (`ProjectCompiler._apply_xref_op` delegates), for the same reason `spec_ops.py` is
   shared: the code that clears a hard approval blocker must not exist twice.

Three dispositions, all reusing the proven applier: **confirm** = `modify` with the
unchanged four-tuple (ADD/MODIFY both set `user_confirmed=True`, so a human naming a
dependency *is* the confirmation); **correct** = `modify` with fixed fields; **deny** =
`remove`.

Load-bearing details:

- A dependency operation that cannot be carried out is **reported and skipped, never
  raised**. A raise would 500 the answer endpoint and lose the user's answer, violating
  decision 8 (never fatal). If every operation is dropped the answer **parks** rather than
  reporting an application that changed nothing.
- An xref-only answer still **bumps the spec's patch version**. Dependencies render into
  the spec Markdown, and the agenda fingerprint covers spec versions — without the bump a
  prepared agenda would look fresh against a spec that had changed underneath it.

Verified against the live project's stored state (a pure function, no LLM):

```
WARNING | customer-onboarding | the dependency 'customer_record_id' ->
          'account-provisioning.customer_record_id' was detected automatically
          and has not been confirmed
```

**Verified live on cloud**, project `8896fe13`, whole chain, first attempt. The driver
script never asks for drafting and never names a dependency operation — the validate hook
starts the pre-draft, the drafting agent decides to ask, and the interpreter decides how to
act on prose:

```
validate succeeded after 195s
unconfirmed-dependency findings: 1
  [warning] customer-onboarding | the dependency 'customer_record_id' ->
            'account-provisioning.customer_record_id' ... has not been confirmed
agenda prepared after 267s          (9 questions, up from 8 — the new one)
dependency question: "Confirm the dependency: Does 'customer_record_id' truly
                      need to be provided to 'account-provisioning'?"
  option: Yes, it's essential for account setup.
  option: No, account-provisioning can generate its own ID.
answer (prose, no operation named): "Yes, that's right — account provisioning
  cannot start until onboarding has created the customer record..."
  changes: ["confirmed dependency customer-onboarding.customer_record_id →
             account-provisioning.customer_record_id", "version bumped to 0.1.2"]
  warnings: []
user_confirmed: false → TRUE
```

Worth noting the drafting agent offered both dispositions unprompted — the second option
("account-provisioning can generate its own ID") maps to a `remove`, not a confirm. The
suggested answers and the dependency work compose without either knowing about the other.

`approve_spec`'s guard is `[r for r in project.cross_references if not r.user_confirmed]`,
which is now empty for this project, so the blocker is cleared. Approve itself was **not**
re-run — that executes the whole back half (graph → CVPA → Temporal design → codegen) and
was outside this check.

Gates: **554 passed**, ruff clean, mypy 35 = baseline, `tsc` clean.

## Pre-existing flake found (not caused by this work)

`tests/test_edit_specs.py::test_confirm_with_stale_fingerprint_raises` fails roughly **1 run
in 4**, and it fails **standalone**, with only that one test running — so it is not test
pollution. `git diff` confirms this work touches neither `_fingerprint` nor `preview_edit`.

The cause looks like clock granularity. `ProjectCompiler._fingerprint` binds a preview to
`project.updated_at.isoformat()`, and Windows' `datetime.now()` is coarse (~15ms). When the
preview's own touch and a subsequent change land in the same tick, `updated_at` does not
move, the fingerprint matches, and the stale preview is accepted.

**That is a product bug, not just a flaky test:** an edit confirmed against a project that
changed within the same clock tick will apply against state it never previewed — precisely
what the fingerprint exists to prevent. A content hash (or a monotonic revision counter)
instead of a timestamp would close it. Left alone here because it is outside this task.

### New cloud failure mode

`nemotron transport error: Server disconnected without sending a response.` — the pre-draft
job failed on it after 12.7 minutes; a retry of the identical request succeeded in 433s.
Not previously recorded in PIPELINE_HANDOFF (which lists HTTP 504 and a 500 "Already
borrowed"). Worth noting that the containment worked exactly as designed: the validate job
still reported **succeeded**, nothing was persisted, no stale agenda was left behind, and
the next `prepare` call simply started over.

### Notes worth keeping

- The validate → pre-draft chain could not be written inline inside the validate job:
  the job is still `active` when its own coroutine returns, so a speculative start would
  always be refused by it. Hence `JobManager.start(..., after=...)`, which runs the
  follow-on only once the job has recorded a terminal status. `job.task` is now cleared
  *after* the hook, because the event loop keeps only a weak reference to a task and
  dropping it mid-hook would let the follow-on be collected.
- This worktree's `.env` sets `local-fallback`, which the default `cloud` setting
  deliberately excludes. Tests that exercise pre-drafting **must** set
  `predraft_questions` explicitly or they pass vacuously — one of them did, and was fixed.
- **`uvicorn ... > log 2>&1` block-buffers.** A compile in flight looked like "no request
  ever reached the backend" purely because the log file was minutes stale, and a healthy
  run was killed on that reading. Start the backend with `PYTHONUNBUFFERED=1` before using
  its log as evidence of anything. Confirmed the click path is fine by listening for the
  request in Playwright (`page.on("request", …)`) instead of trusting the log.
- Measured on project `3ebba227` (drafted before this work): **`dialogue:start` = 364s.**
  That is the wait the pre-draft removes, on cloud.

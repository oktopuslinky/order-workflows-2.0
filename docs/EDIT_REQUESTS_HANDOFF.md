# Handoff: Workflow Edit Requests (feature branch state, 2026-07-16)

Status snapshot for the **edit-request feature** (`docs/EDIT_FORMAT_GUIDE.md`) plus the
**provider-default change** (Nemotron cloud is now the default; the eGPU gateway is opt-in).
This file lists exactly what is verified, what still needs to be tested, and what to build next.

## What was implemented

- **Models** — `models/edit.py` (`EditPlan`, `TriggerOp`, `XrefOp`, `EditRecord`,
  `WiringAction`); `CompilationProject.edit_log` (append-only audit trail).
- **Parser** — `spec/edit_ingest.py`: deterministic skeleton parse, fail-fast before any LLM
  call; split/merge syntax reserved and rejected.
- **Applier** — `require_grounding` flag on `MetadataPatchApplier`/`FactsPatchApplier`
  (`agents/review_pipeline.py`), `human_authority` mode on `SpecPatchApplier`
  (`spec/validator.py`), `EditPatchApplier` (`spec/edit_applier.py`) with `HUMAN_PROVIDED`
  provenance bookkeeping. Review-pass behavior is unchanged (regression-tested).
- **Agent** — `agents/edit_interpreter.py` + `prompts/templates/interpret_edit_request.md`;
  MockProvider ships a canned `EditPlan` so `--provider mock` runs the whole path offline.
- **Orchestration** — `ProjectCompiler.edit_specs`: atomic (deep copy, all-or-nothing),
  add/remove whole workflows, trigger/xref wiring ops, version patch-bump, `EditRecord`,
  stage reset to `SPEC_DRAFTED` (validate → approve-spec must re-run).
- **Surfaces** — CLI `workflow-compiler edit`; `POST /projects/{id}/edit`;
  frontend `EditRequestPanel` (paste/upload, diff via the existing ValidateDiff, edit history).
- **Out-dir fix** — `approve-spec`/`approve` `--out-dir` now defaults to `./generated`, nesting
  `<project-id>/<slug>/` (approve-spec) or `<workflow-id>/` (approve). No more root litter.
- **Provider default** — `WORKFLOW_COMPILER_LLM_PROVIDER` defaults to `nemotron` (cloud);
  `local` (eGPU gateway) and `local-fallback` (eGPU primary + Nemotron fallback) are opt-in
  (`config.py`, `.env`, `.env.example`, README, architecture/HOW_IT_WORKS synced). The frontend
  picker already defaulted to "Nemotron (cloud)" with eGPU models selectable.
- **Docs** — `docs/EDIT_FORMAT_GUIDE.md`, `examples/order_edit_request.md`, README /
  architecture.md / HOW_IT_WORKS.md / CLAUDE.md synced.

## Verification state

### Done — Tier 1 (offline, all green)

- Full `pytest` suite passes (new: `test_edit_models.py`, `test_edit_applier.py`,
  `test_edit_ingest.py`, `test_edit_specs.py` incl. the mock compile → edit → validate →
  approve re-gate; API tests for `/edit`).
- `ruff check src tests` clean; `mypy src` has **no new errors** vs. the pre-existing baseline
  (35 errors, all pre-dating this feature; none in the new modules).
- CLI smoke with `--provider mock`: compile → edit → summary + version bump works.

### Done — Tier 2 scenario 1 (real cloud Nemotron)

- `workflow-compiler compile examples/order_workflow.md --spec-dir ./specs-edit-e2e --provider nemotron --timeout 180`
  succeeded: **project `3f6be187-d4d7-4f0d-9f90-3eb84a43d70f`**, slug
  `order-fulfillment-workflow` (matches `examples/order_edit_request.md`), stage `spec_drafted`.

### TODO — Tier 2 scenarios 2–6 (real cloud Nemotron; `--provider nemotron` is now the default so the flag is optional)

Run from the repo root. Project id above is live in `.workflow_state/projects/`.

2. **Content + metadata edit**
   ```bash
   workflow-compiler edit 3f6be187-d4d7-4f0d-9f90-3eb84a43d70f examples/order_edit_request.md --spec-dir ./specs-edit-e2e --author devansh
   ```
   Assert: per-slug summary printed; re-rendered `specs-edit-e2e/order-fulfillment-workflow.md`
   contains the finance-notification activity with `[human]` marker; shipment retry statement
   says 5 attempts; the $1,000 manager-approval rule is gone; owner is "Fulfillment Operations
   Team"; version bumped `0.1.0 → 0.1.1`; project JSON has one `EditRecord` (verbatim doc);
   stage back to `spec_drafted`. If the interpreter mismaps an entry, tune the worked examples
   in `prompts/templates/interpret_edit_request.md` — prompt tuning against the real model is
   in scope.
3. **Re-gate to code**
   ```bash
   workflow-compiler validate 3f6be187-d4d7-4f0d-9f90-3eb84a43d70f --spec-dir ./specs-edit-e2e
   workflow-compiler approve-spec 3f6be187-d4d7-4f0d-9f90-3eb84a43d70f --spec-dir ./specs-edit-e2e
   ```
   Assert: grounding pass flags but does **not** strip the human additions; answer any open
   questions in the spec file between the two commands; code lands under
   `./generated/3f6be187-.../order_fulfillment_workflow/` (the out-dir fix), and the generated
   Temporal code contains the new activity stub and the updated retry policy.
4. **Multi-workflow edit exercise (full coverage — see the dedicated section below).**
   Build `examples/ideal_multi_workflow_edit_request.md` (does not exist yet), compile
   `examples/ideal_multi_workflow.md` to a fresh spec dir, apply the edit file, and work
   the observe → diagnose → fix loop until every operation class lands correctly across
   multiple workflows at once.
5. **Failure paths** — (a) edit doc with an unknown slug → clean CLI error *before any LLM
   call*, project untouched; (b) a bullet like "make it better" → error listing the entry
   verbatim under "could not be translated", project untouched (atomicity against the real
   model).
6. **API + frontend smoke** — `uvicorn workflow_compiler.api.app:app` + `cd frontend && npm run
   dev`; open the project, click **Edit request**, paste the same edit doc, Apply. Assert: the
   spec diff renders in the right panel, Edit history shows the record, stage badge returns to
   "Spec drafted", and Validate/Approve re-arm (Approve disabled until Validate runs).

Record the transcript (commands + key output) in the PR description.

## The multi-workflow edit exercise (scenario 4, in full)

Goal: see how well the editing process holds up when one edit document touches **several
workflows in the same request**, understand exactly where it goes wrong, and fix it. The
single-workflow scenarios above prove the mechanics; this exercise is where the interesting
failures live — the interpreter matching entries against the wrong workflow's elements,
wiring ops pointing at the wrong slug pair, or one workflow's failure not cleanly aborting
the others (atomicity across sections).

**Step 1 — create the edit file.** Write `examples/ideal_multi_workflow_edit_request.md`
against the project compiled from `examples/ideal_multi_workflow.md` (compile it first and
take the slugs from the spec dir — do not guess them). The file must exercise **every
operation class, and each of add / edit / remove within them**, spread across at least two
`## Workflow:` sections so cross-workflow confusion has a chance to show up:

- Per-workflow content, in *each* targeted workflow's section:
  - `### Add` — at least one activity, one business rule, and one element of another kind
    (timer, exception, or compensation).
  - `### Modify` — at least one rename (activity by its quoted label), one value change
    (retry count or timer duration), and one metadata change (owner or an actor).
  - `### Remove` — at least one rule and one structural element that other elements
    reference (to confirm the dangling-reference pruning + warning behaves outside the unit
    tests).
- Cross-workflow wiring:
  - `### Triggers` — add one trigger between two of the workflows *and* modify or remove a
    trigger the original compile discovered.
  - `### Dependencies` — add one output→input link and remove an existing one.
- Structural ops in the same document:
  - `## Add Workflow:` — one new workflow with a proper document-format body.
  - `## Remove Workflow:` — one existing workflow (pick one that has wiring attached, so the
    drop-and-log path is exercised).

**Step 2 — apply and observe.** Run the edit against cloud Nemotron. For every entry in the
file, check the outcome in the re-rendered spec files, the printed per-slug summary, and the
`EditRecord`:

- Did each entry land in the **right workflow**? (This is the failure mode multi-workflow
  uniquely exposes.)
- Did modifies match the intended element (right id, right statement) rather than a
  similarly-named one in another workflow?
- Did the wiring ops resolve the correct slug pair and direction?
- Did the removed workflow's wiring drops get logged, and did the added workflow come out of
  discovery/facts with a sane spec?
- Are versions bumped exactly once per touched workflow, and is there exactly one
  `EditRecord` covering everything?

**Step 3 — diagnose and fix what goes wrong.** Expected failure sources, in likelihood
order, and where the fix lives:

1. *Interpreter mismaps an entry* (wrong target id, wrong `old` statement, invented ops) →
   tune `prompts/templates/interpret_edit_request.md`: sharpen the worked examples, or add a
   multi-workflow example showing that only the shown spec's ids are valid targets.
2. *Entries land as `unresolved` that a human finds unambiguous* → same prompt file; also
   consider whether the rendered `project_context` (built in
   `ProjectCompiler._project_context`) gives the model enough wiring context.
3. *Deterministic apply drops a patch* ("could not be applied") → decide whether the entry
   was genuinely wrong (fix the doc) or the applier's matching is too strict (fix in
   `agents/review_pipeline.py` appliers or `spec/edit_applier.py` — never by weakening the
   review-mode defaults).
4. *Wiring op errors* (unknown endpoint, no matching trigger) → check
   `_apply_trigger_op`/`_apply_xref_op` in `project_compiler.py`; their matching is
   deliberately exact, so most failures here are the interpreter emitting the wrong slugs —
   which points back to the prompt.

Iterate the edit file + prompt until the whole document applies in one shot. Then finish
with `validate` → `approve-spec` and confirm the regenerated code reflects the edits in
every touched workflow.

**Step 4 — keep the artifacts.** Commit the finished
`examples/ideal_multi_workflow_edit_request.md` as the canonical multi-workflow example
(reference it from `docs/EDIT_FORMAT_GUIDE.md` next to the single-workflow one), and capture
anything learned about model behavior as new worked examples in the prompt template — that
is how the lessons persist.

## Next implementation steps (in priority order)

1. **Finish Tier 2 scenarios 2–6 above** and tune `interpret_edit_request.md` against the real
   model as needed. This is the gate for calling the feature done.
2. **Split/merge phase** (syntax already reserved: `## Split Workflow: <slug>`,
   `## Merge Workflows: <a> + <b>`; parser rejects with "reserved for a future release").
   Design sketch agreed during planning:
   - *Split*: re-run segmentation over the source spec's rendered text; mint fresh element ids
     per child with a recorded old→new map; re-attribute triggers/xrefs to the correct child;
     log as `workflows_added` + `workflows_removed`.
   - *Merge*: concatenate facts with collision-safe id renumbering; explicit metadata
     precedence rules; collapse intra-pair triggers into internal transitions; retarget
     external wiring to the merged slug.
   - Both re-enter the same validate → approve-spec gate.
3. **Repo hygiene (user-visible litter)** — the root still contains tracked one-off dirs
   (`generated-2/`, `generated-fe24cff8/`, `generated-ideal-*/`, `specs-*`, …) from before the
   out-dir fix. Decide which to keep as examples (`generated/` is the documented one) and
   `git rm` the rest. New runs no longer create these.
4. **Nice-to-haves surfaced during implementation** (not committed to):
   - Frontend: render the `[human]` provenance markers distinctly in the spec preview;
     show `EditRecord.resolved_patches` detail in the history panel.
   - `edit --dry-run` (interpret + report the plan without applying) — cheap now that
     interpretation and application are separate phases.
   - Rollback: `edit_log` records what changed but there are no snapshots; a
     `revert <edit-id>` would need inverse patches or stored spec snapshots (explicitly
     descoped earlier — revisit only if users ask).

## Gotchas for whoever picks this up

- `.env` now says `WORKFLOW_COMPILER_LLM_PROVIDER=nemotron`. The eGPU box is NOT used unless
  you pass `--provider local` / `local-fallback` (gateway auth via `LLM_GATEWAY_EMAIL`/
  `LLM_GATEWAY_PASSWORD`; models list at `/auth/config`).
- The `edit` flow errors on *any* dropped patch ("could not be applied") — including an ADD of
  something already present. That is deliberate (human edits must not silently vanish); tell
  users to delete satisfied entries from the doc and re-run.
- `mypy src` is not baseline-clean (35 pre-existing errors). Diff against baseline; don't
  chase them. Use the `.venv` interpreter and `PYTHONIOENCODING=utf-8` when piping CLI output.
- Never weaken the default (review-mode) `SpecPatchApplier` to serve the edit path — the
  human-authority mode is the only sanctioned bypass, and `tests/test_edit_applier.py` guards
  the review-mode behavior.

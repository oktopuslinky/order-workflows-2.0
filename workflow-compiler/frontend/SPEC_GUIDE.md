# Editing spec files — a field guide

This explains how to fill out the **spec Markdown** the workflow-compiler frontend puts in front of
you, what every section means, and the small grammar the parser relies on. The spec is the **human
gate**: you edit it until it's right, then approve it to generate runnable Temporal code.

---

## The loop

```
Upload / paste a document
      │  (compiler segments it → one spec per workflow)
      ▼
Edit the spec  ⇄  Save   (instant, no LLM — just folds your edits back in)
      │        ⇄  Validate (LLM review passes + integrity checks → findings)
      ▼
Approve  →  graph + CVPA + Temporal design + code per workflow
```

**Golden rule (the UI enforces it):** after any edit, **Validate must run before Approve.** Approve
checks the findings from the *last* validate, so the button stays disabled while the banner reads
“Edited since last validate.” Click **Validate**, review the findings, then **Approve**.

- **Save** — writes your Markdown back onto the structured spec. Deterministic, no model, no findings.
  Use it to checkpoint. It does **not** clear the “must validate” state.
- **Validate** — folds edits in, runs three LLM passes (completeness → grounding → consistency) plus
  a deterministic cross-workflow integrity check, and returns **findings**. The editor reloads with
  the re-rendered spec.
- **Approve** — compiles every workflow to code. Blocked while any `BLOCK` finding remains or a
  dependency is unconfirmed, unless you tick the override checkboxes.

---

## Two kinds of section

| Kind | Sections | Role |
|---|---|---|
| **Structural (executable)** | Activities, Decisions, Exceptions, Compensations, Events, Triggers | Carry `[id]` markers; become the graph → Temporal code. **Order = runtime order.** |
| **Descriptive (reference)** | Purpose, Metadata, Inputs, Outputs, Business Rules, API Interfaces, Systems Involved, Timers & SLAs, Retries, Assumptions, Ambiguities | Context and documentation. **Never wired to code.** |

> **API calls happen inside Activities, not in the “API Interfaces” list.** API Interfaces documents
> *which* systems the workflow touches; an **Activity** is *where and when* a call runs (its generated
> stub is where the real call goes). If an API must fire at a point in the flow, model it as an
> activity (e.g. `- Charge card via Payments API — after: a2`), not only as an API-Interfaces line.

---

## The grammar (what the parser depends on)

Keep these intact and edits round-trip cleanly:

- **`[id]` markers** — `- [a3] Ship order`. The id ties your edit to an existing element. A line
  **without** an id is treated as a **new, human-provided** element. Never renumber ids by hand.
- **Tail syntax** — `— key: value; key: value` after the label (that’s an em-dash `—`). Each section
  allows specific keys (below).
- **Provenance markers** — a trailing `[human]` or `[inferred]`; no marker means document-grounded.
  You don’t write these; the system maintains them. Lines you add become `[human]`, which the
  validator may *flag* but will **never delete**.
- **Delete = remove the element.** Delete a line to drop it. (Your `[human]` lines are never
  auto-removed; machine lines can be.)
- **Empty section** renders `<!-- none -->`. Leave it, or add bullets.

---

## Section-by-section

### Purpose
One line: what the workflow is for. Free text.

### Metadata
`- key: value` lines. Scalars: `domain`, `owner`, `version`. Lists (comma-separated):
`actors`, `systems`, `triggers`, `start states`, `end states`, `tags`.
`domain` / `owner` / `tags` often extract blank from documents — fill them in if you care about them.

### Inputs / Outputs
One `- statement` bullet each. Inputs are what the workflow receives; Outputs what it produces.
For multi-workflow projects, an Output that another workflow consumes shows up under **Cross-Workflow
Dependencies** (below).

### Activities  — the units of work
```
- [a1] Validate cart
- [a2] Reserve inventory — parallel: g1
- [a3] Charge card — parallel: g1
```
- Tail key **`parallel`** — activities sharing a group label (`g1`) run concurrently
  (`asyncio.gather`). Put the same group on every member.
- This is where **API/system calls live.** Name the action imperatively; the generated
  `activities.py` stub is where the real call is implemented.

### Decisions  — branch points (**highest-stakes edits**)
```
- [d1] Is the order eligible? — after: a1; yes: a2; no: e1
```
- **`after`** — the activity whose result is being judged.
- **`yes` / `no`** — where each branch goes (an activity/event/exception id, or a terminal token like
  `end`, `reject`, `fail`).
- **Always give the `no:` branch.** A rejecting `no:` that points at an exception is what generates a
  real `raise` in the code (which fires the saga rollback and *fails* the run). A missing `no:` is the
  #1 thing the readiness check raises as an **Open Question** — answer it.

### Exceptions
```
- [e1] Order ineligible — raised by: a1
```
- **`raised by`** — the activity that can throw it. Without it, the exception isn’t attributed to a
  step. A decision’s `no:` typically points here.

### Compensations  — saga rollbacks
```
- [c1] Release inventory — compensates: a2
```
- **`compensates`** — the activity this reverses. On failure, compensations run in reverse order.
- If the same action appears as **both** an Activity and a Compensation, delete the activity line —
  it’s the rollback, not forward work.

### Events  — and the critical `kind`
```
- [v1] OrderPlaced — kind: trigger; emitted by: start
- [v2] PaymentConfirmed — kind: signal_wait
- [v3] OrderShipped — kind: output_emit; emitted by: a3
```
- **`kind`** decides how the event compiles — set it correctly (the right panel gives you a dropdown):
  - **`trigger`** — an inbound event that *starts* the workflow.
  - **`signal_wait`** — the workflow *pauses mid-flow* to receive an external signal. This is what makes
    a wait a **bounded `wait_condition`** instead of a hang. If a “Wait for X” is mislabeled
    `output_emit`, fix it to `signal_wait`.
  - **`output_emit`** — the workflow *produces* a value (an activity’s return).
- **`emitted by`** — the activity (or terminal token) that emits it.
- If an Output is duplicated as an event, delete the event line.

### State Transitions
`- source -> target (trigger: X)` — narrative state changes. Advisory; not the control flow.

### Business Rules / API Interfaces / Systems Involved / Timers and SLAs / Retries
Reference facts, one `- statement` per bullet. Documentation only — see the callout above about API
Interfaces. Timers/SLAs and Retries you wrote in the source doc are applied to activities during
design, but these list entries themselves are descriptive.

### Assumptions / Ambiguities / Suggested Edits
Review notes, one bullet each. Read them; they flag where the extraction guessed or the document was
unclear. Delete or edit freely.

### Open Questions  — answer these
```
- [ ] (R2-no-branch) Decision d1 has no rejection branch — where should "no" go?
  Answer:
```
- Tick `[x]` and fill the `Answer:` line. The right-panel **Open questions** widget does both for you.
- **Unanswered *required* questions block Approve** (override with the “Accept unanswered required
  questions” toggle).

### Cross-Workflow Dependencies  — confirm the links
```
- [ ] uses output `order_id` of `order-placement` as input `order_ref` — the placed order
```
- One workflow’s output feeding another’s input. **Tick `[x]` to confirm.** Unconfirmed dependencies
  **block Approve** (override with “Allow unconfirmed dependencies”). The **Cross-workflow
  dependencies** widget gives you the checkboxes.

### Triggers  — one workflow starting another
```
- [x] triggers `account-provisioning` (blocking) when `application approved`
  result: provisioning_result
  input customer_record_id: step output `a2` (str)
```
- Head line: `triggers <slug> (blocking|fire-and-forget) when <condition>`.
  - **blocking** — the caller awaits the target’s result (bound to `result:`).
  - **fire-and-forget** — start and move on.
  - The `when …` predicate is LLM-drafted — **review it and tick `[x]` to confirm.**
- Indented lines: `result: <name>` and one `input <field>: <source> \`ref\` (<type>)` per target input
  field (source = `workflow input` / `step output` / `constant`).
- **A trigger is a human call.** If the compiler scaffolded one that shouldn’t fire (e.g. auto-starting
  a *customer-initiated* workflow), **delete it** — the **Triggers** widget has a Delete button.

---

## The right-hand panel (structured widgets)

The widgets are shortcuts that edit the Markdown for you — the Markdown is still the source of truth,
so anything you can do in a widget you can also type by hand:

- **Findings** — BLOCK (red) / WARN (yellow) / INFO (dim) from the last Validate.
- **Open questions** — answer + auto-tick.
- **Cross-workflow dependencies** — confirmation checkboxes.
- **Triggers** — confirm or delete.
- **Events** — set each event’s `kind` from a dropdown.
- **Removed by validate** — if a Validate pass deleted a line you believe was correct, it appears here
  with a one-click **Re-add** (re-added lines are recorded as human-provided and stick).

---

## Findings cheat-sheet

- **BLOCK** (red) — structural breakage: a trigger targeting an unknown workflow, an input map naming a
  field the target doesn’t declare, an unisolated document segment, an unmet required question.
  **Blocks Approve.**
- **WARN** (yellow) — should be confirmed but doesn’t block: type mismatch on a hand-off, unconfirmed
  trigger predicate, a blocking trigger with no `result:`.
- **INFO** — informational (e.g. an edit that was folded in).

When you’re happy and BLOCK count is 0 (or overrides are ticked), **Approve** → the **Results** tab
shows the per-workflow diagram, CVPA table, generated files, and a **Download .zip**.

---

## `changes.md` — the change spec of a knowledge-graph-grounded project

When a project is compiled **with a knowledge base** (home page → *Ground with knowledge base*, or
a change request’s **Send to workflow GUI**), the Spec tab gets a second kind of file next to the
workflow specs: `changes.md`, the **change spec** — one block per component of the existing code
base that the design document changes, each with what exists today and what is proposed. It goes
through the same Save ⇄ Validate ⇄ Resolve ⇄ Approve gate; the header shows *Grounded by ‹KB› ·
from ‹change request›*.

```
# Change Spec

## Grounding                      ← read-only (knowledge base, change request, version)
- knowledge base: Order lifecycle (`86d9…`)
- change request: BCR-001 … (`dfad…`)
- version: 1

## Components
### provision_order — activity, modify [inferred]
- path: `fn:existing_Codebase/activities/order_activities.py:provision_order`
- requirements: BCR-01-02, BCR-01-03

#### Existing
Provisions the whole order and returns one ProvisioningResult.

#### Proposed
Takes a shipment group and returns one result per group; …

## Assumptions
- Groups are decided at capture time. [inferred]

## Open Questions
- [ ] Should a cancelled group be refunded immediately?
  Answer:

## Sources                        ← read-only (corpus files + line spans the prompts saw)
- `existing_Codebase/workflows/order_workflow.py — lines 1-112`
```

Grammar (what the parser depends on):

- **Component heading** `### <name> — <kind>, <change_type> [marker]` — `kind` is one of
  `module | activity | workflow | type | signal | query | test | diagram | doc`; `change_type` is
  `modify | add | remove | verify`. Keep the heading of an existing entry so your edit updates the
  right component; a new heading is recorded as human-provided; a deleted heading removes the
  component. The trailing `[human]` / `[inferred]` marker is rendered — never type it.
- **`- path:`** — where the component lives: a knowledge-graph node id
  (`mod:existing_Codebase/shared/types.py`, `fn:…:provision_order`) or a corpus-relative file path.
  Empty for something that does not exist yet.
- **`- requirements:`** — comma-separated change-request requirement ids (`BCR-01-02`).
- **`#### Existing` / `#### Proposed`** — free text until the next heading. `<!-- none -->` means
  empty. **An empty Proposed is a BLOCK** — say what changes (for a removal, what is removed and what
  replaces it).
- **Assumptions / Open Questions** work exactly like the workflow spec’s (`- text`, `- [ ] (ref)
  question` + `Answer:`; the *Open questions* widget applies here too).
- **Grounding** and **Sources** are read-only — whatever you type there is ignored.

Findings for `changes.md` show under the `changes.md` entry in the left rail (and in the Resolve
tab, where the guided dialogue asks about them):

- **BLOCK** — a component with no proposed change.
- **WARN** — a `path` that is not in the knowledge base (with *did you mean …* suggestions from the
  graph); a requirement id the change request does not declare; ingest notes.

---

## Change outputs — what a grounded project produces after Approve

Approving the specs of a knowledge-graph-grounded project starts a follow-on **change_outputs**
job (cloud Nemotron by default). The Results tab gains a **Workflows | Change outputs** switch;
the second view has three stages, each persisted the moment it finishes:

| Stage | What you get | Deterministic checks |
|---|---|---|
| **Diagrams** | every `.mmd` of the knowledge base regenerated + the companion diagram(s) the change spec adds + the per-workflow spec diagram, assembled into `system-flow-diagram.md`; Updated / Original toggle | Mermaid header, every required state present, balanced `subgraph`/`state` blocks (one repair round) |
| **Code** | the modified code base — the change-spec files **plus every corpus file that imports a rewritten module**, in order types → activities → workflow → worker/starter → tests; unified / side-by-side diff, the updated file, `changes.patch` | per file: `ast.parse`, dataclass sanity, required change-spec symbols, imports against the rewritten siblings, ruff (F/E9); **up to N targeted repair rounds** (default 2 — the pill reads `repaired ×2`); a **keep-style** pass (`style kept`); then a **bundle smoke test** (`py_compile` + `import` of the whole export layout in a child interpreter — passed / failed / skipped, per-module errors) |
| **Test cases** | the TC matrix with new rows (`TC-18…`, ids from the KB catalog) and updated rows (originals never dropped, notes appended); a Test-Plan **addendum** (`.docx` / `.md`) | id allocation, merge rules |

**Download all (.zip)** exports the README layout (`src/`, `tests/`, `docs/diagrams/`,
`docs/test-cases/`, `changes.patch`, `CHANGES.md`). **Regenerate** re-runs one stage or all of
them; while another job (validate / approve / outputs) runs the button answers 409 — wait for it.

What the verdicts mean: **ast fail** — the file does not parse even after the repair rounds (kept
as-is with the error; fix by hand); **ruff findings** — pyflakes-class problems the repair rounds
did not clear (undefined names are auto-imported when they are well known); **smoke failed** — the
bundle imports up to the module named in the card; nothing here is a gate — the code stage delivers
a checked, reviewable draft, and a human still reads the diff (see the RUNBOOK's honest test
results).

**Saving is compare-and-swap.** Every project / change request carries a `version`; the editors
send it back with a save and a `409 … changed since it was loaded` means another tab or a job saved
first — click *Reload the latest version* and re-apply the edit.
- **INFO** — a folded-in edit.

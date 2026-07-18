# Shot list — the take

Companion to `HANDOFF.md` (which is authoritative; read it first).

Document: **`examples/ideal_multi_workflow.md`** (Order Placement → Fulfilment → Return).

Each `MARK` is a `__demoMark(...)` call. `video/src/scenes.ts` cuts the edit on these names, and
a **missing mark throws at render time**, listing the marks that *were* recorded. Extra marks are
harmless. **23 marks — hit every one.**

No narration; captions carry the argument. The film ends on the `.zip` download.

---

## Ground truth (measured against live Nemotron, 2026-07-13)

| Step | Result | Time |
|---|---|---|
| compile (fresh) | 3 specs, 3 cross-refs, 3 triggers | **~400s** |
| validate #1 | 3 warnings, 0 blocking | **~75s** |
| approve, deps unconfirmed | **REFUSES** — "Unconfirmed cross-workflow dependencies must be validated before approval" | instant |
| validate, hand-off broken | **1 BLOCKING** — "trigger to 'order-fulfilment' maps to input 'order_id', which 'order-fulfilment' does not declare" | **~160s** |
| validate, fixed | 0 blocking | **~110s** |
| approve (clean) | **all three workflows generate** | **~360s** |
| generated per workflow | `shared.py` `activities.py` `triggers.py` `workflow.py` `worker.py` `starter.py` `test_stepthrough.py` `README.md` | |

Total ≈ **35–45 min**, mostly LLM wait. The edit compresses it to **~2:51**, always disclosing the
speed-up with a true-elapsed clock (`WaitClock`).

---

## Act I — document in

| Beat | Action | MARK |
|---|---|---|
| 1 | Land on `/`, upload `ideal_multi_workflow.md` | `upload` |
| 2 | Click **Compile** | `compile-start` |
| 3 | *Real ~400s wait.* Compressed 46× in the edit, true clock on screen. | |
| 4 | Compile returns | `compile-done` |
| 5 | Workspace loads, 3 workflows in the rail | `workspace` |

## Act II — what came back

| Beat | Action | MARK |
|---|---|---|
| 6 | Workflow tabs; **Editor → Preview → Diagram** | `views` |
| 7 | Click **Classify phases (CVPA)** — *inside the Diagram view* | `cvpa-start` |
| 8 | Classification returns; diagram recolours by phase | `cvpa-done` |
| 9 | Settle on the coloured diagram | `gate` |

## Act III — the human gate

| Beat | Action | MARK |
|---|---|---|
| 10 | **Validate** (Approve is disabled until a validate has run) | `validate0-start` |
| 11 | 3 warnings, 0 blocking. The draft looks good. | `validate0-done` |
| 12 | Click **Approve** → **it REFUSES**: unconfirmed dependencies. **HOLD ~14s at 1×.** | `refuse` |
| 13 | Tick every dependency + trigger on all 3 workflows; answer `R4-decisions`. **Leave both APPROVE OVERRIDES boxes OFF.** | `confirm` |
| 14 | **Deliberately break** the hand-off: in `order-fulfilment` `## Inputs`, rename `- order_id` → `- placed_order_id`. Save once. | `break` |
| 15 | Poll until the PUT lands, then **Validate** | `validate-start` |
| 16 | **1 BLOCKING**, naming the exact mapping. Select **order-placement** (it owns the trigger; badge shows `1`). **HOLD ~14s at 1×.** | `validate-done` |
| 17 | Rename the input back, **Save** | `fix` |
| 18 | **Validate** again | `revalidate-start` |
| 19 | 0 blocking. Approve unlocks. | `revalidate-done` |

## Act IV — code out

| Beat | Action | MARK |
|---|---|---|
| 20 | **Approve** (no overrides ticked). *~360s wait.* | `approve-start` |
| 21 | **All three workflows generate.** | `approve-done` |
| 22 | Results tab — per-workflow diagram, graph health, CVPA phase table | `results` |
| 23 | Generated files: `workflow.py`, `activities.py`, `worker.py`, `triggers.py` … | `code` |
| 24 | Browse the code | `download` |
| 25 | **Download .zip**. Final frame. | `end` |

---

## Traps

- **Save → Validate is a race.** Poll the server until the edit is persisted, *then* validate.
- **CodeMirror ignores value-setting.** Select the line's text range and type over it with real
  key events. Markdown highlighting splits tokens across text nodes.
- **Findings are per-workflow** — select the workflow that owns the finding.
- **Port 3000 is a different app.** Use 3001.
- **125% display scaling** (dpr 1.25). Never *compute* the viewport→video transform — the
  calibration flash *measures* it. And prove the flash is on screen with `check_flash.py` before
  recording anything.

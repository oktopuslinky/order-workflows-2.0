# HANDOFF — shoot the demo video end to end

**This file is authoritative.** It supersedes every earlier note in this folder. It was
rewritten on 2026-07-13 after take 1 was shot, recovered, and rejected — and after the
`R4-decisions` bug that take exposed was fixed. Where an older doc disagrees with this one,
this one wins. `SHOTLIST.md` is the per-beat companion.

Read this whole file before touching anything. Almost every rule below is here because its
absence cost a take.

---

## 1. What the film argues

One sentence: **the LLM drafts the spec, a human corrects it, validation re-runs, and only
then does the compiler emit runnable Temporal code.**

Two beats carry the argument. Both are held at **1× real time** in the edit:

1. **The gate refuses.** The spec looks clean — three warnings, nothing blocking — but Approve
   is *refused*, because the cross-workflow dependencies were inferred by the model and no
   human confirmed them.
2. **The validator catches a deliberate break.** We rename an input the next workflow depends
   on. Validate returns **one blocking finding naming the exact broken mapping** — not
   "something is wrong".

Everything else is plumbing and gets speed-ramped.

### Fixed decisions (do not relitigate)

| Decision | Choice |
|---|---|
| Narration | **None.** Captions carry everything; the film must work with sound off. |
| Length | **2–3 minutes.** |
| Ending | **All three workflows generate**, then download the `.zip`. |
| Act V (`pytest` proof) | **Dropped.** |

> **Never caption the ending with graph-health scores.** Take 1 ended with two workflows "held
> below the 0.90 health gate". That was **a bug, not a feature** — a required question was
> reported unmet although it was ticked *and* answered. It is fixed. All three workflows now
> generate, and a caption claiming 0.80/0.45 health scores would be false.

---

## 2. State right now (verified — do not re-derive)

- **Backend `:8000` restarted 2026-07-13 14:27, so it carries the `R4-decisions` fix**
  (`checklist/validator.py`, `checklist/amend.py`, `project_compiler.py`, edited 13:46–13:47)
  and the `llm_timeout=400` change. It runs **without `--reload`**: if you edit backend code,
  restart it by hand or your change is not live. That mistake wasted a take.
- **Frontend `:3001`.** Port **3000 is a different app** on this machine (ScopeNotes).
  Pointing the recorder at 3000 records the wrong product for 45 minutes.
- `demo/video/src/scenes.ts` is rewritten for the 23 marks in §4, typechecks clean, and renders
  against the synthetic fixture at **5117 frames = 2:51** — inside target.
- Take 1 is archived as `demo/capture/take1-2026-07-13-*`. Not reusable (§9), but keep it until
  the new take is safely in the can.

---

## 2b. What take 2 changed (2026-07-13, shot with Playwright MCP)

Take 2 ran clean to `results` (21/23 marks) and was then **stopped deliberately**: order-placement
was held at **health 0.85**, below the 0.90 gate. That was NOT the `R4-decisions` bug — it was the
structural reviewer flagging **`Trigger order-fulfilment` / `Trigger order-return` as "dead-end
nodes with no outgoing edges"**. A fire-and-forget trigger *is* terminal — it starts another
workflow and control never returns — exactly like the terminal EVENT nodes the check already
exempted. Two bogus warnings × 0.05 = the 0.05 that sank it.

**Fixed** in `graph/review.py::_check_dead_ends` (TRIGGER now exempt alongside EVENT). Replayed
against take 2's real graphs: placement **0.85 → 0.95**, fulfilment 0.95 → 1.0, return 1.0. All
three clear the gate, and the one legitimate warning (duplicate `release inventory reservation`
label) correctly survives. Full suite green. **So §1's "all three workflows generate" is true
again — but only with this fix live.** Backend restarted after it; it now runs *without* `--reload`.

Also corrected, each having cost time:

- **`record.ps1 -Stop` still lost the file.** §9.1 claims CTRL_C fixed the missing-moov problem. It
  did not: ffmpeg takes the CTRL_C and dies *without* writing the index. The recorder now writes a
  **fragmented mp4** (`-movflags +frag_keyframe+empty_moov+default_base_moof`), which is playable at
  every instant, so no stop path can lose a take. Verified: 56.3 MB / 1817.5s, index readable, and
  video duration == wall clock (15fps held, no dropped frames).
- **`record.ps1`'s "is it growing?" check was a false alarm.** A still desktop encodes to almost
  nothing and the writer flushes in 256 KB blocks, so 1 second of no growth proved nothing — it
  aborted a perfectly good recorder *before* `start.json` was written, losing clock zero. Now polls.
- **A fresh compile derived NO open questions** (`<!-- none -->` in all three specs). There was no
  `R4-decisions` to answer. §3's answer bank is a guide to *right answers*, not a checklist — the
  `confirm` beat may be confirmations only.

### Driving with Playwright MCP instead of chrome-devtools

- **`browser_resize` does NOT resize the window.** It installs a device-metrics *emulation* and
  forces dpr to 1, while the real OS window — the thing gdigrab records — stays put. Resize the
  actual window over a raw CDP session instead:
  `Browser.setWindowBounds {left:0, top:0, width:1520, height:900}` → viewport 1506×806 @ dpr 1.25.
- `preflight.ps1` now takes **`-ProfileMatch ms-playwright-mcp`** (Playwright owns its own profile
  and drives it over a debug *pipe*, so there is no CDP port and `launch-chrome.ps1` is unused).
- The Playwright sandbox has **no filesystem access** — inline `instrument.js` rather than reading
  it. Install it with `addInitScript` so it also survives a hard navigation.
- **The view tabs are lowercase in the DOM** (`editor`/`preview`/`diagram`) and only *look*
  capitalised via CSS `capitalize`. An exact, case-sensitive name match misses them — use `/^preview$/i`.
- **Validate/Approve signal "in flight" by going `disabled`, not by changing their label.** Poll
  `button.disabled === false`, or you will mark a stage done while it is still running.
- Once a finding exists, the rail button's name gains its badge ("order-placement 1"), so
  `{ name: 'order-placement', exact: true }` stops matching. Match by prefix.

---

## 3. The answer bank — replay these, don't improvise

A fresh compile re-derives its own open questions, so treat this as the canonical source of
*what the right answers are*, not a guaranteed 1:1 list. Taken from the validated specs of
project `fe24cff8` (also saved under `specs-fe24cff8/`).

**The only open question** — `order-placement` → `R4-decisions`:
> *"For each flagged decision, what happens on the 'no' branch (name the exception or next step)?"*

**Answer:** `On decline, raise PaymentDeclined and cancel the order`

**Confirmations to tick — 5 dependencies + 3 triggers across the three workflows:**

| Workflow | Confirm |
|---|---|
| order-placement | dep `order_id` → order-fulfilment; dep `order_id` → order-return; trigger → order-fulfilment; trigger → order-return |
| order-fulfilment | dep `order_id` from order-placement; dep `shipment_id` → order-return; trigger → order-return |
| order-return | dep `order_id` from order-placement; dep `shipment_id` from order-fulfilment |

⚠️ **The two `APPROVE OVERRIDES` checkboxes — "Accept unanswered required questions" and
"Allow unconfirmed dependencies" — must stay OFF.** They are not confirmations; they are the
escape hatch, and ticking them defeats the entire point of the film. In take 1 a naive
"tick everything unchecked" loop switched them on by accident.

---

## 4. The 23 marks

Fire every one, in order. A **missing** mark throws at render time (`Demo.tsx: resolveScene`),
listing the marks that *were* recorded. **Extra** marks are harmless — if you need to isolate
an unexpected LLM wait, fire a new mark and split the scene in post.

```
upload  compile-start  compile-done  workspace  views
cvpa-start  cvpa-done  gate
validate0-start  validate0-done        <- Approve requires a prior validate
refuse                                 <- MONEY SHOT 1 (hold ~14s, 1x)
confirm  break
validate-start  validate-done          <- MONEY SHOT 2 (hold ~14s, 1x)
fix  revalidate-start  revalidate-done
approve-start  approve-done
results  code  download  end
```

### The flow, precisely

1. Upload `examples/ideal_multi_workflow.md`, click **Compile** (~400s).
2. Browse the three workflows; Editor → Preview → **Diagram**.
3. **Classify phases (CVPA)** — the button lives *inside the Diagram view*, not the toolbar.
4. **Validate** (~75s). Three warnings, zero blocking. **Approve is disabled until a validate
   has run** — that is why `validate0` exists.
5. Click **Approve** → **it refuses**: unconfirmed cross-workflow dependencies. → `refuse`, hold ~14s.
6. **One edit pass:** tick all confirmations across all three workflows, answer `R4-decisions`,
   **and** break the hand-off — then Save once. One pass keeps the take to three validates.
   (Take 1 ticked them in two passes and paid an extra ~90s validate for it.)
7. **Validate** (~160s) → **1 BLOCKING**, naming the mapping. → `validate-done`, hold ~14s.
8. Rename the input back, Save, **Validate** (~110s) → 0 blocking.
9. **Approve** (~360s) → all three generate.
10. Results → per-workflow diagram, health score, CVPA phase table → generated files →
    **Download .zip**. Final frame.

Expect **~35–45 min** of wall clock, most of it LLM wait. The edit compresses it to ~2:51.

### The break (pinned — do not improvise on camera)

In the **order-fulfilment** spec, under `## Inputs`:

```
- order_id          ───rename to───►          - placed_order_id
```

`order-placement`'s trigger maps its `order_id` output to `order-fulfilment`'s `order_id`
input. Renaming the input leaves the trigger pointing at something the target no longer
declares → exactly one blocking finding. **The fix is to rename it back.**

⚠️ The finding is filed against **`order-placement`** (the workflow that owns the trigger), not
against order-fulfilment. **Select `order-placement` in the rail or the money shot is off
screen.** Its rail button shows a `1` badge. Expected text:

> `trigger to 'order-fulfilment' maps to input 'order_id', which 'order-fulfilment' does not declare`

---

## 5. Recording sequence

```powershell
demo\capture\launch-chrome.ps1     # clean throwaway profile, CDP :9222, opens localhost:3001
demo\capture\preflight.ps1         # enforces ONE demo Chrome, clears the desktop,
                                   # un-maximizes and truly foregrounds it (verified)
```

Then over the browser MCP:

```
resize_page(1500, 790)     # -> 1500x790 CSS = 1875x988 physical @ dpr 1.25, fits inside 1920x1200.
                           # Chrome IGNORES --window-size and opens MAXIMIZED, and a maximized
                           # window cannot be resized over CDP -- preflight.ps1 un-maximizes it.
                           # Redo this on every relaunch.
evaluate: <contents of demo/capture/instrument.js>   # installs __demoMark / __demoCalibrate / __demoDump / __demoReset
evaluate: __demoReset()
```

```powershell
demo\capture\record.ps1 -Name app   # MUST print "Recording CONFIRMED ... 15fps ... growing N -> M bytes".
                                    # If it throws, STOP -- nothing is being captured.
```

```
evaluate: __demoCalibrate(15000)    # the four-square colour clapperboard. FIRST THING IN FRAME.
```

```powershell
python demo\capture\check_flash.py  # MUST print "ALL 4 MARKERS VISIBLE"
```

> **Do not drive a single click until `check_flash.py` passes.** Take 1's flash was painted into
> a page that was not the visible window, so the footage had no calibration anchor at all — and
> 41 minutes of otherwise perfect video became uncuttable. This single check is the difference.
> If it fails, its error message tells you which of the three causes it is.

Then drive §4 and **leave the machine completely alone.** gdigrab records whatever is on top:
one notification toast or one window steal lands in the frame. Turn on Focus Assist first.

---

## 6. Driving notes (each cost a cycle)

- **Save → Validate is a race.** Clicking Validate straight after Save validates the *stale*
  spec — the PUT has not landed. **Poll `GET /projects/{id}` until the edit shows up in the
  response, then validate.**
- **CodeMirror ignores value-setting.** There is no `cmView` handle on the DOM. Edit by selecting
  the exact line's text range (walk `.cm-line` nodes — markdown highlighting splits tokens, so
  `"## Inputs"` will *not* match as a single text node) and typing over it with real key events,
  which CM6 honours.
- **Findings are per-workflow.** The FINDINGS panel shows only the selected workflow's findings.
- **CDP `evaluate` has a ~180s protocol timeout.** A poll loop that waits out a 400s compile
  inside one call will error — though the in-page promise keeps running. Poll in short calls.
- **The app shows its own elapsed clock** while an LLM stage runs ("05:11 elapsed"). Use it to
  tell "slow" from "hung".
- **Context economy:** avoid full a11y snapshots mid-take; prefer small `evaluate` calls that
  return tiny JSON.

---

## 7. Teardown — in this order

```powershell
evaluate: __demoDump()                   # returns a JSON *string* -> write to demo/capture/events.json
demo\capture\record.ps1 -Name app -Stop  # sends CTRL_C, then ffprobes; THROWS if the file has no
                                         # index -- while the app is still open and re-recordable
python demo\capture\calibrate.py --name app   # expect scaleX ~= scaleY ~= 1.25
python demo\capture\prepare.py  --name app
```

**Before you dismiss the browser, check: video duration must equal wall-clock duration.** If a
40-minute take produced 32 minutes of video, gdigrab dropped frames, every mark→frame mapping is
wrong, and the take is dead. That is exactly what killed take 1 (30fps asked, 23.9fps delivered).
It is why the recorder now runs at **15fps** — keep it there unless you re-verify.

---

## 8. Post

```bash
cd demo/video
# First: re-tune the `speed` values in scenes.ts against the REAL gaps between marks in events.json.
npx remotion compositions                                    # want 3600-5400 frames (2:00-3:00)
npx remotion still Rough out/probe.png --frame=N --scale=0.5 # the cursor must land on real buttons
npx remotion render Rough out/demo-rough.mp4                 # burned-in timecodes, for review
npx remotion render Final out/demo-final.mp4                 # the deliverable
```

Duration is derived from the take via `calculateMetadata` → `demoDuration()`, never hard-coded, so
the composition cannot drift out of sync with the footage.

**Final check: watch `Final` with the sound off.** If the argument does not land from the captions
alone, the captions are wrong.

---

## 9. Why take 1 was thrown away

All four are now fixed in the rig. This is the record of *why the code looks the way it does* —
do not "simplify" these away.

1. **`record.ps1 -Stop` used `taskkill`.** ffmpeg never wrote the mp4 index (moov atom), and the
   152 MB file was unplayable. Recovered with `recover_mdat.py`, which lifts SPS/PPS from a
   reference clip encoded with identical settings, converts the intact `mdat` from AVCC to
   Annex-B, and remuxes — 74,500 of 74,501 frames came back. **`-Stop` now sends CTRL_C and
   ffprobes the result.** Keep `recover_mdat.py`: it is the only thing between a crashed ffmpeg
   and a lost take.
2. **30fps was more than gdigrab could sustain** (23.9fps actual), so a 3120s take produced 2483s
   of video, dropped frames were stamped as consecutive, and the mark→frame mapping drifted by
   ~10 minutes. **Now 15fps.**
3. **The calibration flash never reached the screen** — painted into a non-visible window, with a
   second Chrome window on the same profile confusing which surface CDP drove.
   **Now:** `preflight.ps1` enforces exactly one demo Chrome and *truly* foregrounds it
   (`SetForegroundWindow` silently no-ops from a background process unless you
   `AttachThreadInput` to the foreground thread first), and `check_flash.py` proves the flash is
   captured before you commit to the take.
4. **The ending was a bug.** `order-placement` was held on `unmet required checklist items
   ['R4-decisions']` even though that question was ticked and answered. Validate reported clean;
   approve then reported blocking; and the override checkbox only rendered when *validate*
   reported the item unmet — so the workflow could never be approved through the UI at all.
   **Fixed. That is what this re-shoot is for.**

Housekeeping, also from take 1: **check nothing sensitive is on screen.** That desktop had an API
token and a password sitting in Notepad window titles, inside a full-desktop capture.

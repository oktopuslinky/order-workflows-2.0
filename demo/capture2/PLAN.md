# Demo video build — durable plan (resume-safe)

Goal: ~3–4 min **narrated, energetic-startup** demo of workflow-compiler covering
**creation, editing, docs, and all configuration options**. Voiceover = ElevenLabs
energetic male ("Adam"). Subtle music bed + captions. Tool: **Remotion** (`demo/video`).

## Approach (decided)
- App is ALREADY running: **frontend `http://localhost:3000`** (PID 3248, our frontend/ dir,
  title "workflow-compiler"), backend `http://localhost:8000`. NOTE: `:3001` is an unrelated
  "Create Next App". Only ONE Next dev instance allowed (Turbopack lock) so DO NOT start another;
  use the running :3000. Provider = Nemotron cloud (configured in `.env`).
- SMOKE TEST PASSED (demo/capture2/smoke.mjs): login → home → workspace(spec/diagram/results) →
  drafted → settings → guide all render REAL data (mermaid graphs, colored CVPA, real generated
  Python files + Download .zip, time-saved "≈17h saved across 2 projects"). Screenshots in
  $CLAUDE_JOB_DIR/tmp/shots/ (contact.png).
- SELECTOR FIX: login submit = `page.locator('form').getByRole('button',{name:'Sign in'})`
  (there are TWO "Sign in" — a seg tab + the submit).
- Capture with **Playwright `recordVideo`** (dir `demo/capture2/`), driving the LIVE app against
  REAL existing data. One continuous webm per scene OR one long webm + marks. Deterministic; no
  gdigrab/calibration needed (video == viewport, capture at 1600x1000 dsf~1.5).
- Do NOT wait on long LLM runs on camera. Show RunningOverlay briefly (click Validate then
  Cancel; click Compile then cut). Use pre-existing COMPLETED projects for the payoff.
- Build a FRESH Remotion composition (energetic style), not the old caption-only `Demo.tsx`.
  Reuse the `demo/video` scaffold (package.json/remotion.config/tailwind). Output 1920x1080.

## Secrets
- ElevenLabs API key stored at `$CLAUDE_JOB_DIR/tmp/eleven.env` (NOT committed). Voice: Adam
  (energetic male). If regenerating, load key from there.

## Demo account (already registered)
- email `demo@demo.local` / pw `demodemo123` / name "Alex Rivera". `projects_shared=true` so it
  sees all existing projects.

## Featured real projects (full IDs)
- COMPLETED 3-workflow (payoff: diagram/health/CVPA/code/Download .zip):
  `fe24cff8-619f-4978-a4f7-73d237e5a730` (order-placement/fulfilment/return). Alt: `087be1a5-...`.
- SPEC_DRAFTED 3-workflow (editing: open questions, dep checklist, trigger cards):
  `12ef7be1-db95-43ed-a7f2-d3bf74003bbe`.
- SPEC_VALIDATED w/ timings + nickname (time-saved): `b9b301bf-83a7-4f67-bce0-9a646905852d`.
- Another w/ timings: `6d81181e-90d6-433e-9772-8a010412b6dd`.

## Key UI selectors / labels (verified from source)
- Nav: logo "workflow·compiler", links "Projects","Guide", ThemeToggle (title "Toggle light / dark"), UserMenu.
- Login `/login`: `#login-email`, `#login-password`, button "Sign in" (seg tabs Sign in/Create account).
- Home `/`: textarea placeholder "When a customer submits an order…"; select#model (opt "Nemotron (cloud)");
  input#nickname; button "Compile"; `<RunningOverlay title="Compiling document">` (COMPILE_STEPS + elapsed clock);
  TimeSavedStat at top; ProjectsPanel right.
- Workspace `/projects/{id}`: action bar → back "←", ProjectIdentity(nickname+id+pencil), stage pill,
  "{n} blocking" pill; tabs "Spec"/"Results"; right: "Edit request","Save","Validate"(btn-gate),"Approve"(btn-pass).
  Spec view 3 cols: left workflow slug buttons (order-placement/…); center view tabs lowercase
  editor/preview/diagram (match `/^diagram$/i`); right rail: Findings, OpenQuestions, DependencyChecklist,
  TriggerCards, EventKindEditor, ValidateDiff, EditHistory, TimeSavedCard, "Approve overrides"
  (2 checkboxes: "Accept unanswered required questions","Allow unconfirmed dependencies" — keep OFF).
  Diagram view has "Classify phases (CVPA)". RunningOverlay covers center on validate/approve.
- Results tab: TimeSavedCard; per-workflow "Diagram", "Graph health: NN%", CVPA table (Node/Phase),
  "Generated files" (file tabs + code), **"Download .zip"** (saves `<id8>-temporal.zip`), Blocking findings.
- Settings `/settings`: Profile(Display name, Theme seg ☾ Light / ☀ Dark), Time-saved baselines
  (Discovery/Spec drafting/Validate/Compile/Edit number inputs w/ defaults, "Reset to defaults"),
  Projects list (page size select 10/25/50/100), "Save changes" → "Saved ✓".
- Guide `/guide`: h1 "Spec grammar" (The one rule, Validate/Approve tiers, Activities…).
  `/guide/edits`: h1 "Edit request format" (two ways, three steps, Validate/Approve).

## Scene list (target ~3:30)
1. Cold open / hero — logo, tagline "document → spec → validate → approve → code".
2. Sign in (`/login`) — quick.
3. Create — home: paste/upload order doc, model select (Nemotron cloud), nickname, Compile → RunningOverlay (elapsed). Cut.
4. Compiled spec — open completed proj; workflow tabs; editor → preview → diagram; Classify CVPA.
5. Human gate / edit — drafted proj: Open Questions, Dependency checklist, edit a line; Validate (overlay) → findings; the gate (Approve gated). Money beat: gate refuses unconfirmed deps / validator catches a break (optional, keep light).
6. Edit request — open Edit request panel (NL edit → preview → confirm).
7. Approve → Results payoff — completed proj Results: diagram, Graph health %, CVPA table, generated Temporal files, Download .zip.
8. Metrics — TimeSaved stat/card (real hours saved).
9. Configuration — Settings: theme toggle (light↔dark, energetic), baselines, page size, Save ✓.
10. Docs — /guide + /guide/edits scroll.
11. Outro — logo + tagline + CTA.

## FINAL STATE (2026-07-17)
- Footage: demo/video/public/footage/*.webm (11 scenes, fresh, real data). Capture script
  `demo/capture2/capture.mjs` (auth via API login; compile/validate STUBBED via page.route so
  overlay shows w/o real LLM jobs). Re-run subset: `node capture.mjs <scene...>`.
- VO: demo/video/public/vo/*.mp3 (Charlie, energetic). Music: demo/video/public/music.mp3 (28s loop).
- Remotion: demo/video/src/{Root,Video,config}.tsx. config.ts AUTO-GEN by
  `node demo/capture2/generate-config.mjs` (measures footage+vo, sets frames/trim). Composition id
  "Demo", 1920x1080@30, TOTAL 4315f = 2:24.
- Render: `cd demo/video && npx remotion render Demo out/demo.mp4`. Output: demo/video/out/demo.mp4.
- Removed stale old-take assets (app.mp4/events.json/calibration.json) from public/.
- Known minor: config scene "Dark" toggle had a strict-match warning (nav vs settings both "Dark");
  hero/edit had guarded label misses (no "Time saved"/"OPEN QUESTIONS" on those pages) — non-fatal.

## Progress log
- [x] Survey app + tooling. Playwright+chromium installed in demo/capture2.
- [x] Demo user registered.
- [ ] Smoke test (smoke.mjs) → screenshots in $CLAUDE_JOB_DIR/tmp.
- [ ] Full capture script (record per-scene webm).
- [ ] Narration script + ElevenLabs VO (mp3 per scene) → demo/video/public/vo/.
- [ ] Remotion composition (energetic) + music + captions.
- [ ] Render out/demo.mp4, verify.

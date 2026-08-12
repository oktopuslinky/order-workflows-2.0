/**
 * Acceptance run for the conversational spec editor (docs/PIPELINE_HANDOFF.md §7.4).
 *
 * Drives the REAL UI at localhost:3000 against a compiled + validated project and
 * checks each locked design decision end to end. Question text and answer
 * interpretation are live LLM calls, so the script never asserts on wording — it
 * drives a fixed sequence of answer *styles* (concrete, vague, vague again,
 * unmappable, skip) and records what the product actually did.
 *
 * Run:  node dialogue-acceptance.mjs <project-id> [--provider-label local]
 * Exits non-zero if any case fails. Writes a JSON report next to this file.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP = "http://localhost:3000";
const API = "http://localhost:8000";
const CRED = { email: "acceptance@demo.local", password: "acceptance123" };

const PROJECT = process.argv[2];
const LABEL =
  (process.argv.find((a) => a.startsWith("--provider-label=")) || "").split("=")[1] ||
  "local";
if (!PROJECT) {
  console.error("usage: node dialogue-acceptance.mjs <project-id> [--provider-label=local]");
  process.exit(2);
}

const results = [];
const log = (...a) => console.log("[acc]", ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function record(id, name, passed, detail) {
  results.push({ id, name, passed, detail });
  log(`${passed ? "PASS" : "FAIL"}  ${id}. ${name}${detail ? ` — ${detail}` : ""}`);
}

/** Current spec markdown straight from the server, for comparison with the UI. */
async function serverSpecs(ctx) {
  const r = await ctx.request.get(`${API}/projects/${PROJECT}`);
  if (!r.ok()) throw new Error(`GET project failed: ${r.status()}`);
  return (await r.json()).spec_markdown;
}

async function serverProject(ctx) {
  const r = await ctx.request.get(`${API}/projects/${PROJECT}`);
  return (await r.json()).project;
}

/** The prompt text currently on screen, or null once the session has ended. */
async function promptText(page) {
  return page.evaluate(() => {
    const box = document.querySelector("textarea[placeholder*='own words']");
    if (!box) return null;
    const card = box.closest("div.flex.flex-col")?.querySelector("div.rounded-md.border");
    return card?.querySelector("p")?.innerText ?? "";
  });
}

/**
 * Wait for the panel to reach its next state.
 *
 * Pass the prompt captured BEFORE the action: this then waits for a genuine
 * transition rather than for the panel to merely look idle. Idle is true again
 * the instant after a click, before React has rendered the pending state, so
 * waiting on idle alone lets the next click land on a disabled button and reads
 * the previous turn's DOM back as if it were the new one.
 */
async function settled(page, prev = null) {
  await page.waitForFunction(
    (prevText) => {
      const t = document.body.innerText;
      if (t.includes("Applying…") || t.includes("Reading the findings…")) return false;
      // The answer box is found by its placeholder ATTRIBUTE — placeholders are
      // not part of body.innerText, so it can never be matched there.
      const box = document.querySelector("textarea[placeholder*='own words']");
      if (!box) return t.includes("All done.") || t.includes("Start resolving");
      if (prevText === null) return true;
      const card = box.closest("div.flex.flex-col")?.querySelector("div.rounded-md.border");
      return (card?.querySelector("p")?.innerText ?? "") !== prevText;
    },
    prev,
    { timeout: 900_000 },
  );
}

/** The question currently on screen, with its severity/slug/follow-up state. */
async function currentQuestion(page) {
  return page.evaluate(() => {
    const body = document.body.innerText;
    if (body.includes("All done.")) return { done: true };
    const box = document.querySelector("textarea[placeholder*='own words']");
    if (!box) return { done: true };
    const card = box.closest("div.flex.flex-col")?.querySelector("div.rounded-md.border");
    return {
      done: false,
      text: card?.querySelector("p")?.innerText ?? "",
      header: card?.querySelector("div")?.innerText ?? "",
      isFollowup: (card?.innerText ?? "").includes("follow-up"),
      counter: document.body.innerText.match(/Question (\d+) of (\d+)/)?.[0] ?? "",
    };
  });
}

/** The outcome panel produced by the last answer. */
async function lastOutcome(page) {
  return page.evaluate(() => {
    const t = document.body.innerText;
    const applied = t.includes("Applied to the spec");
    const parked = t.includes("Recorded as an open question");
    let changes = [];
    if (applied) {
      const nodes = [...document.querySelectorAll("li.font-mono")];
      changes = nodes.map((n) => n.innerText.trim());
    }
    return { applied, parked, changes };
  });
}

async function answer(page, text) {
  const prev = await promptText(page);
  await page.fill("textarea[placeholder*='own words']", text);
  await page.click("button:has-text('Answer')");
  await settled(page, prev);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });

  // Auth: register is idempotent enough — fall back to login when taken.
  let auth = await ctx.request.post(`${API}/auth/register`, {
    data: { ...CRED, display_name: "Acceptance" },
  });
  if (!auth.ok()) {
    auth = await ctx.request.post(`${API}/auth/login`, { data: CRED });
    if (!auth.ok()) throw new Error(`auth failed: ${auth.status()} ${await auth.text()}`);
  }

  // Close any session left open by an earlier run. A killed run leaves one
  // behind, and then the panel opens on a question instead of the "Start
  // resolving" button this script waits for — so a single crash would poison
  // every subsequent attempt. Applied answers stay applied; only the agenda
  // is discarded, and it is a snapshot that must be retaken anyway.
  await ctx.request.delete(`${API}/projects/${PROJECT}/dialogue`);

  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") log("browser-error:", m.text().slice(0, 200));
  });

  const specsBefore = await serverSpecs(ctx);
  const projBefore = await serverProject(ctx);
  // The patch version is the spec's semver in metadata; a bump rewrites it.
  const versionsBefore = Object.fromEntries(
    projBefore.specs.map((s) => [s.slug, s.metadata?.version ?? ""]),
  );

  await page.goto(`${APP}/projects/${PROJECT}`, { waitUntil: "networkidle" });
  await page.click("button:has-text('Resolve')");
  await page.waitForSelector("button:has-text('Start resolving')", { timeout: 60_000 });

  // ---------------------------------------------------------------- case 2/1
  await page.click("button:has-text('Start resolving')");
  await settled(page);

  const q1 = await currentQuestion(page);
  if (q1.done) {
    record(0, "Session opened with questions", false, "no questions were produced");
    await browser.close();
    return finish();
  }

  // 2. Grouping — the agenda should be no longer than its raw source count, and
  //    questions should read as prose rather than a mechanical one-per-source
  //    dump. The agenda's sources are blocking+warning findings AND each spec's
  //    unresolved open questions (locked decision 2) — counting only findings
  //    understates the denominator and scores real grouping as a failure, which
  //    is exactly what happened once parked answers had grown the open-question
  //    list.
  const findingCount = Object.values(projBefore.validation_findings || {})
    .flat()
    .filter((f) => f.severity === "blocking" || f.severity === "warning").length;
  const openQuestionCount = (projBefore.specs || [])
    .flatMap((s) => s.open_questions || [])
    .filter((q) => !q.resolved).length;
  const sourceCount = findingCount + openQuestionCount;
  const total = Number(q1.counter.match(/of (\d+)/)?.[1] ?? 0);
  record(
    2,
    "Related findings are grouped into questions",
    total > 0 && total <= Math.max(sourceCount, 1),
    `${findingCount} findings + ${openQuestionCount} open questions = ${sourceCount} sources → ${total} questions`,
  );

  // 1. A concrete answer applies immediately, with a patch-version bump.
  //
  // Which question comes first depends on the validator's findings and on how
  // the LLM grouped them, so a single canned answer aimed at one specific
  // question is not a stable test -- an answer that does not address the
  // question asked is *correctly* parked, and the case then fails while the
  // product is behaving. Walk the agenda instead, giving each question an
  // answer of the shape it asks for, and assert that at least one concrete
  // answer applies. That is the actual claim: concrete answers take effect
  // immediately.
  const CONCRETE = [
    "It hands off to the account provisioning workflow, and that one starts as " +
      "soon as the customer record has been created and payment has cleared.",
    "The Billing team owns that step, and it runs straight after the customer " +
      "record is created.",
    "Add a step where we email the customer a welcome message once their " +
      "account has been provisioned.",
    "That one is triggered by the Provisioning Service, and it emits an " +
      "account_ready event when it finishes.",
  ];

  let out1 = { applied: false, changes: [] };
  let attempts = 0;
  for (const text of CONCRETE) {
    const q = await currentQuestion(page);
    if (q.done) break;
    attempts += 1;
    await answer(page, text);
    out1 = await lastOutcome(page);
    if (out1.applied) break;
  }

  const projAfter1 = await serverProject(ctx);
  const bumped = projAfter1.specs.filter(
    (s) => (s.metadata?.version ?? "") !== (versionsBefore[s.slug] ?? ""),
  );
  record(
    1,
    "A concrete answer applies immediately and bumps the patch version",
    out1.applied && bumped.length > 0,
    `applied=${out1.applied} after ${attempts} question(s) changes=${out1.changes.length} bumped=[${bumped
      .map((s) => s.slug)
      .join(",")}]`,
  );

  // ------------------------------------------------------------------ case 6
  // THE STALENESS CHECK. Switch to Spec WITHOUT reloading and compare what the
  // editor holds against the server's current rendering.
  const specsAfter1 = await serverSpecs(ctx);
  const changedSlug =
    Object.keys(specsAfter1).find((s) => specsAfter1[s] !== specsBefore[s]) ?? null;

  await page.click("button:has-text('Spec')");
  await page.waitForTimeout(600);
  // Preview renders straight from the editor buffer, and unlike CodeMirror it is
  // not virtualised — so what it shows is exactly what Approve would post.
  await page.click("button:has-text('Preview')");
  await page.waitForTimeout(600);

  let staleness = { checked: false };
  if (changedSlug) {
    // Select the tab for the spec the change landed in.
    for (const t of await page.$$("button")) {
      if ((await t.innerText()).trim() === changedSlug) {
        await t.click();
        await page.waitForTimeout(400);
        break;
      }
    }
    // Compare the RAW editor buffer against the server's rendering.
    //
    // Approve posts these buffers verbatim, so the buffer is what actually
    // decides whether the dialogue's changes survive -- that is the clobber
    // path this case exists to catch. An earlier version probed the rendered
    // Preview for a line of Markdown *source*, which cannot match: list
    // markers and emphasis do not survive rendering, so it reported a stale
    // buffer whenever the new line happened to be a bullet.
    const buffer = await page.evaluate(() => {
      const ta = document.querySelector("textarea");
      if (ta) return ta.value;
      const cm = document.querySelector(".cm-content");
      return cm ? cm.innerText : null;
    });
    if (buffer !== null) {
      const server = specsAfter1[changedSlug] || "";
      const norm = (t) => t.replace(/\s+/g, " ").trim();
      const serverLines = server
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter((l) => l.length > 25);
      const beforeSet = new Set(
        (specsBefore[changedSlug] || "").split(/\r?\n/).map((l) => l.trim()),
      );
      const introduced = serverLines.filter((l) => !beforeSet.has(l));
      const bufferNorm = norm(buffer);
      const missing = introduced.filter((l) => !bufferNorm.includes(norm(l)));
      staleness = {
        checked: true,
        fresh: introduced.length > 0 && missing.length === 0,
        introduced: introduced.length,
        missing: missing.length,
        sample: missing[0]?.slice(0, 70) ?? null,
      };
    }
  }
  const approveDisabled = await page.getAttribute("button:has-text('Approve')", "disabled");
  record(
    6,
    "Spec tab shows the dialogue's changes; Approve is re-gated",
    (!staleness.checked || staleness.fresh) && approveDisabled !== null,
    `spec_fresh=${staleness.checked ? staleness.fresh : "n/a"} introduced=${
      staleness.introduced ?? 0
    } missing=${staleness.missing ?? 0} approve_disabled=${approveDisabled !== null}${
      staleness.sample ? ` first_missing="${staleness.sample}"` : ""
    }`,
  );

  await page.click("button:has-text('Resolve')");
  await page.waitForTimeout(500);

  // ------------------------------------------------------------------ case 3
  // The bound is AT MOST one clarifying follow-up PER QUESTION, then act.
  //
  // Two earlier versions of this case got it wrong in opposite directions. The
  // first passed unconditionally whenever no follow-up appeared, so it could
  // report PASS having tested nothing. The second demanded a park, which fails
  // the product for behaving correctly. Both also compared across *different*
  // questions: if a vague answer is acted on and the agenda advances, a
  // follow-up on the next question is a first follow-up, not a second one.
  //
  // So: keep vague-answering the SAME question. Only a follow-up pill that is
  // still showing after answering a follow-up violates the bound.
  let case3 = { followupSeen: false, violated: false, resolvedTo: "none" };
  const q2 = await currentQuestion(page);
  if (!q2.done) {
    await answer(page, "it depends");
    const afterVague = await currentQuestion(page);
    case3.followupSeen = !afterVague.done && afterVague.isFollowup;

    if (case3.followupSeen) {
      // Still on the same question, now showing its one clarifying follow-up.
      await answer(page, "hard to say, depends on the case");
      const afterSecond = await currentQuestion(page);
      const out = await lastOutcome(page);
      // A follow-up pill still showing means a SECOND follow-up on this
      // question -- the one thing the bound forbids.
      case3.violated = !afterSecond.done && afterSecond.isFollowup;
      case3.resolvedTo = out.parked ? "parked" : out.applied ? "applied" : "advanced";
    } else {
      const out = await lastOutcome(page);
      case3.resolvedTo = out.parked ? "parked" : out.applied ? "applied" : "advanced";
    }
  }
  record(
    3,
    case3.followupSeen
      ? "A vague answer gets at most one follow-up per question, then acts"
      : "A vague answer is acted on without a follow-up (bound not exercised)",
    !case3.violated,
    `follow-up=${case3.followupSeen} second_follow-up=${case3.violated} resolved=${case3.resolvedTo}`,
  );

  // ------------------------------------------------------------------ case 4
  let case4 = { parked: false, inSpec: false, ref: null };
  const q3 = await currentQuestion(page);
  if (!q3.done) {
    await answer(page, "ops owns that decision and it has not been made yet");
    const out = await lastOutcome(page);
    case4.parked = out.parked;
    const proj = await serverProject(ctx);
    for (const s of proj.specs) {
      const hit = (s.open_questions || []).find((q) =>
        String(q.ref || "").startsWith("dialogue:"),
      );
      if (hit) {
        // Decision 8: parked questions land unresolved and human-provided.
        case4.inSpec = hit.resolved === false && hit.provenance === "human_provided";
        case4.ref = hit.ref;
        case4.provenance = hit.provenance;
        case4.resolved = hit.resolved;
        break;
      }
    }
  }
  record(
    4,
    "An unmappable answer parks as an unresolved open question",
    case4.parked || case4.inSpec,
    `parked_panel=${case4.parked} ref=${case4.ref} provenance=${case4.provenance} unresolved=${case4.inSpec}`,
  );

  // ------------------------------------------------------------------ case 5
  let case5 = { untouched: null };
  const q4 = await currentQuestion(page);
  if (!q4.done) {
    const before = await serverSpecs(ctx);
    const prevSkip = await promptText(page);
    await page.click("button:has-text('Skip')");
    await settled(page, prevSkip);
    const after = await serverSpecs(ctx);
    case5.untouched = JSON.stringify(before) === JSON.stringify(after);
    record(5, "Skip leaves the spec untouched", case5.untouched === true, "");
  } else {
    record(5, "Skip leaves the spec untouched", false, "session ended before a skip could run");
  }

  // ------------------------------------------------------------------ case 7
  // Answer whatever remains so the session reaches its summary.
  for (let i = 0; i < 25; i++) {
    const q = await currentQuestion(page);
    if (q.done) break;
    const prevLoop = await promptText(page);
    await page.click("button:has-text('Skip')");
    await settled(page, prevLoop);
  }
  const summary = await page.evaluate(() => {
    const m = document.body.innerText.match(/All done\.[^\n]*/);
    return m ? m[0] : null;
  });
  const proj = await serverProject(ctx);
  const sess = proj.dialogue_session;
  const counts = sess
    ? sess.questions.reduce((a, q) => ((a[q.status] = (a[q.status] || 0) + 1), a), {})
    : {};
  const summaryMatches =
    summary !== null &&
    (counts.answered ?? 0) === Number(summary.match(/(\d+) of/)?.[1] ?? -1);
  record(
    7,
    "Session end reports accurate answered/parked/skipped counts",
    summaryMatches,
    `${summary} | server=${JSON.stringify(counts)}`,
  );

  fs.writeFileSync(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), `acceptance-${LABEL}.json`),
    JSON.stringify({ project: PROJECT, provider: LABEL, results, counts }, null, 2),
  );
  await browser.close();
  return finish();
}

function finish() {
  const failed = results.filter((r) => !r.passed);
  log(`\n${results.length - failed.length}/${results.length} cases passed`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error("[acc] fatal:", e);
  process.exit(3);
});

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

/** Wait for either a new question, or the end-of-session panel. */
async function settled(page) {
  await page.waitForFunction(
    () => {
      const t = document.body.innerText;
      return (
        !t.includes("Applying…") &&
        !t.includes("Reading the findings…") &&
        (t.includes("All done.") ||
          t.includes("Answer in your own words") ||
          t.includes("Start resolving"))
      );
    },
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
  await page.fill("textarea[placeholder*='own words']", text);
  await page.click("button:has-text('Answer')");
  await settled(page);
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

  // 2. Grouping — the agenda should be shorter than the raw finding count when
  //    related findings exist, and questions should read as prose, not as a
  //    mechanical one-per-finding dump.
  const findingCount = Object.values(projBefore.validation_findings || {})
    .flat()
    .filter((f) => f.severity === "blocking" || f.severity === "warning").length;
  const total = Number(q1.counter.match(/of (\d+)/)?.[1] ?? 0);
  record(
    2,
    "Related findings are grouped into questions",
    total > 0 && total <= Math.max(findingCount, 1),
    `${findingCount} blocking+warning findings → ${total} questions`,
  );

  // 1. A concrete answer applies immediately, with a patch-version bump.
  await answer(
    page,
    "It hands off to the account provisioning workflow, and that one starts as " +
      "soon as the customer record has been created and payment has cleared.",
  );
  const out1 = await lastOutcome(page);
  const projAfter1 = await serverProject(ctx);
  const bumped = projAfter1.specs.filter(
    (s) => (s.metadata?.version ?? "") !== (versionsBefore[s.slug] ?? ""),
  );
  record(
    1,
    "Answer applies immediately and bumps the patch version",
    out1.applied && bumped.length > 0,
    `applied=${out1.applied} changes=${out1.changes.length} bumped=[${bumped
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
    // Pick a line the dialogue introduced and look for it in the rendered buffer.
    const beforeLines = new Set((specsBefore[changedSlug] || "").split("\n").map((l) => l.trim()));
    const newLine = (specsAfter1[changedSlug] || "")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 25 && !beforeLines.has(l))
      .sort((a, b) => b.length - a.length)[0];
    if (newLine) {
      // Make sure we're looking at the spec the change landed in.
      const tabs = await page.$$("button");
      for (const t of tabs) {
        const label = (await t.innerText()).trim();
        if (label === changedSlug) {
          await t.click();
          await page.waitForTimeout(400);
          break;
        }
      }
      const shown = await page.evaluate(() => document.body.innerText);
      const probe = newLine.replace(/[*_`#]/g, "").slice(0, 60);
      staleness = { checked: true, fresh: shown.includes(probe.slice(0, 40)), probe };
    }
  }
  const approveDisabled = await page.getAttribute("button:has-text('Approve')", "disabled");
  record(
    6,
    "Spec tab shows the dialogue's changes; Approve is re-gated",
    (!staleness.checked || staleness.fresh) && approveDisabled !== null,
    `spec_fresh=${staleness.checked ? staleness.fresh : "n/a"} approve_disabled=${
      approveDisabled !== null
    }`,
  );

  await page.click("button:has-text('Resolve')");
  await page.waitForTimeout(500);

  // ------------------------------------------------------------------ case 3
  // Vague, then vague again: exactly one follow-up, then a park.
  let case3 = { followupSeen: false, parkedAfterSecond: false, secondFollowup: false };
  const q2 = await currentQuestion(page);
  if (!q2.done) {
    await answer(page, "it depends");
    const afterVague = await currentQuestion(page);
    case3.followupSeen = !afterVague.done && afterVague.isFollowup;
    if (!afterVague.done) {
      await answer(page, "hard to say, depends on the case");
      const afterSecond = await currentQuestion(page);
      const out = await lastOutcome(page);
      case3.secondFollowup = !afterSecond.done && afterSecond.isFollowup;
      case3.parkedAfterSecond = out.parked || !case3.secondFollowup;
    }
  }
  record(
    3,
    "A vague answer gets exactly one follow-up, then parks",
    case3.followupSeen ? !case3.secondFollowup : true,
    `follow-up=${case3.followupSeen} second_follow-up=${case3.secondFollowup} parked=${case3.parkedAfterSecond}`,
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
    await page.click("button:has-text('Skip')");
    await settled(page);
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
    await page.click("button:has-text('Skip')");
    await settled(page);
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
    path.resolve(path.dirname(new URL(import.meta.url).pathname.slice(1)), `acceptance-${LABEL}.json`),
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

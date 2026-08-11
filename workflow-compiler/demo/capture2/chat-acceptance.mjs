/**
 * Browser acceptance for the free-form spec chat (Resolve tab → Free-form).
 *
 * Companion to dialogue-acceptance.mjs. The engine's decisions are covered by
 * unit tests and were verified live against the API; what only a browser can
 * prove is the part that has burned us before: that an applied change reaches
 * the *editor buffers*, not just the server. A spec patched server-side while
 * the Spec tab still shows pre-change text is the clobber path — Approve posts
 * those buffers back and silently overwrites what the chat just did.
 *
 * Never asserts on LLM wording; only on disposition tags and observable state.
 *
 *   node chat-acceptance.mjs <project-id> [--provider-label=cloud]
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const API = "http://localhost:8000";
const APP = "http://localhost:3000";
const PROJECT = process.argv[2];
const LABEL = (process.argv.find((a) => a.startsWith("--provider-label=")) ?? "=local").split("=")[1];
const CRED = { email: "acceptance@demo.local", password: "acceptance123" };

if (!PROJECT) {
  console.error("usage: node chat-acceptance.mjs <project-id> [--provider-label=cloud]");
  process.exit(64);
}

const results = [];
const log = (m) => console.log(`[chat] ${m}`);
function record(id, name, passed, detail) {
  results.push({ id, name, passed, detail });
  log(`${passed ? "PASS" : "FAIL"}  ${id}. ${name}${detail ? ` — ${detail}` : ""}`);
}

/** Wait until the panel is idle again (no in-flight send). */
async function settled(page) {
  await page.waitForFunction(
    () => {
      const t = document.body.innerText;
      if (t.includes("Applying…") || t.includes("Working on it…")) return false;
      // The send box is identified by its placeholder ATTRIBUTE, which is not
      // part of innerText — query the DOM, never body text. (This exact mistake
      // cost an evening in dialogue-acceptance.mjs.)
      return !!document.querySelector("textarea[placeholder]");
    },
    null,
    { timeout: 900_000 },
  );
}

/** Every assistant turn's status tag, oldest first. */
const tags = (page) =>
  page.evaluate(
    (sel) => [...document.querySelectorAll(sel)].map((e) => e.innerText.trim()),
    "span.font-mono.font-bold",
  );

const TAG_SELECTOR = "span.font-mono.font-bold";

async function send(page, text) {
  // Wait for a NEW assistant turn, not merely for the panel to look idle.
  // "Idle" is true again the instant after the click, before React has even
  // rendered the pending state — so waiting on idle alone reads the DOM back
  // before the response lands and silently scores the previous turn.
  const before = (await tags(page)).length;
  const box = page.locator("textarea[placeholder]").last();
  await box.fill(text);
  await page.click("button:has-text('Send')");
  await page.waitForFunction(
    ({ sel, n }) => document.querySelectorAll(sel).length > n,
    { sel: TAG_SELECTOR, n: before },
    { timeout: 900_000 },
  );
  await settled(page);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });

  let auth = await ctx.request.post(`${API}/auth/register`, {
    data: { ...CRED, display_name: "Acceptance" },
  });
  if (!auth.ok()) {
    auth = await ctx.request.post(`${API}/auth/login`, { data: CRED });
    if (!auth.ok()) throw new Error(`auth failed: ${auth.status()}`);
  }
  // Start from an empty transcript so turn counts are meaningful.
  await ctx.request.delete(`${API}/projects/${PROJECT}/chat`);

  const projBefore = await (await ctx.request.get(`${API}/projects/${PROJECT}`)).json();
  const versionsBefore = Object.fromEntries(
    projBefore.project.specs.map((s) => [s.slug, s.metadata?.version ?? ""]),
  );

  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") log(`browser-error: ${m.text().slice(0, 160)}`);
  });

  await page.goto(`${APP}/projects/${PROJECT}`, { waitUntil: "networkidle" });
  await page.click("button:has-text('Resolve')");

  // ------------------------------------------------------------------ case 1
  await page.click("button:has-text('Free-form')");
  await page.waitForSelector("textarea[placeholder]", { timeout: 60_000 });
  const promptedEmpty = (await page.innerText("body")).includes("Try things like");
  record(1, "Free-form mode opens with no session and no validate needed", promptedEmpty);

  // ------------------------------------------------------------------ case 2
  await send(page, "add an activity that notifies the customer when the order is delayed");
  let seen = await tags(page);
  const applied = seen.includes("APPLIED");
  record(
    2,
    "A concrete instruction is applied to the spec",
    applied,
    `turn tags: ${JSON.stringify(seen)}`,
  );

  const projAfter = await (await ctx.request.get(`${API}/projects/${PROJECT}`)).json();
  const bumped = projAfter.project.specs
    .filter((s) => (s.metadata?.version ?? "") !== versionsBefore[s.slug])
    .map((s) => s.slug);
  record(
    3,
    "The applied change bumped the spec's patch version",
    bumped.length > 0,
    `bumped=[${bumped}]`,
  );

  // ------------------------------------------------------------------ case 4
  // The one thing only a browser can check: did the editor buffers adopt it?
  const serverSpec = projAfter.project.specs.find((s) => s.slug === bumped[0]);
  await page.click("button:has-text('Spec')");
  await page.waitForTimeout(800);
  const editorText = await page.evaluate(() => {
    const ta = document.querySelector("textarea");
    return ta ? ta.value : document.body.innerText;
  });
  // Compare on a token the change introduced rather than whole documents.
  const fresh = /delay/i.test(editorText);
  record(
    4,
    "Spec tab shows the chat's change (no stale-buffer clobber)",
    fresh,
    `editor mentions the new step: ${fresh}`,
  );

  const approve = page.locator("button:has-text('Approve')").first();
  const approveDisabled = (await approve.count()) === 0 || (await approve.isDisabled());
  record(
    5,
    "Approve is re-gated until validation runs again",
    approveDisabled,
    `approve_disabled=${approveDisabled}`,
  );

  // ------------------------------------------------------------------ case 6
  await page.click("button:has-text('Resolve')");
  await page.waitForSelector("textarea[placeholder]", { timeout: 30_000 });
  const persisted = (await tags(page)).includes("APPLIED");
  record(6, "The transcript survives leaving and returning to the tab", persisted);

  // ------------------------------------------------------------------ case 7
  const beforeVague = (await tags(page)).length;
  await send(page, "make the whole thing better somehow");
  seen = await tags(page);
  // The contract is "never guess", not "always ask". Asking one clarifying
  // question and parking it as an open question are BOTH correct dispositions
  // for a vague instruction — what must not happen is a silent invented change.
  const last = seen[seen.length - 1];
  record(
    7,
    "A vague instruction is questioned or parked — never silently applied",
    seen.length > beforeVague && (last === "QUESTION" || last === "PARKED"),
    `disposition: ${last}`,
  );

  const failed = results.filter((r) => !r.passed);
  log(`\n${results.length - failed.length}/${results.length} cases passed`);
  writeFileSync(
    `chat-acceptance-${LABEL}.json`,
    JSON.stringify({ project: PROJECT, provider: LABEL, results }, null, 2),
  );
  await browser.close();
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error(`[chat] fatal: ${e.message}`);
  process.exit(3);
});

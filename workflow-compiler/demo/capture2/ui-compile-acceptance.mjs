/**
 * Acceptance run for compiling **through the browser UI** (docs/PIPELINE_HANDOFF.md §4.2).
 *
 * This is the row that had never succeeded on any provider. Everything else in the
 * pipeline was proven at the API layer the UI calls, which is not the same claim:
 * the click path involves the provider <select>, the hidden file input, the
 * multipart upload, the pending overlay, and the post-compile redirect — none of
 * which an API-level test touches.
 *
 * Parameterised by document so the same proven harness also covers the
 * non-Markdown ingestion formats (§0 row 1), which differ only in the bytes
 * uploaded.
 *
 * Run:  node ui-compile-acceptance.mjs [--doc=../../examples/multi_workflow.md]
 *                                      [--provider=nemotron] [--expect-specs=2]
 *                                      [--label=md]
 * Exits non-zero if any case fails. Writes ui-compile-<label>.json next to this file.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = "http://localhost:3000";
const API = "http://localhost:8000";
const CRED = { email: "acceptance@demo.local", password: "acceptance123" };

const arg = (name, dflt) =>
  (process.argv.find((a) => a.startsWith(`--${name}=`)) || "").split("=")[1] || dflt;

const DOC = path.resolve(HERE, arg("doc", "../../examples/multi_workflow.md"));
const PROVIDER = arg("provider", "nemotron");
const EXPECT_SPECS = Number(arg("expect-specs", "2"));
const EXPECT_COMPS = Number(arg("expect-compensations", "0"));
const EXPECT_XREF = arg("expect-xref", "false") === "true";
const LABEL = arg("label", path.extname(DOC).replace(".", "") || "doc");
// A cloud compile of the 2-workflow reference doc has measured 149s–484s, and the
// NVIDIA API has been seen returning 504s that the retry layer rides out. Allow
// generous headroom: a false timeout here would look exactly like the failure this
// script exists to disprove.
const BUDGET_MS = Number(arg("budget-ms", "1500000"));

if (!fs.existsSync(DOC)) {
  console.error(`document not found: ${DOC}`);
  process.exit(2);
}

const results = [];
const log = (...a) => console.log("[ui]", ...a);
function record(id, name, passed, detail) {
  results.push({ id, name, passed, detail });
  log(`${passed ? "PASS" : "FAIL"}  ${id}. ${name}${detail ? ` — ${detail}` : ""}`);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 } });

  let auth = await ctx.request.post(`${API}/auth/register`, {
    data: { ...CRED, display_name: "Acceptance" },
  });
  if (!auth.ok()) {
    auth = await ctx.request.post(`${API}/auth/login`, { data: CRED });
    if (!auth.ok()) throw new Error(`auth failed: ${auth.status()} ${await auth.text()}`);
  }

  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
  });
  // Record the compile response status from the network, so a failed compile is
  // reported as the HTTP error it was rather than as a generic UI timeout.
  let compileStatus = null;
  page.on("response", (r) => {
    if (r.url().includes("/projects/compile")) compileStatus = r.status();
  });

  await page.goto(APP, { waitUntil: "networkidle" });

  // ------------------------------------------------------------------ case 1
  // The form accepts the document through the real (hidden) file input.
  await page.setInputFiles('input[type="file"]', DOC);
  const shown = await page
    .locator(`text=${path.basename(DOC)}`)
    .first()
    .isVisible()
    .catch(() => false);
  record(1, "File input accepts the document and the UI confirms it", shown, path.basename(DOC));

  // ------------------------------------------------------------------ case 2
  // The provider <select> is the routing the UI actually uses.
  await page.selectOption("select#provider", PROVIDER);
  const selected = await page.inputValue("select#provider");
  await page.fill("input#nickname", `UI ${LABEL} ${PROVIDER}`);
  record(2, "Provider select is set", selected === PROVIDER, `provider=${selected}`);

  // ------------------------------------------------------------------ case 3
  // The click itself. Success is the redirect to /projects/<id>, which only
  // happens in the mutation's onSuccess — so reaching it proves the whole
  // upload → compile → response path ran through the browser.
  const t0 = Date.now();
  await page.click("button:has-text('Compile')");

  const overlay = await page
    .locator("text=Compiling document")
    .first()
    .isVisible()
    .catch(() => false);

  let redirected = true;
  try {
    await page.waitForURL(/\/projects\/[0-9a-f-]{36}$/, { timeout: BUDGET_MS });
  } catch {
    redirected = false;
  }
  const elapsed = Math.round((Date.now() - t0) / 1000);

  if (!redirected) {
    // Surface the actual cause instead of just "timed out".
    const err = await page
      .locator("p.text-\\[var\\(--block\\)\\]")
      .first()
      .innerText()
      .catch(() => null);
    record(
      3,
      "Compile completes through the browser and redirects to the project",
      false,
      `no redirect after ${elapsed}s http=${compileStatus} ui_error=${err} overlay_seen=${overlay}`,
    );
    fs.writeFileSync(
      path.join(HERE, `ui-compile-${LABEL}.json`),
      JSON.stringify({ doc: DOC, provider: PROVIDER, results, elapsed }, null, 2),
    );
    await browser.close();
    return finish();
  }

  const projectId = page.url().split("/").pop();
  record(
    3,
    "Compile completes through the browser and redirects to the project",
    true,
    `${elapsed}s → ${projectId} (overlay_seen=${overlay} http=${compileStatus})`,
  );

  // ------------------------------------------------------------------ case 4
  // The compile produced real specs — a redirect alone would be satisfied by an
  // empty project. Check the substance via the API the page reads.
  const r = await ctx.request.get(`${API}/projects/${projectId}`);
  const body = await r.json();
  const proj = body.project;
  const specs = proj.specs || [];
  const md = body.spec_markdown || {};
  // Activities live at spec.facts.structure.activities — `spec.facts` is a wrapper
  // holding the flat fact list AND the id-linked structure. Reading spec.activities
  // yields undefined for every spec, which scores a perfectly good compile as empty.
  const structOf = (s) => s.facts?.structure || {};
  const emptySpecs = specs.filter(
    (s) => (structOf(s).activities || []).length === 0 || !(md[s.slug] || "").trim(),
  );
  const totalComps = specs.reduce((n, s) => n + (structOf(s).compensations || []).length, 0);
  record(
    4,
    "Specs were drafted with real content",
    specs.length >= EXPECT_SPECS && emptySpecs.length === 0,
    `stage=${proj.stage} specs=${specs.length}/${EXPECT_SPECS} ` +
      `[${specs
        .map((s) => {
          const st = structOf(s);
          return (
            `${s.slug}:${(st.activities || []).length}a/${(st.exceptions || []).length}x` +
            `/${(st.compensations || []).length}c`
          );
        })
        .join(", ")}] empty=${emptySpecs.length}`,
  );

  // ----------------------------------------------------------------- case 4b
  // Compensations and the cross-workflow dependency are the two fields the
  // handoff flags as most at risk of being silently dropped (§5). Assert them
  // only when the caller says the document contains them, so the harness stays
  // usable for documents that legitimately have neither.
  if (EXPECT_COMPS > 0 || EXPECT_XREF) {
    const xrefs = proj.cross_references || [];
    const ok = totalComps >= EXPECT_COMPS && (!EXPECT_XREF || xrefs.length > 0);
    record(
      41,
      "Compensations and cross-workflow dependencies survived extraction",
      ok,
      `compensations=${totalComps}/${EXPECT_COMPS} xrefs=${xrefs.length}` +
        (xrefs.length
          ? ` [${xrefs
              .map(
                (x) =>
                  `${x.source_workflow}.${x.output_field}→${x.target_workflow}.${x.input_field}` +
                  ` confirmed=${x.user_confirmed}`,
              )
              .join("; ")}]`
          : ""),
    );
  }

  // ------------------------------------------------------------------ case 5
  // The Spec tab renders those specs in the browser. This is the UI half of the
  // claim: the project page must actually show what was compiled.
  await page.waitForSelector("button:has-text('Spec')", { timeout: 60_000 });
  await page.click("button:has-text('Spec')");
  await page.waitForTimeout(1500);
  const slugsOnScreen = await page.evaluate((slugs) => {
    const t = document.body.innerText;
    return slugs.filter((s) => t.includes(s));
  }, specs.map((s) => s.slug));
  record(
    5,
    "Project page renders the compiled specs",
    slugsOnScreen.length === specs.length,
    `${slugsOnScreen.length}/${specs.length} slugs on screen`,
  );

  // The Spark model list 502s whenever the eGPU gateway is unreachable, and the UI
  // is *supposed* to degrade quietly when it does (§6.3.8) — that console line is
  // the handled path, not a defect. Filter it out rather than weakening the case.
  const realErrors = consoleErrors.filter((e) => !/502|Bad Gateway/i.test(e));
  record(
    6,
    "No unexpected browser console errors during the compile",
    realErrors.length === 0,
    realErrors.length
      ? realErrors.slice(0, 3).join(" | ")
      : `clean (${consoleErrors.length} benign Spark-probe 502s ignored)`,
  );

  fs.writeFileSync(
    path.join(HERE, `ui-compile-${LABEL}.json`),
    JSON.stringify(
      { doc: DOC, provider: PROVIDER, project: projectId, elapsed, results, consoleErrors },
      null,
      2,
    ),
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
  console.error("[ui] fatal:", e);
  process.exit(3);
});

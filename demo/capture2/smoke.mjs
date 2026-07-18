import { chromium } from "playwright";

const OUT = process.env.SHOT_DIR || ".";
const BASE = "http://localhost:3000";
const PROJ = {
  completed: "fe24cff8-619f-4978-a4f7-73d237e5a730",
  drafted: "12ef7be1-db95-43ed-a7f2-d3bf74003bbe",
  validated: "b9b301bf-83a7-4f67-bce0-9a646905852d",
};

const log = (...a) => console.log("[smoke]", ...a);

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
  deviceScaleFactor: 1.5,
});
const page = await ctx.newPage();
page.on("console", (m) => {
  if (m.type() === "error") log("PAGE ERR:", m.text().slice(0, 160));
});

async function shot(name) {
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  log("shot", name);
}

// --- login ---
await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.fill("#login-email", "demo@demo.local");
await page.fill("#login-password", "demodemo123");
await shot("01-login");
await page.locator('form').getByRole("button", { name: "Sign in" }).click();
await page.waitForURL(`${BASE}/`, { timeout: 15000 }).catch(() => {});
await page.waitForLoadState("networkidle").catch(() => {});
await shot("02-home");

// --- completed project: spec then results ---
await page.goto(`${BASE}/projects/${PROJ.completed}`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await shot("03-workspace-spec");
// diagram view
await page.getByRole("button", { name: /^diagram$/i }).click().catch((e) => log("no diagram btn", e.message));
await page.waitForTimeout(1800);
await shot("04-diagram");
// results tab
await page.getByRole("button", { name: "Results", exact: true }).click().catch((e) => log("no results btn", e.message));
await page.waitForTimeout(2000);
await shot("05-results");

// --- drafted project: editing widgets ---
await page.goto(`${BASE}/projects/${PROJ.drafted}`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await shot("06-drafted-editor");

// --- settings ---
await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await shot("07-settings");

// --- guide ---
await page.goto(`${BASE}/guide`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await shot("08-guide");
await page.goto(`${BASE}/guide/edits`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await shot("09-guide-edits");

// dump the visible button labels on the workspace for selector confidence
await page.goto(`${BASE}/projects/${PROJ.completed}`, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
const btns = await page.$$eval("button", (bs) =>
  bs.map((b) => (b.textContent || "").trim()).filter(Boolean).slice(0, 40),
);
log("workspace buttons:", JSON.stringify(btns));

await browser.close();
log("DONE");

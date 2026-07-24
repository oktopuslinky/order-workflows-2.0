import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

// Capture clean per-scene footage of the LIVE workflow-compiler app.
// Auth per context via API login (robust). Expensive compile/validate calls are
// STUBBED so the RunningOverlay shows without launching real LLM jobs (which
// saturate the backend). Payoff scenes use already-completed projects.

const APP = "http://localhost:3000";
const API = "http://localhost:8000";
const CRED = { email: "demo@demo.local", password: "demodemo123" };
const ROOT = path.resolve(".");
const FOOT = path.resolve(ROOT, "../video/public/footage");
const TMP = path.resolve(ROOT, "_vidtmp");
const VW = 1920, VH = 1200;

const PROJ = {
  completed: "fe24cff8-619f-4978-a4f7-73d237e5a730",
  drafted: "12ef7be1-db95-43ed-a7f2-d3bf74003bbe",
  timed: "b9b301bf-83a7-4f67-bce0-9a646905852d",
};

const ORDER_DOC = `Order Placement Workflow

When a customer submits an order, validate the shopping cart and reserve
inventory. Authorise the payment. If payment is declined, raise
PaymentDeclined and cancel the order. Otherwise create the order record and
trigger Order Fulfilment. If a return is requested, start Order Return.`;

fs.mkdirSync(FOOT, { recursive: true });
fs.mkdirSync(TMP, { recursive: true });
const log = (...a) => console.log("[cap]", ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ONLY = process.argv.slice(2); // optional: capture only named scenes

const CURSOR = `
(() => {
  const init = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div');
    c.id = '__cur';
    c.style.cssText = 'position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;transition:transform .5s cubic-bezier(.22,1,.36,1);will-change:transform;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));';
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2 L4 19 L8.5 14.5 L11.5 21.5 L14.5 20.2 L11.5 13.2 L18 13.2 Z" fill="#0b0b0c" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    window.__mv = (x, y) => { c.style.transform = 'translate(' + x + 'px,' + y + 'px)'; };
    window.__rip = (x, y) => {
      const r = document.createElement('div');
      r.style.cssText = 'position:fixed;left:' + (x-6) + 'px;top:' + (y-6) + 'px;width:12px;height:12px;border-radius:50%;background:rgba(45,212,191,.6);z-index:2147483646;pointer-events:none;transition:transform .45s ease-out,opacity .45s ease-out;';
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(5)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 500);
    };
  };
  if (document.readyState !== 'loading') init(); else document.addEventListener('DOMContentLoaded', init);
  window.__initCursor = init;
})();`;

async function newCtx(browser, { record = true, auth = true } = {}) {
  const ctx = await browser.newContext({
    viewport: { width: VW, height: VH },
    deviceScaleFactor: 1,
    recordVideo: record ? { dir: TMP, size: { width: VW, height: VH } } : undefined,
  });
  ctx.setDefaultTimeout(9000);
  await ctx.addInitScript(CURSOR);
  if (auth) {
    await ctx.request.post(`${API}/auth/login`, {
      data: CRED, headers: { "Content-Type": "application/json" },
    }).catch((e) => log("  api login err", String(e).slice(0, 80)));
  }
  const page = await ctx.newPage();
  return { ctx, page };
}

async function ensureCursor(page) {
  await page.evaluate(() => window.__initCursor && window.__initCursor()).catch(() => {});
  await page.evaluate(() => window.__mv && window.__mv(innerWidth / 2, innerHeight * 0.6)).catch(() => {});
}

async function gotoApp(page, url, ready) {
  await page.goto(url, { waitUntil: "domcontentloaded" }).catch(() => {});
  // wait for the authed shell (nav "Projects" link) so we skip the auth spinner
  await page.getByRole("link", { name: "Projects" }).first().waitFor({ state: "visible", timeout: 15000 }).catch(() => {});
  if (ready) await page.locator(ready).first().waitFor({ state: "visible", timeout: 15000 }).catch((e) => log("  ready wait miss", String(e).slice(0, 60)));
  await ensureCursor(page);
  await sleep(900);
}

async function moveTo(page, sel, opts = {}) {
  const loc = typeof sel === "string" ? page.locator(sel) : sel;
  const box = await loc.first().boundingBox({ timeout: 6000 }).catch(() => null);
  if (!box) { log("  !target missing", String(sel).slice(0, 50)); return null; }
  const x = box.x + box.width * (opts.px ?? 0.5);
  const y = box.y + box.height * (opts.py ?? 0.5);
  await page.evaluate(([x, y]) => window.__mv && window.__mv(x, y), [x, y]);
  await sleep(560);
  return { x, y, loc };
}

async function click(page, sel, opts = {}) {
  const r = await moveTo(page, sel, opts);
  if (!r) return false;
  await page.evaluate(([x, y]) => window.__rip && window.__rip(x, y), [r.x, r.y]);
  await sleep(120);
  await r.loc.click({ timeout: 6000 }).catch((e) => log("  click err", String(e).slice(0, 60)));
  await sleep(250);
  return true;
}

async function typeInto(page, sel, text, delay = 22) {
  const loc = page.locator(sel).first();
  await moveTo(page, loc);
  await loc.click({ timeout: 6000 }).catch(() => {});
  await loc.fill("").catch(() => {});
  await loc.type(text, { delay }).catch(() => {});
}

async function smoothScroll(page, toY, dur = 2200) {
  await page.evaluate(async ([toY, dur]) => {
    const el = document.scrollingElement || document.documentElement;
    const s = el.scrollTop, d = toY - s, t0 = performance.now();
    await new Promise((res) => {
      const step = (t) => {
        const k = Math.min(1, (t - t0) / dur);
        const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        el.scrollTop = s + d * e; k < 1 ? requestAnimationFrame(step) : res();
      };
      requestAnimationFrame(step);
    });
  }, [toY, dur]).catch(() => {});
}

async function scene(browser, name, fn, opts = {}) {
  if (ONLY.length && !ONLY.includes(name)) return;
  log("scene", name);
  const { ctx, page } = await newCtx(browser, opts);
  try { await fn(page, ctx); } catch (e) { log("  SCENE ERR", name, String(e).slice(0, 120)); }
  const vid = page.video();
  await ctx.close();
  if (vid) {
    const p = await vid.path();
    const dst = path.join(FOOT, name + ".webm");
    fs.renameSync(p, dst);
    log("  saved", dst, `(${(fs.statSync(dst).size / 1e6).toFixed(1)}MB)`);
  }
}

// ---------------------------------------------------------------------------
const browser = await chromium.launch({ headless: true });

// LOGIN (UI, for show) -------------------------------------------------------
await scene(browser, "login", async (page) => {
  await page.goto(`${APP}/login`, { waitUntil: "domcontentloaded" });
  await ensureCursor(page);
  await sleep(700);
  await typeInto(page, "#login-email", CRED.email, 32);
  await sleep(250);
  await typeInto(page, "#login-password", CRED.password, 32);
  await sleep(400);
  await click(page, "form >> role=button[name='Sign in']");
  await page.getByRole("link", { name: "Projects" }).first().waitFor({ timeout: 15000 }).catch(() => {});
  await sleep(1800);
}, { auth: false });

// HERO / HOME ----------------------------------------------------------------
await scene(browser, "hero", async (page) => {
  await gotoApp(page, `${APP}/`, "text=Turn a workflow doc");
  await sleep(1200);
  await moveTo(page, "text=Turn a workflow doc");
  await sleep(1400);
  await moveTo(page, "text=Time saved").catch(() => {});
  await sleep(1600);
});

// CREATE (stub compile so overlay shows, no real LLM job) --------------------
await scene(browser, "create", async (page) => {
  await gotoApp(page, `${APP}/`, "button:has-text('Compile')");
  // Stub the compile endpoints: leave the request hanging so RunningOverlay stays.
  await page.route("**/projects/compile**", async () => { /* never resolve */ });
  await sleep(500);
  await typeInto(page, "#nickname", "Orders pipeline", 28);
  await sleep(250);
  await typeInto(page, "textarea", ORDER_DOC, 7);
  await sleep(500);
  await moveTo(page, "#model");
  await sleep(800);
  await click(page, "button:has-text('Compile')");
  await sleep(7000); // hold the "Compiling document" overlay
});

// SPEC (completed project) ---------------------------------------------------
await scene(browser, "spec", async (page) => {
  await gotoApp(page, `${APP}/projects/${PROJ.completed}`, "button:has-text('Validate')");
  await sleep(900);
  await click(page, "aside >> role=button[name='order-fulfilment']");
  await sleep(1400);
  await click(page, "aside >> role=button[name='order-placement']");
  await sleep(1000);
  await click(page, "role=button[name=/^preview$/i]");
  await sleep(2000);
  await click(page, "role=button[name=/^diagram$/i]");
  await sleep(3200);
});

// EDIT (drafted project: widgets + edit a line; NO live validate) ------------
await scene(browser, "edit", async (page) => {
  await gotoApp(page, `${APP}/projects/${PROJ.drafted}`, "button:has-text('Validate')");
  await sleep(900);
  await moveTo(page, "text=OPEN QUESTIONS").catch(() => {});
  await sleep(1200);
  const cb = page.locator("aside input[type=checkbox]").first();
  if (await cb.count()) {
    const b = await cb.boundingBox().catch(() => null);
    if (b) { await page.evaluate(([x, y]) => window.__mv(x, y), [b.x + 8, b.y + 8]); await sleep(500); await page.evaluate(([x, y]) => window.__rip(x, y), [b.x + 8, b.y + 8]); await cb.click().catch(() => {}); }
    await sleep(1000);
  }
  await moveTo(page, "text=CROSS-WORKFLOW DEPENDENCIES").catch(() => {});
  await sleep(1400);
  await click(page, "role=button[name=/^editor$/i]").catch(() => {});
  const ed = page.locator(".cm-content").first();
  if (await ed.count()) {
    await moveTo(page, ed, { px: 0.25, py: 0.12 });
    await ed.click().catch(() => {});
    await page.keyboard.type("  # reviewed by Alex Rivera", { delay: 26 }).catch(() => {});
  }
  await sleep(1600);
  await moveTo(page, "button:has-text('Validate')");
  await sleep(1400);
});

// EDIT REQUEST panel ---------------------------------------------------------
await scene(browser, "editrequest", async (page) => {
  await gotoApp(page, `${APP}/projects/${PROJ.drafted}`, "button:has-text('Edit request')");
  await sleep(700);
  await click(page, "button:has-text('Edit request')");
  await sleep(1600);
  const ta = page.locator("textarea").first();
  if (await ta.count()) {
    await typeInto(page, "textarea",
      "## order-placement\n\nAdd a fraud check after payment authorisation. If an order is\nflagged, hold it for manual review before fulfilment.", 12);
    await sleep(1600);
  }
  await sleep(1200);
});

// RESULTS payoff (completed project) -----------------------------------------
await scene(browser, "results", async (page) => {
  await gotoApp(page, `${APP}/projects/${PROJ.completed}`, "button:has-text('Results')");
  await sleep(700);
  await click(page, "role=button[name='Results']");
  await sleep(2400);
  for (const w of ["order-fulfilment", "order-return", "order-placement"]) {
    await click(page, `button:has-text('${w}')`);
    await sleep(1600);
  }
  for (const f of ["workflow.py", "activities.py"]) {
    await click(page, `button:has-text('${f}')`);
    await sleep(1500);
  }
  await click(page, "button:has-text('Download .zip')");
  await sleep(1800);
});

// METRICS --------------------------------------------------------------------
await scene(browser, "metrics", async (page) => {
  await gotoApp(page, `${APP}/projects/${PROJ.timed}`, "button:has-text('Save')");
  await sleep(1000);
  await smoothScroll(page, 500, 1600);
  await moveTo(page, "text=Time saved").catch(() => {});
  await sleep(2800);
});

// CONFIG (settings) ----------------------------------------------------------
await scene(browser, "config", async (page) => {
  await gotoApp(page, `${APP}/settings`, "text=Time-saved baselines");
  await sleep(900);
  // Scope to the Settings "Theme" toggle group so we don't also match the nav toggle.
  const darkBtn = page.getByRole("group", { name: "Theme" }).getByRole("button", { name: /Dark/ });
  await click(page, darkBtn);
  await sleep(1800); // let the whole app flip to dark on-camera
  const compileInput = page.locator("input[type=number]").nth(3);
  if (await compileInput.count()) { await moveTo(page, compileInput); await compileInput.click().catch(() => {}); await compileInput.fill("20"); await sleep(700); }
  await smoothScroll(page, 520, 1200);
  await click(page, "button:has-text('Save changes')");
  await sleep(1600);
  await smoothScroll(page, 0, 900);
  await sleep(700);
});

// DOCS -----------------------------------------------------------------------
await scene(browser, "docs", async (page) => {
  await gotoApp(page, `${APP}/guide`, "text=Filling out a spec");
  await sleep(1000);
  await smoothScroll(page, 760, 2600);
  await sleep(700);
  await gotoApp(page, `${APP}/guide/edits`, "text=Writing an edit request");
  await sleep(900);
  await smoothScroll(page, 760, 2600);
  await sleep(900);
});

// OUTRO ----------------------------------------------------------------------
await scene(browser, "outro", async (page) => {
  await gotoApp(page, `${APP}/`, "text=Turn a workflow doc");
  await sleep(3000);
});

await browser.close();
log("ALL DONE");

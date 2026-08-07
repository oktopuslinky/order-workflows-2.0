/**
 * In-page instrumentation for the demo take. Injected once over CDP.
 *
 * CDP-dispatched clicks are *real* DOM events, so a capturing listener sees
 * everything the driver does -- no need to hand-log each action. Each event
 * records the target's viewport rect + a wall-clock timestamp; Remotion later
 * maps those to video pixels (via calibration.json) to fly the synthetic cursor.
 *
 * Buffered in sessionStorage so a hard navigation doesn't lose the take.
 */
(() => {
  const KEY = "__demoEvents";

  const load = () => {
    try {
      return JSON.parse(sessionStorage.getItem(KEY) || "[]");
    } catch {
      return [];
    }
  };
  const save = (evts) => sessionStorage.setItem(KEY, JSON.stringify(evts));

  if (window.__demoInstrumented) return "already-instrumented";
  window.__demoInstrumented = true;

  const push = (evt) => {
    const evts = load();
    evts.push(evt);
    save(evts);
  };

  const describe = (el) => {
    if (!el || !el.getBoundingClientRect) return null;
    const r = el.getBoundingClientRect();
    // Prefer the nearest meaningful control over a bare <span> inside a button.
    const label =
      (el.getAttribute && (el.getAttribute("aria-label") || el.getAttribute("title"))) ||
      (el.innerText || "").trim().slice(0, 60) ||
      el.tagName.toLowerCase();
    return {
      label,
      tag: el.tagName.toLowerCase(),
      rect: { x: r.x, y: r.y, w: r.width, h: r.height },
    };
  };

  document.addEventListener(
    "click",
    (e) => {
      const target = e.target.closest("button,a,input,select,label,[role=button],textarea") || e.target;
      push({ type: "click", t: Date.now(), url: location.pathname, ...describe(target) });
    },
    true, // capture phase: fires even if the app stops propagation
  );

  document.addEventListener(
    "change",
    (e) => {
      const t = e.target;
      push({
        type: "change",
        t: Date.now(),
        url: location.pathname,
        value: t.type === "checkbox" ? String(t.checked) : String(t.value || "").slice(0, 80),
        ...describe(t),
      });
    },
    true,
  );

  // Typing: one event per burst, not per keystroke -- the cursor only needs to
  // know *where* typing happened and for how long.
  let typingTimer = null;
  let typingStart = null;
  document.addEventListener(
    "input",
    (e) => {
      if (typingStart === null) typingStart = Date.now();
      const target = e.target;
      clearTimeout(typingTimer);
      typingTimer = setTimeout(() => {
        push({
          type: "type",
          t: typingStart,
          tEnd: Date.now(),
          url: location.pathname,
          ...describe(target),
        });
        typingStart = null;
      }, 600);
    },
    true,
  );

  /** Mark a named beat (scene boundary) from the driver. */
  window.__demoMark = (name, note) => {
    push({ type: "mark", t: Date.now(), name, note: note || "", url: location.pathname });
    return name;
  };

  /**
   * Clapperboard + calibration in one.
   *
   * Paints four distinctly-coloured squares at known viewport offsets and holds
   * them for `ms`. A frame grabbed during that window lets calibrate.py solve the
   * viewport -> video-pixel transform by *measuring* it, instead of guessing at
   * DPI scaling and browser chrome height.
   */
  window.__demoCalibrate = (ms = 700) => {
    const INSET = 40;
    const SIZE = 60;
    const corners = [
      { id: "tl", color: "#ff00ff", x: INSET, y: INSET },
      { id: "tr", color: "#00ffff", x: window.innerWidth - INSET - SIZE, y: INSET },
      { id: "bl", color: "#ffff00", x: INSET, y: window.innerHeight - INSET - SIZE },
      { id: "br", color: "#00ff00", x: window.innerWidth - INSET - SIZE, y: window.innerHeight - INSET - SIZE },
    ];

    const host = document.createElement("div");
    host.style.cssText = "position:fixed;inset:0;z-index:2147483647;pointer-events:none;";
    for (const c of corners) {
      const d = document.createElement("div");
      d.style.cssText = `position:absolute;left:${c.x}px;top:${c.y}px;width:${SIZE}px;height:${SIZE}px;background:${c.color};`;
      host.appendChild(d);
    }
    document.body.appendChild(host);

    const t = Date.now();
    setTimeout(() => host.remove(), ms);

    const markers = corners.map((c) => ({
      id: c.id,
      color: c.color,
      // centre of the square, in viewport CSS px
      cx: c.x + SIZE / 2,
      cy: c.y + SIZE / 2,
    }));

    push({
      type: "calibrate",
      t,
      tEnd: t + ms,
      markers,
      viewport: { w: window.innerWidth, h: window.innerHeight },
      dpr: window.devicePixelRatio,
    });

    return {
      t,
      ms,
      markers,
      viewport: { w: window.innerWidth, h: window.innerHeight },
      dpr: window.devicePixelRatio,
    };
  };

  /** Drain the buffer for export. */
  window.__demoDump = () => JSON.stringify(load());
  window.__demoReset = () => save([]);

  return "instrumented";
})();

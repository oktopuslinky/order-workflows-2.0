import React from "react";
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { SCENES, FPS, type SceneCfg } from "./config";

const ACCENT = "#2dd4bf";
const ACCENT2 = "#a78bfa";
const INK = "#f8fafc";

// ---- per-scene creative content --------------------------------------------
type Caption = { at: number; text: string; key?: string };
type Focus = { at: number; dur: number; scale: number; cx: number; cy: number };
type Ring = { at: number; dur: number; cx: number; cy: number; r: number }; // cx/cy/r in 0..1 of canvas
type Dir = "left" | "right";
type Creative = {
  num: string; label: string; captions: Caption[];
  focus?: Focus[]; rings?: Ring[]; dir?: Dir;
};

const C: Record<string, Creative> = {
  login: {
    num: "", label: "", dir: "left",
    captions: [{ at: 0.3, text: "Sign in — local account,", key: "no external services." }],
  },
  hero: {
    num: "01", label: "THE PROBLEM", dir: "right",
    captions: [
      { at: 0.2, text: "Workflows buried in", key: "documents" },
      { at: 2.4, text: "Turn them into", key: "runnable code" },
    ],
  },
  create: {
    num: "02", label: "CREATE", dir: "left",
    captions: [
      { at: 0.3, text: "Drop in a doc —", key: "Word, PDF, Markdown" },
      { at: 4.5, text: "Pick your model:", key: "Nemotron or local GPU" },
      { at: 9.5, text: "Hit compile — it reads &", key: "extracts every workflow" },
    ],
    focus: [{ at: 13.2, dur: 5, scale: 1.5, cx: 0.32, cy: 0.82 }],
    rings: [{ at: 12.4, dur: 3.2, cx: 0.405, cy: 0.70, r: 0.055 }],
  },
  spec: {
    num: "03", label: "THE SPEC", dir: "right",
    captions: [
      { at: 0.3, text: "One spec per workflow,", key: "grounded in your doc" },
      { at: 6, text: "Spec, preview, or", key: "live graph" },
      { at: 12, text: "The human gate:", key: "you decide" },
    ],
  },
  edit: {
    num: "04", label: "EDIT & VALIDATE", dir: "left",
    captions: [
      { at: 0.3, text: "Answer open questions,", key: "confirm dependencies" },
      { at: 6, text: "Edit any line," },
      { at: 9, text: "then Validate —", key: "issues in plain language" },
    ],
  },
  editrequest: {
    num: "05", label: "EDIT REQUESTS", dir: "right",
    captions: [
      { at: 0.3, text: "Bigger change?", key: "Just describe it" },
      { at: 5, text: "Plain English →", key: "precise spec edits" },
      { at: 10, text: "Previewed &", key: "logged" },
    ],
  },
  results: {
    num: "06", label: "RUNNABLE CODE", dir: "left",
    captions: [
      { at: 0.3, text: "Approve — the gate opens" },
      { at: 3.5, text: "Real Temporal code:", key: "activities, workers, tests" },
      { at: 10, text: "Graph, health score, phases —" },
      { at: 13.5, text: "then", key: "download the .zip" },
    ],
    focus: [{ at: 13.6, dur: 3.2, scale: 1.55, cx: 0.9, cy: 0.16 }],
    rings: [{ at: 13.2, dur: 3.0, cx: 0.9, cy: 0.16, r: 0.05 }],
  },
  metrics: {
    num: "07", label: "TIME SAVED", dir: "right",
    captions: [
      { at: 0.3, text: "It tracks what it", key: "saved you" },
      { at: 3.6, text: "Versus a human team —", key: "real hours back" },
    ],
  },
  config: {
    num: "08", label: "CONFIGURE", dir: "left",
    captions: [
      { at: 0.3, text: "Dark mode,", key: "your baselines" },
      { at: 4.2, text: "Tune it to", key: "your team" },
    ],
  },
  docs: {
    num: "09", label: "DOCS", dir: "right",
    captions: [{ at: 0.3, text: "Everything documented —", key: "in the app" }],
  },
  outro: { num: "", label: "", captions: [] },
};

// ---- animated background (blur-free, cheap) --------------------------------
const Background: React.FC = () => {
  const f = useCurrentFrame();
  const t = f / FPS;
  const g = (cx: number, cy: number, col: string, sp: number, ph: number, size = 55) => {
    const x = cx + Math.sin(t * sp + ph) * 6;
    const y = cy + Math.cos(t * sp * 0.8 + ph) * 5;
    return `radial-gradient(circle at ${x}% ${y}%, ${col} 0%, transparent ${size}%)`;
  };
  return (
    <AbsoluteFill style={{ background: "linear-gradient(135deg,#0a0f1e 0%,#141033 55%,#1b1145 100%)" }}>
      <AbsoluteFill style={{
        backgroundImage: [
          g(20, 25, "rgba(79,70,229,0.55)", 0.25, 0),
          g(85, 20, "rgba(13,148,136,0.45)", 0.30, 2),
          g(80, 85, "rgba(124,58,237,0.50)", 0.22, 4),
          g(15, 90, "rgba(219,39,119,0.40)", 0.28, 1),
        ].join(","),
      }} />
      <AbsoluteFill style={{
        backgroundImage: "radial-gradient(rgba(255,255,255,0.04) 1px, transparent 1px)",
        backgroundSize: "40px 40px", opacity: 0.5,
      }} />
    </AbsoluteFill>
  );
};

// ---- browser-framed footage (slide entrance + zoom) ------------------------
const AppFrame: React.FC<{ cfg: SceneCfg; creative: Creative }> = ({ cfg, creative }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;

  const pop = spring({ frame: f, fps, config: { damping: 200 }, durationInFrames: 20 });
  const dir = creative.dir === "right" ? 1 : -1;
  const enterX = interpolate(pop, [0, 1], [dir * 90, 0]);
  const enterScale = interpolate(pop, [0, 1], [0.955, 1]);
  const enterY = interpolate(pop, [0, 1], [22, 0]);

  const sceneSec = cfg.durationInFrames / fps;
  const rate = Math.max(0.6, Math.min(1, cfg.usableSec / sceneSec));

  let zScale = 1, ox = 50, oy = 50;
  for (const z of creative.focus ?? []) {
    if (t >= z.at && t <= z.at + z.dur) {
      const p = interpolate(t, [z.at, z.at + 0.6, z.at + z.dur - 0.6, z.at + z.dur],
        [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
      zScale = interpolate(p, [0, 1], [1, z.scale]);
      ox = z.cx * 100; oy = z.cy * 100;
    }
  }

  return (
    <div style={{
      position: "absolute", left: "50%", top: "48%",
      transform: `translate(-50%,-50%) translate(${enterX}px, ${enterY}px) scale(${enterScale})`,
      width: 1560, borderRadius: 18, overflow: "hidden",
      boxShadow: "0 40px 120px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.08)",
      background: "#0f172a",
    }}>
      <div style={{ height: 40, background: "#111827", display: "flex", alignItems: "center", gap: 8, padding: "0 16px" }}>
        {["#ef4444", "#eab308", "#22c55e"].map((c) => (
          <div key={c} style={{ width: 12, height: 12, borderRadius: "50%", background: c }} />
        ))}
        <div style={{
          marginLeft: 16, height: 22, flex: 1, maxWidth: 520, borderRadius: 11,
          background: "#1f2937", color: "#94a3b8", fontSize: 12, display: "flex",
          alignItems: "center", padding: "0 12px", fontFamily: "monospace",
        }}>localhost:3000 · workflow·compiler</div>
      </div>
      <div style={{ width: 1560, height: 975, overflow: "hidden", background: "#fff" }}>
        <div style={{ width: "100%", height: "100%", transform: `scale(${zScale})`, transformOrigin: `${ox}% ${oy}%` }}>
          <OffthreadVideo
            src={staticFile(`footage/${cfg.name}.mp4`)}
            trimBefore={cfg.trimFrames}
            playbackRate={rate}
            muted
            style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top center" }}
          />
        </div>
      </div>
    </div>
  );
};

// ---- callout rings ----------------------------------------------------------
const Rings: React.FC<{ rings?: Ring[] }> = ({ rings }) => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const t = f / FPS;
  if (!rings) return null;
  return (
    <>
      {rings.map((r, i) => {
        if (t < r.at || t > r.at + r.dur) return null;
        const local = t - r.at;
        const pulse = 1 + 0.16 * Math.sin(local * 7);
        const op = interpolate(local, [0, 0.3, r.dur - 0.4, r.dur], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        const cx = r.cx * width, cy = r.cy * height, rad = r.r * width * pulse;
        return (
          <svg key={i} width={width} height={height} style={{ position: "absolute", inset: 0, opacity: op }}>
            <circle cx={cx} cy={cy} r={rad} fill="none" stroke={ACCENT} strokeWidth={5} />
            <circle cx={cx} cy={cy} r={rad + 12} fill="none" stroke={ACCENT} strokeWidth={2} opacity={0.4} />
          </svg>
        );
      })}
    </>
  );
};

// ---- wipe sweep at scene start ---------------------------------------------
const WipeIn: React.FC<{ dir: Dir }> = ({ dir }) => {
  const f = useCurrentFrame();
  const { width } = useVideoConfig();
  if (f > 13) return null;
  const from = dir === "right" ? 1 : -1;
  const x = interpolate(f, [0, 12], [from * 0.15 * width, from * 1.5 * width], { extrapolateRight: "clamp" });
  const op = interpolate(f, [0, 8, 12], [0.9, 0.6, 0], { extrapolateRight: "clamp" });
  return (
    <div style={{
      position: "absolute", top: -80, bottom: -80, left: 0, width: width * 1.4,
      transform: `translateX(${x}px) skewX(-12deg)`, opacity: op,
      background: `linear-gradient(90deg, transparent, ${ACCENT2}, ${ACCENT}, transparent)`,
    }} />
  );
};

// ---- section label chip -----------------------------------------------------
const SectionLabel: React.FC<{ num: string; label: string }> = ({ num, label }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!label) return null;
  const s = spring({ frame: f, fps, config: { damping: 200 }, durationInFrames: 20 });
  const x = interpolate(s, [0, 1], [-60, 0]);
  const op = interpolate(f, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 70, top: 12, display: "flex", alignItems: "center", gap: 14, transform: `translateX(${x}px)`, opacity: op }}>
      {num && (
        <div style={{ fontSize: 22, fontWeight: 800, color: "#0a0f1e", background: ACCENT, borderRadius: 10, padding: "6px 12px", letterSpacing: 1 }}>{num}</div>
      )}
      <div style={{ fontSize: 26, fontWeight: 800, color: INK, letterSpacing: 3, textShadow: "0 2px 12px rgba(0,0,0,.5)" }}>{label}</div>
    </div>
  );
};

// ---- captions (per-word pop) ------------------------------------------------
const Captions: React.FC<{ items: Caption[]; sceneSec: number }> = ({ items, sceneSec }) => {
  const f = useCurrentFrame();
  const t = f / FPS;
  let idx = -1;
  for (let i = 0; i < items.length; i++) if (t >= items[i].at) idx = i;
  if (idx < 0) return null;
  const cur = items[idx];
  const start = cur.at;
  const end = idx + 1 < items.length ? items[idx + 1].at : sceneSec;
  const local = t - start;
  const outOp = interpolate(t, [end - 0.3, end], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  const textWords = cur.text.split(" ").map((w) => ({ w, key: false }));
  const keyWords = (cur.key ? cur.key.split(" ") : []).map((w) => ({ w, key: true }));
  const words = [...textWords, ...keyWords];

  const containerY = interpolate(local, [0, 0.3], [16, 0], { extrapolateRight: "clamp" });

  return (
    <div style={{
      position: "absolute", left: 0, right: 0, bottom: 104, display: "flex", justifyContent: "center",
      opacity: outOp, transform: `translateY(${containerY}px)`,
    }}>
      <div style={{
        display: "inline-block", maxWidth: 1200, textAlign: "center", fontSize: 40, fontWeight: 800,
        lineHeight: 1.22, padding: "12px 28px", borderRadius: 16,
        background: "rgba(8,12,24,0.74)", boxShadow: "0 12px 44px rgba(0,0,0,0.5)",
      }}>
        {words.map((word, i) => {
          const wStart = i * 0.045;
          const wp = interpolate(local, [wStart, wStart + 0.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          const wy = interpolate(wp, [0, 1], [14, 0]);
          return (
            <span key={i} style={{
              display: "inline-block", marginRight: 11, opacity: wp, transform: `translateY(${wy}px)`,
              color: word.key ? ACCENT : INK, textShadow: "0 3px 16px rgba(0,0,0,.7)",
            }}>{word.w}</span>
          );
        })}
      </div>
    </div>
  );
};

// ---- title cards ------------------------------------------------------------
const Kicker: React.FC<{ text: string }> = ({ text }) => (
  <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: 6, color: ACCENT, marginBottom: 20 }}>{text}</div>
);

const IntroCard: React.FC = () => {
  const f = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 200 }, durationInFrames: 26 });
  const y = interpolate(s, [0, 1], [40, 0]);
  const op = interpolate(f, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const outOp = interpolate(f, [durationInFrames - 14, durationInFrames], [1, 0], { extrapolateLeft: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: Math.min(op, outOp) }}>
      <div style={{ textAlign: "center", transform: `translateY(${y}px)`, padding: 60 }}>
        <Kicker text="WORKFLOW · COMPILER" />
        <div style={{ fontSize: 92, fontWeight: 850, color: INK, lineHeight: 1.05, letterSpacing: -2 }}>
          From a <span style={{ color: ACCENT2 }}>document</span><br />to <span style={{ color: ACCENT }}>runnable code</span>
        </div>
        <div style={{ marginTop: 30, fontSize: 26, color: "#cbd5e1", fontFamily: "monospace" }}>
          document → spec → validate → approve → code
        </div>
      </div>
    </AbsoluteFill>
  );
};

const OutroCard: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 200 }, durationInFrames: 26 });
  const sc = interpolate(s, [0, 1], [0.9, 1]);
  const op = interpolate(f, [0, 14], [0, 1], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: op }}>
      <div style={{ textAlign: "center", transform: `scale(${sc})` }}>
        <div style={{ fontSize: 84, fontWeight: 850, color: INK, letterSpacing: -1 }}>
          workflow<span style={{ color: ACCENT }}>·</span>compiler
        </div>
        <div style={{ marginTop: 22, fontSize: 30, color: "#cbd5e1" }}>A human in the loop, the whole way.</div>
        <div style={{
          marginTop: 40, display: "inline-block", fontSize: 22, fontWeight: 800, letterSpacing: 1,
          color: "#0a0f1e", background: ACCENT, borderRadius: 12, padding: "14px 28px",
        }}>Compile your first workflow →</div>
      </div>
    </AbsoluteFill>
  );
};

// ---- animated intro (floating workflow bubbles -> title) -------------------
const hexRgba = (hex: string, a: number) => {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
};

type Bubble = { label: string; x: number; y: number; r: number; c: string; d: number; hi?: boolean };
const BUBBLES: Bubble[] = [
  { label: "Order placement", x: 0.205, y: 0.30, r: 86, c: "#2dd4bf", d: 2, hi: true },
  { label: "Returns", x: 0.815, y: 0.25, r: 72, c: "#a78bfa", d: 10, hi: true },
  { label: "Fulfilment", x: 0.735, y: 0.72, r: 80, c: "#38bdf8", d: 6 },
  { label: "Approvals", x: 0.255, y: 0.74, r: 76, c: "#f472b6", d: 14, hi: true },
  { label: "Onboarding", x: 0.50, y: 0.16, r: 66, c: "#818cf8", d: 20 },
  { label: "Payments", x: 0.115, y: 0.54, r: 64, c: "#34d399", d: 26 },
  { label: "Subscriptions", x: 0.885, y: 0.55, r: 70, c: "#c084fc", d: 8 },
  { label: ".docx", x: 0.39, y: 0.85, r: 52, c: "#22d3ee", d: 17 },
  { label: ".pdf", x: 0.63, y: 0.88, r: 48, c: "#fb7185", d: 23 },
  { label: ".md", x: 0.50, y: 0.62, r: 50, c: "#5eead4", d: 30 },
];

const BubbleView: React.FC<{ b: Bubble; conv: number }> = ({ b, conv }) => {
  const f = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = f / fps;
  const appear = spring({ frame: f - b.d, fps, config: { damping: 200 }, durationInFrames: 26 });
  const driftX = Math.sin(t * 0.6 + b.d) * 20;
  const driftY = Math.cos(t * 0.5 + b.d * 1.3) * 16;
  // converge toward center + fade as title takes over
  const baseX = b.x * width, baseY = b.y * height;
  const cx = baseX + (width * 0.5 - baseX) * conv * 0.55;
  const cy = baseY + (height * 0.5 - baseY) * conv * 0.55;
  const op = appear * (1 - conv);
  const scale = interpolate(appear, [0, 1], [0.5, 1]) * (1 - 0.22 * conv);
  const rad = b.r;
  return (
    <div style={{
      position: "absolute", left: cx - rad + driftX, top: cy - rad + driftY,
      width: rad * 2, height: rad * 2, borderRadius: "50%",
      transform: `scale(${scale})`, opacity: op,
      background: `radial-gradient(circle at 34% 28%, ${hexRgba(b.c, 0.5)}, ${hexRgba(b.c, 0.10)} 70%)`,
      border: `1.5px solid ${hexRgba(b.c, 0.55)}`,
      boxShadow: `0 12px 44px ${hexRgba(b.c, 0.28)}, inset 0 1px 0 rgba(255,255,255,0.28)`,
      display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center",
    }}>
      <span style={{ color: INK, fontSize: b.r > 60 ? 21 : 16, fontWeight: 700, padding: "0 8px", letterSpacing: 0.2, textShadow: "0 2px 8px rgba(0,0,0,.5)" }}>{b.label}</span>
    </div>
  );
};

const IntroBubbles: React.FC = () => {
  const f = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = f / fps;

  // convergence 0->1 across ~7.6s..10s
  const conv = interpolate(t, [7.6, 10.0], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  // kicker top
  const kOp = interpolate(f, [4, 16], [0, 1], { extrapolateRight: "clamp" });

  // hook line (early)
  const hookIn = interpolate(t, [0.8, 1.5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const hookOut = interpolate(t, [6.6, 7.4], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const hookOp = Math.min(hookIn, hookOut);
  const hookY = interpolate(hookIn, [0, 1], [18, 0]);

  // title lockup (late)
  const titleS = spring({ frame: f - Math.round(9.7 * fps), fps, config: { damping: 200 }, durationInFrames: 30 });
  const titleOp = interpolate(t, [9.6, 10.3], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const titleY = interpolate(titleS, [0, 1], [46, 0]);

  // "Here's how" cue near the end
  const cueOp = interpolate(t, [12.6, 13.3, durationInFrames / fps - 0.2], [0, 1, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const cueBob = Math.sin(t * 3) * 5;

  return (
    <AbsoluteFill>
      {/* floating bubbles */}
      {BUBBLES.map((b) => <BubbleView key={b.label} b={b} conv={conv} />)}

      {/* kicker */}
      <div style={{ position: "absolute", top: 70, left: 0, right: 0, textAlign: "center", opacity: kOp }}>
        <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: 8, color: ACCENT }}>WORKFLOW · COMPILER</span>
      </div>

      {/* hook line */}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: hookOp }}>
        <div style={{ transform: `translateY(${hookY}px)`, textAlign: "center", background: "rgba(8,12,24,0.55)", borderRadius: 20, padding: "18px 40px" }}>
          <div style={{ fontSize: 58, fontWeight: 850, color: INK, letterSpacing: -1, lineHeight: 1.1 }}>
            Every workflow,<br />buried in a <span style={{ color: ACCENT2 }}>document</span>
          </div>
        </div>
      </AbsoluteFill>

      {/* title lockup */}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: titleOp }}>
        <div style={{ textAlign: "center", transform: `translateY(${titleY}px)` }}>
          <div style={{ fontSize: 86, fontWeight: 850, color: INK, lineHeight: 1.06, letterSpacing: -2 }}>
            From a <span style={{ color: ACCENT2 }}>document</span><br />to <span style={{ color: ACCENT }}>runnable code</span>
          </div>
          <div style={{ marginTop: 26, fontSize: 25, color: "#cbd5e1", fontFamily: "monospace" }}>
            document → spec → validate → approve → code
          </div>
          <div style={{ marginTop: 34, opacity: cueOp, transform: `translateY(${cueBob}px)`, fontSize: 20, fontWeight: 700, letterSpacing: 3, color: ACCENT }}>
            HERE&apos;S HOW ↓
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---- one scene --------------------------------------------------------------
const Scene: React.FC<{ cfg: SceneCfg }> = ({ cfg }) => {
  const { fps } = useVideoConfig();
  const creative = C[cfg.name] ?? { num: "", label: "", captions: [] };
  const sceneSec = cfg.durationInFrames / fps;
  const isIntro = cfg.name === "hero";
  const isOutro = cfg.name === "outro";
  if (isIntro) {
    return (
      <AbsoluteFill>
        <IntroBubbles />
        <Audio src={staticFile(`vo/${cfg.vo}.mp3`)} />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill>
      <AppFrame cfg={cfg} creative={creative} />
      <Rings rings={creative.rings} />
      <WipeIn dir={creative.dir ?? "left"} />
      {isIntro && (
        <Sequence durationInFrames={Math.round(2.2 * fps)}>
          <AbsoluteFill style={{ background: "rgba(10,15,30,0.72)" }} />
          <IntroCard />
        </Sequence>
      )}
      {isOutro && (
        <>
          <AbsoluteFill style={{ background: "rgba(10,15,30,0.82)" }} />
          <OutroCard />
        </>
      )}
      {!isOutro && <SectionLabel num={creative.num} label={creative.label} />}
      {!isOutro && <Captions items={creative.captions} sceneSec={sceneSec} />}
      <Audio src={staticFile(`vo/${cfg.vo}.mp3`)} />
    </AbsoluteFill>
  );
};

// ---- progress bar (global) --------------------------------------------------
const ProgressBar: React.FC<{ scenes: SceneCfg[] }> = ({ scenes }) => {
  const f = useCurrentFrame();
  const { durationInFrames, width } = useVideoConfig();
  const p = Math.min(1, f / durationInFrames);
  let acc = 0;
  const ticks = scenes.slice(0, -1).map((s) => { acc += s.durationInFrames; return acc / durationInFrames; });
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 6, background: "rgba(255,255,255,0.08)" }}>
      <div style={{ height: "100%", width: `${p * 100}%`, background: `linear-gradient(90deg, ${ACCENT2}, ${ACCENT})` }} />
      {ticks.map((tk, i) => (
        <div key={i} style={{ position: "absolute", top: 0, bottom: 0, left: `${tk * 100}%`, width: 2, background: "rgba(255,255,255,0.22)" }} />
      ))}
      <div style={{ position: "absolute", top: -2, left: `calc(${p * 100}% - 5px)`, width: 10, height: 10, borderRadius: "50%", background: ACCENT, boxShadow: `0 0 10px ${ACCENT}` }} />
    </div>
  );
};

// ---- root video -------------------------------------------------------------
export const DemoVideo: React.FC<{ only?: string[] }> = ({ only }) => {
  const scenes = only ? SCENES.filter((s) => only.includes(s.name)) : SCENES;
  let cursor = 0;
  return (
    <AbsoluteFill style={{ background: "#0a0f1e" }}>
      <Background />
      <Audio src={staticFile("music.mp3")} volume={0.14} loop />
      {scenes.map((cfg) => {
        const from = cursor;
        cursor += cfg.durationInFrames;
        return (
          <Sequence key={cfg.name} from={from} durationInFrames={cfg.durationInFrames} name={cfg.name}>
            <Scene cfg={cfg} />
          </Sequence>
        );
      })}
      <ProgressBar scenes={scenes} />
    </AbsoluteFill>
  );
};

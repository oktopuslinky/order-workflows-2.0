/**
 * Overlay furniture: callouts that point at real UI, title cards between acts,
 * and the wait clock.
 *
 * Type sizes follow the Remotion layout rules (headline >= 84px, supporting
 * >= 44px, labels >= 32px at 1080p) and stay inside an 80px side / 100px
 * top-bottom safe area.
 */

import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";

import { type Calibration, type Rect, rectToCanvas } from "../lib/take";

const FONT =
  '"Inter", "Segoe UI", system-ui, -apple-system, sans-serif';

/** Fade+rise in, fade out. Scene-local frames. */
const useReveal = (from: number, to: number, ease = 12) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [from, from + ease, to - ease, to], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
};

/**
 * A box drawn around a real element, with a label. Takes the element's viewport
 * rect straight from events.json, so it lands on the actual pixels.
 */
export const Callout: React.FC<{
  cal: Calibration;
  rect: Rect;
  text: string;
  from: number;
  to: number;
  /** Which side of the box the label sits on. */
  side?: "top" | "bottom" | "left" | "right";
  tone?: "info" | "warn" | "good";
}> = ({ cal, rect, text, from, to, side = "bottom", tone = "info" }) => {
  const o = useReveal(from, to);
  if (o <= 0.001) return null;

  const r = rectToCanvas(rect, cal);
  const colors = {
    info: { line: "#60a5fa", bg: "#1e3a8a", fg: "#eff6ff" },
    warn: { line: "#fbbf24", bg: "#78350f", fg: "#fffbeb" },
    good: { line: "#34d399", bg: "#065f46", fg: "#ecfdf5" },
  }[tone];

  const PAD = 10;
  const box = {
    left: r.x - PAD,
    top: r.y - PAD,
    width: r.w + PAD * 2,
    height: r.h + PAD * 2,
  };

  const labelPos: React.CSSProperties =
    side === "bottom"
      ? { left: box.left, top: box.top + box.height + 14 }
      : side === "top"
        ? { left: box.left, top: box.top - 62 }
        : side === "right"
          ? { left: box.left + box.width + 14, top: box.top }
          : { left: box.left - 14, top: box.top, translate: "-100% 0" };

  return (
    <>
      <div
        style={{
          position: "absolute",
          ...box,
          border: `3px solid ${colors.line}`,
          borderRadius: 8,
          boxShadow: `0 0 0 9999px rgba(2,6,23,${0.45 * o})`,
          opacity: o,
          zIndex: 30,
        }}
      />
      <div
        style={{
          position: "absolute",
          ...labelPos,
          zIndex: 31,
          opacity: o,
          translate: `${(labelPos.translate as string) ?? "0 0"}`,
        }}
      >
        <div
          style={{
            fontFamily: FONT,
            fontSize: 34,
            fontWeight: 600,
            color: colors.fg,
            background: colors.bg,
            border: `2px solid ${colors.line}`,
            padding: "10px 18px",
            borderRadius: 8,
            whiteSpace: "nowrap",
            translate: `0 ${interpolate(o, [0, 1], [8, 0])}px`,
          }}
        >
          {text}
        </div>
      </div>
    </>
  );
};

/** Full-frame act card. */
export const TitleCard: React.FC<{
  kicker?: string;
  title: string;
  sub?: string;
  durationInFrames: number;
}> = ({ kicker, title, sub, durationInFrames }) => {
  const frame = useCurrentFrame();
  const o = useReveal(0, durationInFrames, 14);
  const rise = interpolate(frame, [0, 24], [22, 0], {
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.2, 0, 0.1, 1),
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0b0f17",
        justifyContent: "center",
        padding: "100px 80px",
        opacity: o,
      }}
    >
      <div style={{ translate: `0 ${rise}px` }}>
        {kicker && (
          <div
            style={{
              fontFamily: FONT,
              fontSize: 34,
              fontWeight: 600,
              letterSpacing: 3,
              textTransform: "uppercase",
              color: "#60a5fa",
              marginBottom: 22,
            }}
          >
            {kicker}
          </div>
        )}
        <div
          style={{
            fontFamily: FONT,
            fontSize: 92,
            fontWeight: 700,
            lineHeight: 1.05,
            color: "#f8fafc",
            maxWidth: 1500,
          }}
        >
          {title}
        </div>
        {sub && (
          <div
            style={{
              fontFamily: FONT,
              fontSize: 46,
              fontWeight: 400,
              color: "#94a3b8",
              marginTop: 28,
              maxWidth: 1400,
              lineHeight: 1.35,
            }}
          >
            {sub}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

/**
 * The wait clock.
 *
 * The LLM waits are minutes long and we speed the footage up to get through
 * them. That compression is stated on screen rather than hidden: the clock
 * counts *real* elapsed seconds, and the badge says how fast we're running.
 */
export const WaitClock: React.FC<{
  /** True wall-clock seconds this wait took. */
  realSeconds: number;
  durationInFrames: number;
  speed: number;
  label?: string;
}> = ({ realSeconds, durationInFrames, speed, label = "compiling" }) => {
  const frame = useCurrentFrame();
  const elapsed = interpolate(frame, [0, durationInFrames], [0, realSeconds], {
    extrapolateRight: "clamp",
  });
  const mm = Math.floor(elapsed / 60);
  const ss = Math.floor(elapsed % 60);

  return (
    <div
      style={{
        position: "absolute",
        right: 80,
        top: 100,
        zIndex: 60,
        display: "flex",
        alignItems: "center",
        gap: 14,
        fontFamily: FONT,
      }}
    >
      <div
        style={{
          background: "rgba(2,6,23,0.85)",
          border: "2px solid #334155",
          borderRadius: 10,
          padding: "12px 20px",
          color: "#e2e8f0",
          fontSize: 36,
          fontWeight: 600,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {label} {mm}:{String(ss).padStart(2, "0")}
      </div>
      <div
        style={{
          background: "#1e3a8a",
          border: "2px solid #60a5fa",
          borderRadius: 10,
          padding: "12px 18px",
          color: "#eff6ff",
          fontSize: 32,
          fontWeight: 600,
        }}
      >
        {speed}x
      </div>
    </div>
  );
};

/** Lower-third caption -- carries the narration beat when there's no VO yet. */
export const Caption: React.FC<{ text: string; from: number; to: number }> = ({
  text,
  from,
  to,
}) => {
  const o = useReveal(from, to, 10);
  if (o <= 0.001) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        right: 80,
        bottom: 100,
        zIndex: 60,
        opacity: o,
        display: "flex",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          fontFamily: FONT,
          fontSize: 44,
          fontWeight: 500,
          color: "#f8fafc",
          background: "rgba(2,6,23,0.88)",
          border: "1px solid #334155",
          borderRadius: 12,
          padding: "18px 30px",
          textAlign: "center",
          maxWidth: 1500,
        }}
      >
        {text}
      </div>
    </div>
  );
};

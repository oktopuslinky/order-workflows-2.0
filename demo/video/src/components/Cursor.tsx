/**
 * The synthetic cursor.
 *
 * CDP-dispatched clicks are real to the app but invisible on screen -- the OS
 * pointer never moves. So we draw one, driven by the *actual* elements the
 * driver hit (events.json) at the *actual* times it hit them. The motion is
 * synthesised; the targets and timing are not.
 *
 * Between two clicks the cursor eases from one to the next, arriving shortly
 * before the click lands (a real hand doesn't teleport on the frame it clicks),
 * then punches down on contact.
 */

import React from "react";
import { interpolate, Easing, useCurrentFrame } from "remotion";

import {
  type Calibration,
  type TakeEvent,
  centreOf,
  epochToFrame,
  pointerEvents,
  toCanvas,
} from "../lib/take";

/** Frames spent travelling to a target before the click registers. */
const TRAVEL = 18;
/** Frames the click ripple lives for. */
const RIPPLE = 14;

export const Cursor: React.FC<{
  events: TakeEvent[];
  cal: Calibration;
  /** Frame offset of this scene within the recording. */
  startFrame: number;
}> = ({ events, cal, startFrame }) => {
  const frame = useCurrentFrame() + startFrame;

  const pts = React.useMemo(
    () =>
      pointerEvents(events).map((e) => {
        const c = centreOf(e.rect!);
        const p = toCanvas(c.x, c.y, cal);
        return { ...p, at: epochToFrame(e.t, cal), type: e.type, label: e.label };
      }),
    [events, cal],
  );

  if (pts.length === 0) return null;

  // Which hop are we on? The cursor is *arriving at* the next target.
  const nextIdx = pts.findIndex((p) => p.at > frame - 1);
  const target = nextIdx === -1 ? pts[pts.length - 1] : pts[nextIdx];
  const prev = nextIdx <= 0 ? pts[0] : pts[nextIdx - 1];

  // Travel window: end at the click, start TRAVEL frames earlier -- but never
  // before the previous click, or the cursor would rewind.
  const arriveAt = target.at;
  const departAt = Math.max(prev.at, arriveAt - TRAVEL);

  const t =
    arriveAt === departAt
      ? 1
      : interpolate(frame, [departAt, arriveAt], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.33, 0, 0.15, 1), // ease-out: fast away, settle in
        });

  const x = interpolate(t, [0, 1], [prev.x, target.x]);
  const y = interpolate(t, [0, 1], [prev.y, target.y]);

  // Click punch: brief scale-down at the moment of contact.
  const sinceClick = frame - arriveAt;
  const punch =
    sinceClick >= 0 && sinceClick < 8
      ? interpolate(sinceClick, [0, 3, 8], [0.72, 1.06, 1], { extrapolateRight: "clamp" })
      : 1;

  // Ripple on the most recent click that has already landed.
  const landed = [...pts].reverse().find((p) => p.at <= frame && frame - p.at < RIPPLE);
  const rippleAge = landed ? frame - landed.at : -1;

  return (
    <>
      {landed && rippleAge >= 0 && (
        <div
          style={{
            position: "absolute",
            left: landed.x,
            top: landed.y,
            width: 0,
            height: 0,
            zIndex: 40,
          }}
        >
          <div
            style={{
              position: "absolute",
              left: "-50%",
              top: "-50%",
              width: interpolate(rippleAge, [0, RIPPLE], [10, 86]),
              height: interpolate(rippleAge, [0, RIPPLE], [10, 86]),
              translate: "-50% -50%",
              borderRadius: "50%",
              border: "3px solid rgba(96,165,250,0.9)",
              opacity: interpolate(rippleAge, [0, RIPPLE], [0.85, 0]),
            }}
          />
        </div>
      )}

      <div
        style={{
          position: "absolute",
          left: x,
          top: y,
          zIndex: 50,
          scale: String(punch),
          filter: "drop-shadow(0 3px 6px rgba(0,0,0,0.45))",
          pointerEvents: "none",
        }}
      >
        {/* macOS-ish arrow, drawn so it points *at* (x, y). */}
        <svg width="34" height="34" viewBox="0 0 24 24" style={{ display: "block" }}>
          <path
            d="M4 2 L4 19 L8.5 14.8 L11.4 21.4 L14.3 20.1 L11.5 13.7 L17.6 13.3 Z"
            fill="#fff"
            stroke="#111"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </>
  );
};

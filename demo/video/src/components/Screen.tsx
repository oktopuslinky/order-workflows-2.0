/**
 * The recorded screen: raw desktop footage, cropped to the browser viewport and
 * fitted to the canvas, with an optional zoom onto a region of interest.
 *
 * Zoom/Ken-Burns isn't covered by any Remotion skill, so it's built here from
 * the primitives the rules do mandate: interpolate() on `scale`/`translate`,
 * never a CSS transition.
 *
 * `speed` drives playbackRate for the long LLM waits. The wait is real and we
 * don't hide it -- the WaitClock overlay keeps showing true elapsed time.
 */

import React from "react";
import { Video } from "@remotion/media";
import { AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame } from "remotion";

import { CANVAS, type Calibration, type Rect, fitViewport, rectToCanvas } from "../lib/take";

export type Focus = {
  /** Region of interest, in viewport px. */
  rect: Rect;
  /** Scene-local frames. */
  from: number;
  to: number;
  /** How tight to zoom. 1 = no zoom. */
  scale?: number;
  /** Frames spent easing in / out of the zoom. */
  ease?: number;
};

export const Screen: React.FC<{
  cal: Calibration;
  /** Frame in the recording where this scene starts. */
  startFrame: number;
  /** Playback speed of the underlying footage. */
  speed?: number;
  focus?: Focus;
  children?: React.ReactNode;
}> = ({ cal, startFrame, speed = 1, focus, children }) => {
  const frame = useCurrentFrame();
  const fit = fitViewport(cal);

  // --- zoom -------------------------------------------------------------
  let zoom = 1;
  let panX = 0;
  let panY = 0;

  if (focus) {
    const ease = focus.ease ?? 20;
    const target = focus.scale ?? 1.6;

    const amount = interpolate(
      frame,
      [focus.from, focus.from + ease, focus.to - ease, focus.to],
      [0, 1, 1, 0],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.bezier(0.4, 0, 0.2, 1),
      },
    );

    zoom = interpolate(amount, [0, 1], [1, target]);

    // Pan so the focus rect's centre sits at the canvas centre once zoomed.
    const r = rectToCanvas(focus.rect, cal);
    const cx = r.x + r.w / 2;
    const cy = r.y + r.h / 2;
    const fullPanX = (CANVAS.w / 2 - cx) * target;
    const fullPanY = (CANVAS.h / 2 - cy) * target;
    panX = interpolate(amount, [0, 1], [0, fullPanX]);
    panY = interpolate(amount, [0, 1], [0, fullPanY]);
  }

  return (
    <AbsoluteFill style={{ backgroundColor: "#0b0f17", overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          // Order matters: translate the zoomed content, then scale about origin.
          translate: `${panX}px ${panY}px`,
          scale: String(zoom),
          transformOrigin: "0 0",
        }}
      >
        {/* The raw desktop recording, positioned so the browser viewport lands
            centred on the canvas. Trim by props -- never re-encode. */}
        <Video
          src={staticFile(cal.video)}
          trimBefore={startFrame}
          playbackRate={speed}
          muted
          style={{
            position: "absolute",
            left: fit.left,
            top: fit.top,
            width: cal.videoSize.w * fit.scale,
            height: cal.videoSize.h * fit.scale,
          }}
        />
        {/* Cursor + callouts live in the same zoomed space, so they track the
            pixels they point at. */}
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

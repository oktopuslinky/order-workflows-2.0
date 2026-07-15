import "./index.css";

import React from "react";
import { Composition, staticFile } from "remotion";

import { Demo, demoDuration } from "./Demo";
import { CANVAS, FPS } from "./lib/take";

/**
 * Two compositions off the same edit:
 *
 *   Rough — scene names + timecodes burned into the frame. The review cut: it
 *           tells you which scene a problem is in without counting frames.
 *   Final — the same edit, clean. The deliverable.
 *
 * There is no narration by design, so both are silent and the captions carry the
 * argument. (An earlier cut laid public/voiceover.mp3 over Final; that file was
 * never recorded, and Final failed to resolve it.)
 *
 * Duration comes from the take via calculateMetadata, never a hard-coded number,
 * so the composition cannot drift out of sync with the footage.
 */

const calculateMetadata = async () => {
  const [events, cal] = await Promise.all([
    fetch(staticFile("events.json")).then((r) => r.json()),
    fetch(staticFile("calibration.json")).then((r) => r.json()),
  ]);
  return {
    durationInFrames: demoDuration({ events, cal }),
    fps: FPS,
    width: CANVAS.w,
    height: CANVAS.h,
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Rough"
        component={Demo}
        fps={FPS}
        width={CANVAS.w}
        height={CANVAS.h}
        durationInFrames={30 * 60}
        defaultProps={{ showTimecode: true }}
        calculateMetadata={calculateMetadata}
      />
      <Composition
        id="Final"
        component={Demo}
        fps={FPS}
        width={CANVAS.w}
        height={CANVAS.h}
        durationInFrames={30 * 60}
        defaultProps={{ showTimecode: false }}
        calculateMetadata={calculateMetadata}
      />
    </>
  );
};

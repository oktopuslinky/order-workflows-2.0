/**
 * The take: recorded footage + the driver's event log + the measured
 * viewport->video transform.
 *
 * Three coordinate spaces are in play, and keeping them straight is the whole
 * ballgame:
 *
 *   viewport px  what the browser reported (getBoundingClientRect)
 *   video px     where that lands in the raw recording  [calibration solves this]
 *   canvas px    the 1920x1080 Remotion composition     [fitScale solves this]
 *
 * Everything downstream (cursor, callouts, zooms) works in *viewport* px and is
 * projected through here, so there's exactly one place to be wrong.
 */

export type Rect = { x: number; y: number; w: number; h: number };

export type TakeEvent = {
  type: "click" | "change" | "type" | "mark" | "calibrate";
  t: number; // epoch ms
  tEnd?: number;
  label?: string;
  tag?: string;
  url?: string;
  value?: string;
  name?: string; // for marks
  note?: string;
  rect?: Rect;
};

export type Calibration = {
  video: string;
  videoSize: { w: number; h: number };
  viewport: { w: number; h: number };
  scaleX: number;
  scaleY: number;
  offsetX: number;
  offsetY: number;
  refinedStartEpochMs: number;
  fps: number;
};

export const CANVAS = { w: 1920, h: 1080 };
export const FPS = 30;

/** Epoch ms -> frame index in the recording. */
export const epochToFrame = (t: number, cal: Calibration, fps = FPS): number =>
  Math.round(((t - cal.refinedStartEpochMs) / 1000) * fps);

/** viewport px -> video px */
export const toVideo = (x: number, y: number, cal: Calibration) => ({
  x: cal.scaleX * x + cal.offsetX,
  y: cal.scaleY * y + cal.offsetY,
});

/**
 * The transform that maps the browser viewport region of the raw video onto the
 * full 1920x1080 canvas. `contain`, so nothing is cropped off; any leftover is
 * letterboxed by the background.
 */
export const fitViewport = (cal: Calibration) => {
  const topLeft = toVideo(0, 0, cal);
  const vw = cal.scaleX * cal.viewport.w;
  const vh = cal.scaleY * cal.viewport.h;
  const scale = Math.min(CANVAS.w / vw, CANVAS.h / vh);
  return {
    scale,
    // Where to put the video's top-left so the viewport region is centred.
    left: (CANVAS.w - vw * scale) / 2 - topLeft.x * scale,
    top: (CANVAS.h - vh * scale) / 2 - topLeft.y * scale,
    viewportOnCanvas: {
      x: (CANVAS.w - vw * scale) / 2,
      y: (CANVAS.h - vh * scale) / 2,
      w: vw * scale,
      h: vh * scale,
    },
  };
};

/** viewport px -> canvas px (what cursor + callouts actually draw in). */
export const toCanvas = (x: number, y: number, cal: Calibration) => {
  const fit = fitViewport(cal);
  const v = toVideo(x, y, cal);
  return { x: v.x * fit.scale + fit.left, y: v.y * fit.scale + fit.top };
};

export const rectToCanvas = (r: Rect, cal: Calibration) => {
  const fit = fitViewport(cal);
  const tl = toCanvas(r.x, r.y, cal);
  return {
    x: tl.x,
    y: tl.y,
    w: r.w * cal.scaleX * fit.scale,
    h: r.h * cal.scaleY * fit.scale,
  };
};

export const centreOf = (r: Rect) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });

/** Find a named beat the driver marked with __demoMark(). */
export const mark = (events: TakeEvent[], name: string): TakeEvent | undefined =>
  events.find((e) => e.type === "mark" && e.name === name);

/** Pointer-bearing events, in order -- what the synthetic cursor follows. */
export const pointerEvents = (events: TakeEvent[]): TakeEvent[] =>
  events.filter((e) => (e.type === "click" || e.type === "change" || e.type === "type") && e.rect);

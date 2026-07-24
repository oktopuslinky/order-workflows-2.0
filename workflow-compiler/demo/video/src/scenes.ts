/**
 * The edit.
 *
 * Each scene is a slice between two marks the driver fired during the take, so these
 * names are also the shot list the take must hit. A missing mark throws at render time
 * (Demo.tsx `resolveScene`) with the list of marks that *were* recorded, rather than
 * silently rendering a black scene. Extra marks are harmless -- only missing ones fail.
 *
 * `speed` compresses the real LLM waits. Where it is > 1, `wait` puts a clock on screen
 * showing the TRUE elapsed time and the multiplier, so the compression is disclosed
 * rather than hidden. That rule is not negotiable: the film argues the compiler is
 * honest, so the film has to be.
 *
 * Two scenes deliberately hold at 1x -- `refuse` and `blocking`. They are the argument:
 * the gate refuses to ship dependencies nobody confirmed, and the validator catches a
 * broken hand-off and names the exact mapping. Everything else is plumbing.
 *
 * There is no narration. The captions carry the whole argument; the film has to work
 * with the sound off.
 *
 * NOTE ON THE ENDING: an earlier take ended with two workflows "held below the 0.90
 * graph-health gate". That was a *bug* (a required question reported unmet although it
 * was answered), not a feature, and it has since been fixed. Do not reintroduce captions
 * claiming health-gate scores -- with the fix, all three workflows generate.
 */

import { type Calibration, type Rect, type TakeEvent } from "./lib/take";

type Take = { events: TakeEvent[]; cal: Calibration };

export type SceneSpec = {
  id: string;
  fromMark: string;
  toMark: string;
  speed?: number;
  hideCursor?: boolean;
  wait?: { label: string };
  titleCard?: { kicker?: string; title: string; sub?: string; frames: number };
  captions?: { text: string; from: number; to: number }[];
  callouts?: (take: Take) => {
    rect: Rect;
    text: string;
    from: number;
    to: number;
    side?: "top" | "bottom" | "left" | "right";
    tone?: "info" | "warn" | "good";
  }[];
  focus?: (take: Take) => { rect: Rect; from: number; to: number; scale?: number } | undefined;
};

/** Rect of the element a given event touched -- used to aim callouts/zooms. */
export const rectOfEvent = (take: Take, predicate: (e: TakeEvent) => boolean): Rect | undefined =>
  take.events.find((e) => predicate(e) && e.rect)?.rect;

/** Rect of a marked beat's *next* pointer event -- "the thing we clicked here". */
export const rectAfterMark = (take: Take, markName: string): Rect | undefined => {
  const i = take.events.findIndex((e) => e.type === "mark" && e.name === markName);
  if (i === -1) return undefined;
  return take.events.slice(i + 1).find((e) => e.rect)?.rect;
};

/**
 * Rect of the last thing clicked *before* a mark fired -- i.e. the button whose click
 * caused this beat. `refuse` fires once the refusal is on screen, so the Approve button
 * that triggered it is behind us, not ahead.
 */
export const rectBeforeMark = (take: Take, markName: string): Rect | undefined => {
  const i = take.events.findIndex((e) => e.type === "mark" && e.name === markName);
  if (i === -1) return undefined;
  const before = take.events.slice(0, i).filter((e) => e.rect && e.type === "click");
  return before[before.length - 1]?.rect;
};

/** Click whose recorded label matches -- the sturdiest way to aim at a known button. */
const rectOfLabel = (take: Take, re: RegExp): Rect | undefined =>
  rectOfEvent(take, (e) => e.type === "click" && !!e.label && re.test(e.label));

/**
 * Callouts are aimed at rects measured during the take. If the take didn't record the
 * rect we're aiming at, drop the callout rather than crash the render -- a missing
 * annotation is a blemish; a failed render is a blocker.
 */
type Callout = {
  rect: Rect;
  text: string;
  from: number;
  to: number;
  side?: "top" | "bottom" | "left" | "right";
  tone?: "info" | "warn" | "good";
};
const callout = (rect: Rect | undefined, c: Omit<Callout, "rect">): Callout[] =>
  rect ? [{ rect, ...c }] : [];

export const SCENES: SceneSpec[] = [
  // ------------------------------------------------------------- Act I: in
  {
    id: "upload",
    fromMark: "upload",
    toMark: "compile-start",
    speed: 2,
    titleCard: {
      kicker: "Workflow Compiler",
      title: "A business document in.\nRunnable Temporal code out.",
      sub: "With a human gate in the middle — because the model does not get the last word.",
      frames: 105,
    },
    captions: [
      { text: "One document. Three workflows buried inside it.", from: 10, to: 130 },
      { text: "Order placement, fulfilment, returns — and the hand-offs between them.", from: 140, to: 320 },
    ],
  },
  {
    id: "compile",
    fromMark: "compile-start",
    toMark: "compile-done",
    speed: 46,
    hideCursor: true,
    wait: { label: "compiling" },
    captions: [
      { text: "It segments the document, then extracts facts from each workflow separately.", from: 10, to: 999 },
    ],
  },
  {
    id: "reveal",
    fromMark: "compile-done",
    toMark: "workspace",
    captions: [{ text: "Three workflows. Three cross-references. Three triggers.", from: 5, to: 999 }],
  },

  // -------------------------------------------------- Act II: what came back
  {
    id: "workspace",
    fromMark: "workspace",
    toMark: "views",
    speed: 4,
    captions: [
      { text: "Every workflow gets an editable spec — this is the draft, not the answer.", from: 10, to: 999 },
    ],
  },
  {
    id: "views",
    fromMark: "views",
    toMark: "cvpa-start",
    speed: 5,
    captions: [
      { text: "The spec, its rendered preview, and the graph it implies.", from: 10, to: 220 },
      { text: "All three are projections of one structured object.", from: 230, to: 999 },
    ],
  },
  {
    id: "cvpa",
    fromMark: "cvpa-start",
    toMark: "cvpa-done",
    speed: 20,
    hideCursor: true,
    wait: { label: "classifying phases" },
  },
  {
    id: "phases",
    fromMark: "cvpa-done",
    toMark: "gate",
    speed: 3,
    captions: [{ text: "The diagram recolours by phase: capture, validate, process, act.", from: 5, to: 999 }],
  },

  // --------------------------------------------------- Act III: the human gate
  {
    id: "gate",
    fromMark: "gate",
    toMark: "validate0-start",
    speed: 4,
    titleCard: {
      kicker: "The human gate",
      title: "The model drafts.\nYou correct.",
      sub: "This is the part that makes the generated code trustworthy.",
      frames: 95,
    },
  },
  {
    id: "validate0",
    fromMark: "validate0-start",
    toMark: "validate0-done",
    speed: 24,
    hideCursor: true,
    wait: { label: "validating" },
    captions: [{ text: "Validate first. Approve only ever trusts the last validate.", from: 10, to: 999 }],
  },
  {
    id: "clean-draft",
    fromMark: "validate0-done",
    toMark: "refuse",
    speed: 4,
    // Do not name a warning COUNT here: a fresh compile re-derives its own findings, and take 3
    // produced a different number than take 1. Say what is invariant -- nothing is blocking.
    captions: [{ text: "Warnings only, nothing blocking. The draft looks good. So — approve it?", from: 5, to: 999 }],
  },
  {
    // MONEY SHOT #1 -- held at 1x. The machine refuses.
    id: "refuse",
    fromMark: "refuse",
    toMark: "confirm",
    captions: [
      { text: "It refuses. The cross-workflow dependencies were inferred, and nobody confirmed them.", from: 5, to: 210 },
      { text: "A guess it cannot verify is not something it will let you ship.", from: 220, to: 999 },
    ],
    callouts: (take) =>
      callout(rectBeforeMark(take, "refuse"), { text: "Approve — refused", from: 10, to: 999, tone: "warn" }),
  },
  {
    id: "confirm",
    fromMark: "confirm",
    toMark: "break",
    speed: 8,
    // This compile derived NO open questions (all three specs: `<!-- none -->`), so there was no
    // question to answer on camera. Caption the confirmations, which is what actually happens.
    captions: [
      { text: "So confirm them by hand — every dependency, every trigger, one workflow at a time.", from: 10, to: 999 },
    ],
  },
  {
    id: "break",
    fromMark: "break",
    toMark: "validate-start",
    speed: 6,
    captions: [
      { text: "Now break it on purpose: rename an input the next workflow depends on.", from: 10, to: 210 },
      { text: "Does the gate actually catch it — or just wave it through?", from: 220, to: 999 },
    ],
  },
  {
    id: "validate",
    fromMark: "validate-start",
    toMark: "validate-done",
    speed: 26,
    hideCursor: true,
    wait: { label: "validating" },
  },
  {
    // MONEY SHOT #2 -- held at 1x. The validator names the exact broken mapping.
    id: "blocking",
    fromMark: "validate-done",
    toMark: "fix",
    captions: [
      { text: "Caught — and it names the exact broken mapping, not just \"something is wrong\".", from: 5, to: 220 },
      { text: "The trigger maps to an input the target workflow no longer declares.", from: 230, to: 999 },
    ],
    callouts: (take) =>
      callout(rectOfLabel(take, /validate/i), { text: "1 blocking finding", from: 10, to: 999, tone: "warn" }),
  },
  {
    id: "fix",
    fromMark: "fix",
    toMark: "revalidate-start",
    speed: 5,
    captions: [{ text: "Put it back. Save. Validate again.", from: 5, to: 999 }],
  },
  {
    id: "revalidate",
    fromMark: "revalidate-start",
    toMark: "revalidate-done",
    speed: 26,
    hideCursor: true,
    wait: { label: "re-validating" },
  },
  {
    id: "clean",
    fromMark: "revalidate-done",
    toMark: "approve-start",
    speed: 4,
    captions: [{ text: "Zero blocking findings. Now — and only now — Approve unlocks.", from: 5, to: 999 }],
  },

  // ------------------------------------------------------------- Act IV: out
  {
    id: "approve",
    fromMark: "approve-start",
    toMark: "approve-done",
    speed: 42,
    hideCursor: true,
    wait: { label: "generating" },
    captions: [{ text: "Graph → health gate → CVPA → Temporal design → code generation.", from: 10, to: 999 }],
  },
  {
    id: "generated",
    fromMark: "approve-done",
    toMark: "results",
    speed: 3,
    captions: [
      { text: "All three workflows generated — because all three earned it.", from: 5, to: 200 },
      { text: "The code is a deterministic render of the design you approved. No model wrote it.", from: 210, to: 999 },
    ],
  },
  {
    id: "results",
    fromMark: "results",
    toMark: "code",
    speed: 4,
    captions: [{ text: "Per-workflow: the graph, its health score, and the CVPA phase table.", from: 5, to: 999 }],
  },
  {
    id: "files",
    fromMark: "code",
    toMark: "download",
    speed: 4,
    captions: [
      { text: "workflow.py, activities.py, worker.py, triggers.py — generated, not templated.", from: 10, to: 260 },
      { text: "Plus a worker, a starter, and a step-through test.", from: 270, to: 999 },
    ],
  },
  {
    id: "download",
    fromMark: "download",
    toMark: "end",
    speed: 2,
    captions: [{ text: "Download the lot.", from: 5, to: 999 }],
  },
  {
    // Outro. A title card renders *before* its scene, and there is no mark after `end`,
    // so this zero-length slice (end -> end, clamped to 1 frame) exists purely to hang
    // the closing card on. Cheaper than a new field in Demo.tsx.
    id: "outro",
    fromMark: "end",
    toMark: "end",
    hideCursor: true,
    titleCard: {
      kicker: "Workflow Compiler",
      title: "The LLM specifies.\nDeterministic code emits.",
      sub: "And a human signs off on everything in between.",
      frames: 115,
    },
  },
];

/**
 * The demo composition.
 *
 * Scenes are cut from *named marks* the driver fired during the take
 * (`__demoMark("compile-start")`), not hand-typed timecodes -- so the edit stays
 * pinned to what actually happened, and re-recording the take doesn't mean
 * re-timing the video by hand.
 */

import React from "react";
import { AbsoluteFill, Sequence, continueRender, delayRender, staticFile } from "remotion";

import { Cursor } from "./components/Cursor";
import { Screen } from "./components/Screen";
import { Caption, Callout, TitleCard, WaitClock } from "./components/Overlays";
import { type Calibration, type TakeEvent, epochToFrame, mark } from "./lib/take";
import { type SceneSpec, SCENES } from "./scenes";

export type DemoProps = {
  /** Burn scene name + timecode into the frame (for the review cut). */
  showTimecode?: boolean;
};

type Take = { events: TakeEvent[]; cal: Calibration };

/** Load events + calibration before the first frame renders. */
export const useTake = (): Take | null => {
  const [take, setTake] = React.useState<Take | null>(null);
  const [handle] = React.useState(() => delayRender("loading take"));

  React.useEffect(() => {
    Promise.all([
      fetch(staticFile("events.json")).then((r) => r.json()),
      fetch(staticFile("calibration.json")).then((r) => r.json()),
    ])
      .then(([events, cal]) => {
        setTake({ events, cal });
        continueRender(handle);
      })
      .catch((err) => {
        throw new Error(`Could not load the take: ${err}`);
      });
  }, [handle]);

  return take;
};

/** Resolve a scene's mark names into recording frame numbers. */
const resolveScene = (spec: SceneSpec, take: Take) => {
  const from = mark(take.events, spec.fromMark);
  const to = mark(take.events, spec.toMark);
  if (!from || !to) {
    throw new Error(
      `Scene "${spec.id}" references missing mark(s): ${spec.fromMark} / ${spec.toMark}. ` +
        `Marks present: ${take.events
          .filter((e) => e.type === "mark")
          .map((e) => e.name)
          .join(", ")}`,
    );
  }
  const startFrame = epochToFrame(from.t, take.cal);
  const endFrame = epochToFrame(to.t, take.cal);
  const rawFrames = Math.max(1, endFrame - startFrame);
  const speed = spec.speed ?? 1;
  return {
    startFrame,
    rawFrames,
    realSeconds: rawFrames / take.cal.fps,
    // Speeding the footage up shortens the scene by the same factor.
    durationInFrames: Math.max(1, Math.round(rawFrames / speed)),
  };
};

const TimecodeBurn: React.FC<{ scene: string; index: number }> = ({ scene, index }) => (
  <div
    style={{
      position: "absolute",
      left: 40,
      top: 30,
      zIndex: 100,
      fontFamily: "monospace",
      fontSize: 30,
      color: "#fde68a",
      background: "rgba(2,6,23,0.85)",
      padding: "8px 14px",
      borderRadius: 6,
    }}
  >
    #{index} {scene}
  </div>
);

export const Demo: React.FC<DemoProps> = ({ showTimecode = false }) => {
  const take = useTake();
  if (!take) return null;

  let cursorFrames = 0;
  const placed = SCENES.map((spec) => {
    const r = resolveScene(spec, take);
    const seq = { spec, ...r, at: cursorFrames };
    cursorFrames += r.durationInFrames + (spec.titleCard ? spec.titleCard.frames : 0);
    return seq;
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#0b0f17" }}>
      {placed.map((s, i) => {
        const nodes: React.ReactNode[] = [];
        let at = s.at;

        if (s.spec.titleCard) {
          nodes.push(
            <Sequence
              key={`${s.spec.id}-card`}
              from={at}
              durationInFrames={s.spec.titleCard.frames}
            >
              <TitleCard {...s.spec.titleCard} durationInFrames={s.spec.titleCard.frames} />
            </Sequence>,
          );
          at += s.spec.titleCard.frames;
        }

        nodes.push(
          <Sequence key={s.spec.id} from={at} durationInFrames={s.durationInFrames}>
            <Screen
              cal={take.cal}
              startFrame={s.startFrame}
              speed={s.spec.speed ?? 1}
              focus={s.spec.focus?.(take)}
            >
              {/* Cursor is disabled during pure-wait scenes: nothing is being
                  clicked, and a hovering pointer would be an invention. */}
              {!s.spec.hideCursor && (
                <Cursor events={take.events} cal={take.cal} startFrame={s.startFrame} />
              )}
              {s.spec.callouts?.(take).map((c, ci) => (
                <Callout key={ci} cal={take.cal} {...c} />
              ))}
            </Screen>

            {s.spec.wait && (
              <WaitClock
                realSeconds={s.realSeconds}
                durationInFrames={s.durationInFrames}
                speed={s.spec.speed ?? 1}
                label={s.spec.wait.label}
              />
            )}

            {/* There is no narration -- the captions carry the whole argument.
                The film has to work with the sound off. */}
            {s.spec.captions?.map((c, ci) => (
              <Caption key={ci} text={c.text} from={c.from} to={c.to} />
            ))}

            {showTimecode && <TimecodeBurn scene={s.spec.id} index={i + 1} />}
          </Sequence>,
        );

        return <React.Fragment key={s.spec.id}>{nodes}</React.Fragment>;
      })}
    </AbsoluteFill>
  );
};

/** Total length, computed from the take -- used by Root's calculateMetadata. */
export const demoDuration = (take: Take): number =>
  SCENES.reduce((acc, spec) => {
    const r = resolveScene(spec, take);
    return acc + r.durationInFrames + (spec.titleCard?.frames ?? 0);
  }, 0);

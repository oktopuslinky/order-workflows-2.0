import "./index.css";
import React from "react";
import { Composition } from "remotion";
import { DemoVideo } from "./Video";
import { SCENES, FPS, TOTAL } from "./config";
import { KgDemoVideo } from "./VideoKg";
import { SCENES as KG_SCENES, TOTAL as KG_TOTAL } from "./configKg";

const SAMPLE = ["hero", "create", "results"];
const SAMPLE_FRAMES = SCENES.filter((s) => SAMPLE.includes(s.name)).reduce((a, s) => a + s.durationInFrames, 0);

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Demo"
        component={DemoVideo}
        durationInFrames={TOTAL}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="Sample"
        component={DemoVideo}
        defaultProps={{ only: SAMPLE }}
        durationInFrames={SAMPLE_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="KgDemo"
        component={KgDemoVideo}
        durationInFrames={KG_TOTAL}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="KgSample"
        component={KgDemoVideo}
        defaultProps={{ only: ["kg-hero", "kg-graph", "kg-outputs-smoke"] }}
        durationInFrames={KG_SCENES.filter((s) => ["kg-hero", "kg-graph", "kg-outputs-smoke"].includes(s.name)).reduce((a, s) => a + s.durationInFrames, 0) || 300}
        fps={FPS}
        width={1920}
        height={1080}
      />
    </>
  );
};

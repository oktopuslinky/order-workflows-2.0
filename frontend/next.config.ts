import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root to this folder — a stray lockfile in a parent dir
  // otherwise makes Next infer the wrong root.
  turbopack: {
    root: path.resolve(__dirname),
  },
  // The dev-tools badge floats over the bottom-left of every page, which puts it
  // inside the demo recording's crop for the whole video. Compile and runtime
  // errors are still surfaced with this off.
  devIndicators: false,
};

export default nextConfig;

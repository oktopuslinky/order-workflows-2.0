"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { NodeRunStatus } from "@/lib/runHighlights";

let mermaidReady: Promise<typeof import("mermaid").default> | null = null;

function loadMermaid() {
  if (!mermaidReady) {
    mermaidReady = import("mermaid").then((mod) => {
      const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      mod.default.initialize({
        startOnLoad: false,
        theme: dark ? "dark" : "neutral",
        // A diagram the model got wrong must show *our* error text next to the
        // diagram, not mermaid's "bomb" appended to document.body (seen live when a
        // regenerated .mmd had a syntax slip).
        suppressErrorRendering: true,
      });
      return mod.default;
    });
  }
  return mermaidReady;
}

const STATUS_CLASSES = ["run-done", "run-active", "run-waiting", "run-failed"];

export function MermaidView({
  source,
  nodeStatus,
}: {
  source: string;
  /** Live-run highlighting: diagram node id → status (see lib/runHighlights). */
  nodeStatus?: Record<string, NodeRunStatus>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped after each successful render so highlighting re-applies to the new
  // SVG — the innerHTML swap throws away any classes set on the old one.
  const [renderTick, setRenderTick] = useState(0);
  const domId = `mmd-${useId().replace(/:/g, "")}`;

  useEffect(() => {
    let cancelled = false;
    if (!source?.trim()) return;
    loadMermaid()
      .then((mermaid) => mermaid.render(domId, source))
      .then(({ svg }) => {
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
          setError(null);
          setRenderTick((t) => t + 1);
        }
      })
      .catch((e) => !cancelled && setError(String(e?.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [source, domId]);

  useEffect(() => {
    const svg = ref.current?.querySelector("svg");
    if (!svg) return;
    // Mermaid ids each node's <g> as `<renderId>-flowchart-<nodeId>-<n>` (the
    // render id is the container dom id passed to mermaid.render).
    svg.querySelectorAll<SVGGElement>("g.node").forEach((g) => {
      g.classList.remove(...STATUS_CLASSES);
      const key = g.id.match(/flowchart-(.+)-\d+$/)?.[1];
      const status = key ? nodeStatus?.[key] : undefined;
      if (status) g.classList.add(`run-${status}`);
    });
  }, [nodeStatus, renderTick]);

  if (!source?.trim()) {
    return <p className="text-xs text-[var(--faint)]">No diagram yet.</p>;
  }
  return (
    <div className="overflow-auto">
      {error ? (
        <pre className="whitespace-pre-wrap text-xs text-[var(--block)]">{error}</pre>
      ) : (
        <div ref={ref} className="[&_svg]:max-w-full" />
      )}
    </div>
  );
}

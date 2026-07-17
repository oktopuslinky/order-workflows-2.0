"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Full-panel overlay for a multi-minute LLM call: a spinner, an elapsed timer,
 * and a rotating "what's happening now" label (the backend has no progress
 * stream yet, so the labels advance on a heuristic timer).
 */
export function RunningOverlay({
  title,
  steps,
  stepSeconds = 35,
}: {
  title: string;
  steps: string[];
  /** Heuristic seconds per step label — shorter calls (edits) pass a smaller value. */
  stepSeconds?: number;
}) {
  const [elapsed, setElapsed] = useState(0);
  const start = useRef(0);

  useEffect(() => {
    start.current = Date.now();
    const t = setInterval(
      () => setElapsed(Math.floor((Date.now() - start.current) / 1000)),
      1000,
    );
    return () => clearInterval(t);
  }, []);

  // Advance the label heuristically across the known stages.
  const stepIndex = Math.min(Math.floor(elapsed / stepSeconds), steps.length - 1);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");

  return (
    <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-4 bg-[var(--paper)]/80 backdrop-blur-sm">
      <div className="h-10 w-10 animate-spin rounded-full border-3 border-[var(--border-strong)] border-t-[var(--accent)]" />
      <div className="text-center">
        <p className="font-medium">{title}</p>
        <p className="mt-1 text-sm text-[var(--muted)]">{steps[stepIndex]}…</p>
        <p className="mt-2 font-mono text-xs text-[var(--faint)]">
          {mm}:{ss} elapsed · LLM stages can take 1–3 minutes
        </p>
      </div>
    </div>
  );
}

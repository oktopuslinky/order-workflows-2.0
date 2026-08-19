"use client";

import { useEffect, useId, useRef, useState } from "react";

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

export function MermaidView({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
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
        }
      })
      .catch((e) => !cancelled && setError(String(e?.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [source, domId]);

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

"use client";

import { SEVERITY_STYLE, SEVERITY_TAG } from "@/lib/format";
import type { SpecFinding } from "@/lib/types";

export function FindingsPanel({
  findings,
  onSelect,
}: {
  findings: SpecFinding[];
  onSelect?: (section: string | null) => void;
}) {
  if (findings.length === 0) {
    return (
      <p className="text-xs text-emerald-500">No findings — spec looks clean.</p>
    );
  }
  const order = { blocking: 0, warning: 1, info: 2 } as const;
  const sorted = [...findings].sort(
    (a, b) => order[a.severity] - order[b.severity],
  );
  return (
    <ul className="flex flex-col gap-2">
      {sorted.map((f, i) => {
        const location = [f.section, f.field].filter(Boolean).join(" › ");
        return (
          <li key={i}>
            <button
              onClick={() => onSelect?.(f.section)}
              className={`w-full rounded-md border px-2.5 py-2 text-left text-xs ${SEVERITY_STYLE[f.severity]}`}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold">
                  {SEVERITY_TAG[f.severity]}
                </span>
                {location && <span className="opacity-70">{location}</span>}
              </div>
              <p className="mt-1 leading-snug">{f.message}</p>
              {f.suggestion && (
                <p className="mt-1 italic opacity-70">→ {f.suggestion}</p>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

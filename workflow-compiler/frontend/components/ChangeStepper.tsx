"use client";

import type { ChangeStepKind, WizardStep } from "@/lib/types";
import { STEP_LABEL, STEP_ORDER, STEP_TONE } from "@/components/ChangeStagePill";

/**
 * Impact → EPIC → Stories → TDD. The current step is highlighted; any step that
 * has been reached (current or earlier, or already carrying a draft) can be
 * opened to review its transcript and artifact.
 */
export function ChangeStepper({
  steps,
  current,
  selected,
  running,
  onSelect,
}: {
  steps: WizardStep[];
  current: ChangeStepKind | null;
  selected: ChangeStepKind;
  /** The step whose job is running, if any (shown as "working…"). */
  running: boolean;
  onSelect: (kind: ChangeStepKind) => void;
}) {
  const byKind = new Map(steps.map((s) => [s.kind, s]));
  const currentIdx = current ? STEP_ORDER.indexOf(current) : -1;
  return (
    <ol className="flex flex-wrap items-stretch gap-1.5" aria-label="Wizard steps">
      {STEP_ORDER.map((kind, i) => {
        const step = byKind.get(kind);
        const status = step?.status ?? "pending";
        const isCurrent = kind === current;
        const reached = i <= currentIdx || status !== "pending" || (currentIdx === -1 && i === 0);
        const isSelected = kind === selected;
        const label =
          isCurrent && running ? "working…" : status === "asking" ? "questions" : status;
        return (
          <li key={kind} className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={!reached}
              onClick={() => onSelect(kind)}
              aria-current={isCurrent ? "step" : undefined}
              className={`flex min-w-[6.5rem] flex-col items-start rounded-md border px-2.5 py-1.5 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${
                isSelected
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-strong)]"
              }`}
              title={reached ? `Open ${STEP_LABEL[kind]}` : "Not reached yet"}
            >
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <span className="font-mono text-[11px] text-[var(--faint)]">{i + 1}</span>
                {STEP_LABEL[kind]}
                {isCurrent && (
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" aria-hidden />
                )}
              </span>
              <span className={`pill mt-1 ${STEP_TONE[status]}`}>{label}</span>
            </button>
            {i < STEP_ORDER.length - 1 && (
              <span className="text-[var(--faint)]" aria-hidden>
                →
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDuration, fmtHours } from "@/lib/format";
import type { TimeSavedReport } from "@/lib/types";

/**
 * Per-project time-saved breakdown: measured pipeline seconds vs. the
 * configured human-team estimates. Values are always shown as text — the bars
 * are redundant proportion cues, never the only encoding.
 */
export function TimeSavedCard({ report }: { report: TimeSavedReport }) {
  if (report.rows.length === 0) return null;
  const maxBaseline = Math.max(
    ...report.rows.map((row) => row.human_baseline_hours),
    0.001,
  );
  return (
    <div className="card p-3">
      <p className="eyebrow mb-1">Time saved</p>
      <p className="text-lg font-semibold text-[var(--pass)]">
        ≈ {fmtHours(Math.max(report.total_saved_hours, 0))} saved
      </p>
      <p className="mb-2 text-[11px] text-[var(--muted)]">
        vs. an estimated human-team effort of{" "}
        {fmtHours(report.total_baseline_hours)} — the pipeline ran for{" "}
        {fmtDuration(report.total_actual_seconds)}.
      </p>
      <table className="w-full text-[11px] [font-variant-numeric:tabular-nums]">
        <thead>
          <tr className="text-left text-[var(--faint)]">
            <th className="py-0.5 pr-2 font-medium">Step</th>
            <th className="py-0.5 pr-2 font-medium">Human est.</th>
            <th className="py-0.5 font-medium">Actual</th>
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row) => (
            <tr key={row.step} className="align-top text-[var(--muted)]">
              <td className="py-1 pr-2">
                <span className="font-mono text-[10px] text-[var(--ink)]">
                  {row.step}
                </span>
                <span
                  aria-hidden
                  className="mt-0.5 block h-1 rounded-full bg-[var(--pass)] opacity-60"
                  style={{
                    width: `${Math.max(
                      (row.human_baseline_hours / maxBaseline) * 100,
                      4,
                    )}%`,
                  }}
                />
              </td>
              <td className="py-1 pr-2 whitespace-nowrap">
                {fmtHours(row.human_baseline_hours)}
              </td>
              <td className="py-1 whitespace-nowrap">
                {fmtDuration(row.actual_seconds)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-[var(--faint)]">
        Human-team hours are configurable estimates
        (WORKFLOW_COMPILER_BASELINE_HOURS), not measurements.
      </p>
    </div>
  );
}

/** Landing-page aggregate: total time saved across the caller's projects. */
export function TimeSavedStat() {
  const summary = useQuery({
    queryKey: ["metrics-summary"],
    queryFn: () => api.metricsSummary(),
  });
  if (summary.isLoading) {
    return (
      <div className="card mb-6 h-16 animate-pulse bg-[var(--surface-2)]" />
    );
  }
  const data = summary.data;
  if (!data || data.projects === 0 || data.total_saved_hours <= 0) return null;
  return (
    <div className="card mb-6 flex flex-wrap items-baseline gap-x-3 gap-y-1 p-4">
      <span className="text-2xl font-semibold text-[var(--pass)] [font-variant-numeric:tabular-nums]">
        ≈ {fmtHours(data.total_saved_hours)}
      </span>
      <span className="text-sm text-[var(--muted)]">
        saved across {data.projects} project{data.projects === 1 ? "" : "s"} —
        the pipelines ran for {fmtDuration(data.total_actual_seconds)} in place
        of an estimated {fmtHours(data.total_baseline_hours)} of human-team
        work.
      </span>
      <span
        className="basis-full text-[10px] text-[var(--faint)]"
        title="Working day = 8 hours. Baselines are configurable estimates, not measurements."
      >
        Estimates — tune WORKFLOW_COMPILER_BASELINE_HOURS to your org.
      </span>
    </div>
  );
}

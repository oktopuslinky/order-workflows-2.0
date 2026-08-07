import type { ProjectStage, Severity } from "./types";

export const STAGE_LABEL: Record<ProjectStage, string> = {
  ingested: "Ingested",
  workflows_discovered: "Workflows discovered",
  spec_drafted: "Spec drafted",
  spec_validated: "Validated",
  spec_approved: "Approved",
  compiling: "Compiling",
  completed: "Completed",
  needs_attention: "Needs attention",
  failed: "Failed",
};

export const SEVERITY_STYLE: Record<Severity, string> = {
  blocking: "tone-block",
  warning: "tone-gate",
  info: "tone-info",
};

/** Stage → semantic tone class (gate = waiting on a human, pass = approved). */
export const STAGE_TONE: Record<ProjectStage, string> = {
  ingested: "tone-info",
  workflows_discovered: "tone-info",
  spec_drafted: "tone-info",
  spec_validated: "tone-gate",
  spec_approved: "tone-pass",
  compiling: "tone-accent",
  completed: "tone-pass",
  needs_attention: "tone-gate",
  failed: "tone-block",
};

export const SEVERITY_TAG: Record<Severity, string> = {
  blocking: "BLOCK",
  warning: "WARN",
  info: "INFO",
};

/** Compile-stage progression labels shown under the spinner. */
export const COMPILE_STEPS = [
  "Segmenting document into workflows",
  "Extracting facts per workflow",
  "Drafting editable specs",
];

export const APPROVE_STEPS = [
  "Building workflow graphs",
  "CVPA classification",
  "Temporal design",
  "Generating Temporal code",
];

export function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

/** Seconds → compact human duration ("42 s", "3.5 min", "1.2 h"). */
export function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

/** ISO timestamp → compact relative age ("just now", "5m", "2h", "3d", "Jul 4"). */
export function fmtRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, (Date.now() - then) / 1000);
  if (secs < 45) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  if (secs < 7 * 86400) return `${Math.round(secs / 86400)}d ago`;
  return new Date(then).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** Hours → "X h" with a working-days hint for large values (8-hour days). */
export function fmtHours(hours: number): string {
  const rounded = hours >= 10 ? Math.round(hours).toString() : hours.toFixed(1);
  if (hours < 16) return `${rounded} h`;
  return `${rounded} h (≈ ${(hours / 8).toFixed(1)} working days)`;
}

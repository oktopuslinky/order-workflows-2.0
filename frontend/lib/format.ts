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
  blocking: "border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-300",
  warning:
    "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  info: "border-slate-400/40 bg-slate-400/10 text-slate-600 dark:text-slate-400",
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

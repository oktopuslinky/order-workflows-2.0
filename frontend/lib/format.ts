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

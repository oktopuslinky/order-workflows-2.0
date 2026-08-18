import type { ChangeStage, ChangeStepKind, WizardStepStatus } from "@/lib/types";

/** Stage pill for a change request (created / in progress / complete). */
export function ChangeStagePill({ stage }: { stage: ChangeStage }) {
  const tone =
    stage === "complete" ? "tone-pass" : stage === "in_progress" ? "tone-gate" : "tone-info";
  const label = stage === "in_progress" ? "in progress" : stage;
  return <span className={`pill ${tone}`}>{label}</span>;
}

export const STEP_LABEL: Record<ChangeStepKind, string> = {
  impact: "Impact",
  epic: "EPIC",
  stories: "Stories",
  tdd: "TDD",
};

export const STEP_ORDER: ChangeStepKind[] = ["impact", "epic", "stories", "tdd"];

/** Wizard step status → tone class. */
export const STEP_TONE: Record<WizardStepStatus, string> = {
  pending: "tone-info",
  asking: "tone-gate",
  drafting: "tone-accent",
  drafted: "tone-gate",
  approved: "tone-pass",
};

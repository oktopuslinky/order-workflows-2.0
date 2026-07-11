// TypeScript mirrors of the workflow-compiler Pydantic models the UI consumes.
// Only the fields the frontend reads are typed; unknown fields pass through.

export type Severity = "blocking" | "warning" | "info";

export type ProjectStage =
  | "ingested"
  | "workflows_discovered"
  | "spec_drafted"
  | "spec_validated"
  | "spec_approved"
  | "compiling"
  | "completed"
  | "needs_attention"
  | "failed";

export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "changes_requested";

export type EventKind = "trigger" | "signal_wait" | "output_emit";
export type TriggerMode = "blocking" | "fire_and_forget";
export type CVPAPhase =
  | "capture"
  | "validate"
  | "process"
  | "activate"
  | "unclassified";
export type ReviewSeverity =
  | "info"
  | "warning"
  | "error"
  | "critical"
  | string;

export interface SpecFinding {
  severity: Severity;
  workflow: string;
  section: string | null;
  field: string | null;
  message: string;
  suggestion: string | null;
}

export interface SpecItem {
  text: string;
  provenance: string;
  resolved: boolean;
  answer: string | null;
  ref: string | null;
}

export interface CrossReference {
  source_workflow: string;
  output_field: string;
  output_type: string;
  target_workflow: string;
  input_field: string;
  input_type: string;
  description: string | null;
  user_confirmed: boolean;
}

export interface TriggerInputBinding {
  target_input: string;
  source: string;
  source_ref: string | null;
  type: string;
}

export interface WorkflowTrigger {
  source_workflow: string;
  target_workflow: string;
  mode: TriggerMode;
  condition: string | null;
  input_map: TriggerInputBinding[];
  result_binding: string | null;
  user_confirmed: boolean;
}

export interface WorkflowMetadata {
  name: string;
  purpose: string | null;
  domain: string | null;
  owner: string | null;
  [key: string]: unknown;
}

export interface WorkflowSpec {
  slug: string;
  metadata: WorkflowMetadata;
  open_questions: SpecItem[];
  assumptions: SpecItem[];
  ambiguities: SpecItem[];
  suggested_edits: SpecItem[];
  [key: string]: unknown;
}

export interface WorkflowSegment {
  id: string;
  slug: string;
  name: string;
  purpose: string | null;
  sliced: boolean;
}

export interface CompilationProject {
  project_id: string;
  document_text: string;
  segments: WorkflowSegment[];
  specs: WorkflowSpec[];
  cross_references: CrossReference[];
  triggers: WorkflowTrigger[];
  spec_approval_status: ApprovalStatus;
  workflow_ids: Record<string, string>;
  warnings: string[];
  validation_findings: Record<string, SpecFinding[]>;
  stage: ProjectStage;
  created_at: string;
  updated_at: string;
}

export interface ProjectResponse {
  project: CompilationProject;
  spec_markdown: Record<string, string>;
}

export interface GeneratedFile {
  path: string;
  language: string;
  content: string;
}

export interface ProjectFilesResponse {
  project_id: string;
  files: GeneratedFile[];
}

export interface MermaidDiagram {
  source: string;
  title: string | null;
  [key: string]: unknown;
}

export interface ReviewIssue {
  id: string;
  severity: ReviewSeverity;
  message: string;
  location: string | null;
  suggestion: string | null;
}

export interface ReviewReport {
  summary: string | null;
  issues: ReviewIssue[];
  score: number | null;
  health_score: number | null;
  [key: string]: unknown;
}

export interface CVPANodeAssignment {
  node_id: string;
  phase: CVPAPhase;
  rationale: string | null;
  confidence: number;
}

export interface CVPAClassification {
  assignments: CVPANodeAssignment[];
  [key: string]: unknown;
}

export interface TemporalCodeBundle {
  files: GeneratedFile[];
  [key: string]: unknown;
}

export interface WorkflowState {
  workflow_id: string;
  project_id: string | null;
  approval_status: ApprovalStatus;
  review_report: ReviewReport | null;
  cvpa_classification: CVPAClassification | null;
  temporal_code: TemporalCodeBundle | null;
  mermaid_diagram: MermaidDiagram | null;
  stage: string;
  [key: string]: unknown;
}

export interface WorkflowStateResponse {
  state: WorkflowState;
}

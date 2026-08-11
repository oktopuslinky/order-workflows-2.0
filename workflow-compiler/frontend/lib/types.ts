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

export interface LocalModel {
  id: string;
  /** null until health has actually been probed. */
  available: boolean | null;
  detail: string | null;
}

/**
 * The gateway advertises every configured model whether or not its inference
 * server is up, so `models` is a list of names, not a promise that they serve.
 * `entries` carries health once a probe has run.
 */
export interface LocalModelList {
  models: string[];
  entries: LocalModel[];
  probed: boolean;
}

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

export interface EditPatch {
  action: string;
  target: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface WiringOp {
  action: string;
  source_workflow?: string;
  target_workflow?: string;
  [key: string]: unknown;
}

/** Opaque preview handoff — round-tripped to the server verbatim on confirm. */
export interface ResolvedEdit {
  fingerprint: string;
  [key: string]: unknown;
}

export interface EditPreviewResponse {
  record: EditRecord;
  resolved: ResolvedEdit;
  spec_markdown: Record<string, string>;
  workflows_added: string[];
  workflows_removed: string[];
}

export interface EditRecord {
  edit_id: string;
  document: string;
  author: string | null;
  created_at: string;
  resolved_patches: Record<string, EditPatch[]>;
  trigger_ops: WiringOp[];
  xref_ops: WiringOp[];
  workflows_added: string[];
  workflows_removed: string[];
  summary: Record<string, string[]>;
  [key: string]: unknown;
}

export interface CompilationProject {
  project_id: string;
  nickname: string | null;
  document_text: string;
  segments: WorkflowSegment[];
  specs: WorkflowSpec[];
  cross_references: CrossReference[];
  triggers: WorkflowTrigger[];
  spec_approval_status: ApprovalStatus;
  workflow_ids: Record<string, string>;
  warnings: string[];
  validation_findings: Record<string, SpecFinding[]>;
  edit_log: EditRecord[];
  dialogue_session: DialogueSession | null;
  stage: ProjectStage;
  created_at: string;
  updated_at: string;
}

export interface TimeSavedRow {
  step: string;
  category: string;
  label: string;
  human_baseline_hours: number;
  actual_seconds: number;
  saved_hours: number;
}

/** Measured pipeline time vs. estimated human-team hours. Baselines are estimates. */
export interface TimeSavedReport {
  rows: TimeSavedRow[];
  total_baseline_hours: number;
  total_actual_seconds: number;
  total_saved_hours: number;
}

export interface MetricsSummary {
  projects: number;
  total_baseline_hours: number;
  total_actual_seconds: number;
  total_saved_hours: number;
}

/** Per-user UI/metric preferences, persisted on the account. */
export interface UserPreferences {
  // Per-user overrides of the org-wide baselines, keyed by metric category
  // (discovery/spec/validate/compile/edit). Empty = inherit config defaults.
  baseline_hours: Record<string, number>;
  projects_page_size: number;
}

/** Lightweight project row for the Projects list (label, stage, timestamp). */
export interface ProjectSummary {
  project_id: string;
  nickname: string | null;
  stage: ProjectStage;
  workflow_count: number;
  updated_at: string;
}

export interface ProjectListResponse {
  projects: ProjectSummary[];
}

/** Org-wide defaults so the Settings UI can show "default: X" and offer reset. */
export interface SettingsDefaults {
  baseline_hours: Record<string, number>;
  projects_page_size: number;
}

export interface ProjectResponse {
  project: CompilationProject;
  spec_markdown: Record<string, string>;
  time_saved: TimeSavedReport | null;
  // slug → structural Mermaid source, built deterministically from the current
  // specs (a preview of what graph approval will build).
  diagrams: Record<string, string>;
}

// --- Conversational spec resolution ---------------------------------------

export type QuestionStatus = "pending" | "answered" | "parked" | "skipped";

export interface DialogueQuestion {
  question_id: string;
  slug: string;
  text: string;
  origin: "finding" | "open_question";
  severity: Severity;
  section: string | null;
  covers: string[];
  status: QuestionStatus;
  answer: string | null;
  followups: string[];
  changes: string[];
  parked_as: string | null;
}

export interface DialogueSession {
  session_id: string;
  questions: DialogueQuestion[];
  cursor: number;
  applied_specs: string[];
  created_at: string;
  updated_at: string;
}

export interface DialogueResponse {
  project: CompilationProject;
  session: DialogueSession | null;
  question: DialogueQuestion | null;
  /** Exact text to show: the open clarifying follow-up, else the question. */
  prompt: string | null;
  answered: number;
  total: number;
  remaining: number;
  changes: string[];
  parked_as: string | null;
  warnings: string[];
  spec_markdown: Record<string, string>;
}

export type ChatTurnStatus = "applied" | "clarifying" | "parked" | "no_change";

export interface SpecChatTurn {
  turn_id: string;
  role: "user" | "assistant";
  text: string;
  slug: string | null;
  /** Set on assistant turns only. */
  status: ChatTurnStatus | null;
  changes: string[];
  parked_as: string | null;
  warnings: string[];
  created_at: string;
}

export interface SpecChatSession {
  session_id: string;
  turns: SpecChatTurn[];
  pending_instruction: string | null;
  pending_question: string | null;
  pending_slug: string | null;
  applied_specs: string[];
  created_at: string;
  updated_at: string;
}

export interface SpecChatResponse {
  project: CompilationProject;
  session: SpecChatSession | null;
  reply: string | null;
  status: ChatTurnStatus | null;
  slug: string | null;
  changes: string[];
  parked_as: string | null;
  warnings: string[];
  /** True when the next message is read as a reply to a clarifying question. */
  awaiting_clarification: boolean;
  applied: number;
  spec_markdown: Record<string, string>;
}

export interface CvpaPreviewResponse {
  slug: string;
  diagram: string;
}

export type JobKind = "validate" | "approve";
export type JobStatus = "running" | "succeeded" | "failed" | "canceled";

/**
 * A background validate/approve run. Lives server-side, so it survives the user
 * navigating away or refreshing; `project` is embedded only when the run has
 * succeeded (from `GET /jobs/{id}`), never in the list.
 */
export interface Job {
  job_id: string;
  project_id: string;
  kind: JobKind;
  status: JobStatus;
  error: string | null;
  created_at: string;
  updated_at: string;
  project: ProjectResponse | null;
}

/** Parameters for starting a background run (approve-only fields ignored for validate). */
export interface JobStartBody {
  kind: JobKind;
  spec_markdown?: Record<string, string>;
  workflows?: string[];
  reviewer?: string;
  accept_incomplete?: boolean;
  allow_unconfirmed_references?: boolean;
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

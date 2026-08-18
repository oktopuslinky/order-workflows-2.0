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

/**
 * A candidate answer offered alongside a question. Picking one is a shortcut for
 * typing it: the label is sent as the answer and interpreted the same way, so
 * there is no second apply path and nothing stored that can go stale.
 */
export interface SuggestedOption {
  label: string;
  detail: string;
}

export interface DialogueQuestion {
  question_id: string;
  slug: string;
  text: string;
  origin: "finding" | "open_question";
  severity: Severity;
  section: string | null;
  covers: string[];
  options: SuggestedOption[];
  status: QuestionStatus;
  answer: string | null;
  /** Label of a suggestion accepted verbatim; null when the user wrote their own. */
  chosen_option: string | null;
  followups: string[];
  followup_options: SuggestedOption[];
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
  /** The options belonging to `prompt`. Often empty. */
  options: SuggestedOption[];
  /** Questions are drafted and waiting, so starting a session is instant. */
  prepared: boolean;
  /** A background drafting run is in flight — say so rather than showing nothing. */
  preparing: boolean;
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
  /** Candidate replies, on CLARIFYING assistant turns. */
  options: SuggestedOption[];
  /** On a user turn: the suggestion accepted verbatim, if any. */
  chosen_option: string | null;
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
  /** Candidate replies to the open clarifying question. Empty unless one is open. */
  options: SuggestedOption[];
  /** True when the next message is read as a reply to a clarifying question. */
  awaiting_clarification: boolean;
  applied: number;
  spec_markdown: Record<string, string>;
}

export interface CvpaPreviewResponse {
  slug: string;
  diagram: string;
}

export type JobKind =
  | "validate"
  | "approve"
  | "predraft"
  | "kb_ingest"
  | "cr_questions"
  | "cr_draft"
  | "cr_revise";
export type JobStatus = "running" | "succeeded" | "failed" | "canceled";
/** What a job belongs to: a project, a knowledge base (kb_ingest), or a change request (cr_*). */
export type JobScopeKind = "project" | "knowledge_base" | "change_request";

export interface JobProgress {
  message: string;
  done: number;
  total: number;
}

/**
 * A background validate/approve run. Lives server-side, so it survives the user
 * navigating away or refreshing; `project` is embedded only when the run has
 * succeeded (from `GET /jobs/{id}`), never in the list.
 */
export interface Job {
  job_id: string;
  /** The job's scope id (= scope_id; a kb id for knowledge-base jobs). */
  project_id: string;
  scope_id: string;
  scope_kind: JobScopeKind;
  kind: JobKind;
  status: JobStatus;
  error: string | null;
  created_at: string;
  updated_at: string;
  progress: JobProgress | null;
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

// --- Running generated bundles (docs/RUN_WORKFLOWS_HANDOFF.md §5) ---

export interface TemporalHealth {
  reachable: boolean;
  address: string;
  detail: string | null;
}

export interface WorkflowInputField {
  name: string;
  /** Declared annotation: str, int, float, bool, dict, list. */
  type: string;
  /** The literal the generator puts in starter.py — reused as the form default
   *  so the form and the bundle cannot drift apart. */
  sample: string;
}

export interface SignalDescriptor {
  /** As the *spec* names it. Signalling the snake_cased method does nothing. */
  name: string;
  params: string[];
}

export interface RunnableWorkflow {
  slug: string;
  workflow_id: string;
  workflow_type: string;
  task_queue: string;
  runnable: boolean;
  bundle_dir: string | null;
  materialized: boolean;
  inputs: WorkflowInputField[];
  signals: SignalDescriptor[];
}

export interface RunnableListResponse {
  temporal: TemporalHealth;
  workflows: RunnableWorkflow[];
}

/** `compensated` is deliberately distinct from `failed`: the saga rolled back
 *  cleanly, which is the workflow doing its job. */
export type RunState =
  | "running"
  | "completed"
  | "failed"
  | "compensated"
  | "terminated"
  | "timed_out"
  | "canceled";

export interface RunEvent {
  at: string | null;
  kind: string;
  detail: string;
}

export interface Run {
  run_id: string;
  project_id: string;
  slug: string;
  workflow_id: string;
  execution_run_id: string;
  task_queue: string;
  state: RunState;
  result: string | null;
  error: string | null;
  current_step: string | null;
  events: RunEvent[];
  created_at: string;
  bundle_written: string[];
  bundle_kept: string[];
}

// --------------------------------------------------------------------------- //
// Knowledge bases
// --------------------------------------------------------------------------- //

export type KnowledgeBaseStatus = "ingesting" | "ready" | "failed";

export interface KbStats {
  nodes: number;
  edges: number;
  by_type: Record<string, number>;
  edges_by_type: Record<string, number>;
  files: number;
}

export interface KbCatalog {
  epics: string[];
  stories: string[];
  test_cases: string[];
  requirements: string[];
}

export interface KnowledgeBase {
  kb_id: string;
  name: string;
  owner_id: string | null;
  source: { kind: "zip" | "path"; filename: string | null };
  status: KnowledgeBaseStatus;
  error: string | null;
  stats: KbStats;
  indexed_at: string | null;
  llm_enriched: boolean;
  provider_used: string | null;
  model_used: string | null;
  catalog: KbCatalog;
  warnings: string[];
  created_at: string;
  updated_at: string;
  /** The ingest job that is running (or was just started), if any. */
  job: Job | null;
}

export interface KnowledgeBaseListResponse {
  knowledge_bases: KnowledgeBase[];
}

export interface KgSection {
  band: string;
  node_id: string;
  text: string;
  tokens: number;
  path: string | null;
  start_line: number | null;
  end_line: number | null;
}

export interface KgFileRef {
  path: string;
  band: string;
  tokens: number;
  node_ids: string[];
  spans: [number, number][];
}

export interface KgPacket {
  prompt: string;
  seeds: string[];
  focus_domain: string | null;
  rendered: string;
  sections: KgSection[];
  files: KgFileRef[];
  total_tokens: number;
  band_budgets: Record<string, number>;
  coverage: number;
  uncovered_terms: string[];
  low_confidence: boolean;
  refinement_rounds: number;
}

export interface KbRetrieveResponse {
  kb_id: string;
  packet: KgPacket;
}

export interface KgImpactRow {
  node_id: string;
  type: string;
  name: string;
  path: string | null;
  hops: number;
  via: string;
}

export interface KbImpactResponse {
  kb_id: string;
  seeds: string[];
  max_hops: number;
  rows: KgImpactRow[];
}

export interface KgSearchHit {
  node_id: string;
  type: string;
  name: string;
  path: string | null;
  score: number;
}

export interface KbSearchResponse {
  kb_id: string;
  query: string;
  hits: KgSearchHit[];
}

export interface KbFileListResponse {
  kb_id: string;
  files: string[];
}

export interface KbFileResponse {
  kb_id: string;
  path: string;
  size: number;
  text: string;
  extracted: boolean;
}

export interface KgNodeBrief {
  node_id: string;
  type: string;
  name: string;
  degree: number;
}

export interface KbGraphSummary {
  nodes: number;
  edges: number;
  by_type: Record<string, number>;
  edges_by_type: Record<string, number>;
  top_nodes: KgNodeBrief[];
}

export interface KbGraphSummaryResponse {
  kb_id: string;
  summary: KbGraphSummary;
}

// ---------------------------------------------------------------- change requests

export type ChangeStepKind = "impact" | "epic" | "stories" | "tdd";
export type ChangeStage = "created" | "in_progress" | "complete";
export type WizardStepStatus = "pending" | "asking" | "drafting" | "drafted" | "approved";
export type ArtifactStatus = "empty" | "drafted" | "approved";
export type ArtifactSource = "llm_draft" | "llm_revision" | "human_edit";

export interface ChangeRequestSummary {
  cr_id: string;
  kb_id: string;
  kb_name: string;
  title: string;
  doc_id: string;
  stage: ChangeStage;
  cursor: number;
  current_step: ChangeStepKind | null;
  owner_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChangeRequestListResponse {
  change_requests: ChangeRequestSummary[];
}

export interface BcrMeta {
  doc_id: string;
  status: string;
  requested_by: string;
  date_raised: string;
  target_workflow: string;
}

export interface CrRequirement {
  id: string;
  text: string;
}

export interface CrImpactRow {
  node_id: string;
  type: string;
  name: string;
  path: string | null;
  hops: number;
  via: string;
}

export interface CrIds {
  epic_id: string | null;
  story_ids: string[];
  tdd_id: string | null;
  next_test_case: string | null;
  prior_epic_id: string | null;
  prior_tdd_id: string | null;
}

export interface WizardQuestion {
  question_id: string;
  text: string;
  why: string;
  options: SuggestedOption[];
  status: "pending" | "answered" | "skipped";
  answer: string | null;
  chosen_option: string | null;
  followups: string[];
  followup_options: SuggestedOption[];
  note: string | null;
}

export type ChatTurnKind =
  | "question"
  | "answer"
  | "followup"
  | "note"
  | "draft"
  | "revision"
  | "edit"
  | "approve"
  | "status"
  | "message";

export interface ChatTurn {
  role: "assistant" | "user" | "system";
  text: string;
  kind: ChatTurnKind;
  at: string;
}

export interface WizardStep {
  kind: ChangeStepKind;
  status: WizardStepStatus;
  questions: WizardQuestion[];
  notes: string[];
  turns: ChatTurn[];
  error: string | null;
  started_at: string | null;
  drafted_at: string | null;
  approved_at: string | null;
}

export interface WizardState {
  steps: WizardStep[];
  cursor: number;
  provider: string | null;
  model: string | null;
  started_at: string | null;
  updated_at: string | null;
}

export interface ArtifactVersion {
  version: number;
  markdown: string;
  source: ArtifactSource;
  note: string | null;
  at: string;
}

export interface SourceRef {
  path: string;
  spans: [number, number][];
}

export interface Artifact {
  kind: ChangeStepKind;
  markdown: string;
  version: number;
  status: ArtifactStatus;
  history: ArtifactVersion[];
  sources: SourceRef[];
  coverage: number | null;
  approved_at: string | null;
}

export interface ChangeRequest {
  cr_id: string;
  kb_id: string;
  kb_name: string;
  owner_id: string | null;
  title: string;
  document_text: string;
  source_filename: string | null;
  bcr_meta: BcrMeta;
  requirements: CrRequirement[];
  impact_seed_terms: string[];
  impact_table: CrImpactRow[];
  ids: CrIds;
  wizard: WizardState;
  artifacts: Record<ChangeStepKind, Artifact>;
  project_ids: string[];
  stage: ChangeStage;
  warnings: string[];
  created_at: string;
  updated_at: string;
}

export interface ChangeRequestResponse {
  change_request: ChangeRequest;
  current_step: ChangeStepKind | null;
  question: string | null;
  question_options: SuggestedOption[];
  job: Job | null;
}

export interface ArtifactResponse {
  cr_id: string;
  kind: ChangeStepKind;
  version: number;
  status: ArtifactStatus;
  markdown: string;
  requested_version: number | null;
  history: ArtifactVersion[];
  sources: SourceRef[];
  coverage: number | null;
}

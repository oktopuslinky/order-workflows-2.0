// Typed fetch client for the workflow-compiler FastAPI backend.
// The browser talks to the origin directly (CORS is enabled server-side).

import type {
  ArtifactResponse,
  ChangeRequestListResponse,
  ChangeRequestResponse,
  ChangeRequestSummary,
  ChangeStepKind,
  CvpaPreviewResponse,
  DialogueResponse,
  SpecChatResponse,
  EditPreviewResponse,
  Job,
  JobStartBody,
  KbFileListResponse,
  KbFileResponse,
  KbGraphSummary,
  KbGraphSummaryResponse,
  KbImpactResponse,
  KbRetrieveResponse,
  KbSearchResponse,
  KnowledgeBase,
  KnowledgeBaseListResponse,
  LocalModelList,
  MetricsSummary,
  ProjectFilesResponse,
  ProjectListResponse,
  ProjectResponse,
  ProjectSummary,
  ResolvedEdit,
  Run,
  RunnableListResponse,
  SettingsDefaults,
  UserPreferences,
  WorkflowStateResponse,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    // credentials: session auth rides an HttpOnly cookie on every call.
    response = await fetch(`${API_BASE}${path}`, { credentials: "include", ...init });
  } catch {
    throw new ApiError(
      0,
      `Cannot reach the backend at ${API_BASE}. Is it running (uvicorn workflow_compiler.api.app:app)?`,
    );
  }
  if (!response.ok) {
    const detail = await extractDetail(response);
    // An expired session on an app call sends the user back to sign in.
    // Auth endpoints handle their own 401s (login failure, me-probe).
    if (
      response.status === 401 &&
      !path.startsWith("/auth/") &&
      typeof window !== "undefined" &&
      window.location.pathname !== "/login"
    ) {
      window.location.assign(
        `/login?next=${encodeURIComponent(window.location.pathname)}`,
      );
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

async function extractDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail
        .map((d: { msg?: string }) => d.msg ?? JSON.stringify(d))
        .join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

const jsonHeaders = { "Content-Type": "application/json" };

export interface UserPublic {
  user_id: string;
  email: string;
  display_name: string;
  preferences: UserPreferences;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  me: () => request<UserPublic>("/auth/me"),

  login: (email: string, password: string) =>
    request<UserPublic>("/auth/login", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ email, password }),
    }),

  register: (email: string, password: string, displayName: string) =>
    request<UserPublic>("/auth/register", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        email,
        password,
        display_name: displayName,
      }),
    }),

  logout: () => request<{ status: string }>("/auth/logout", { method: "POST" }),

  updateProfile: (update: {
    display_name?: string;
    preferences?: UserPreferences;
  }) =>
    request<UserPublic>("/auth/me", {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify({
        display_name: update.display_name ?? null,
        preferences: update.preferences ?? null,
      }),
    }),

  settingsDefaults: () => request<SettingsDefaults>("/settings/defaults"),

  listProjects: () => request<ProjectListResponse>("/projects"),

  renameProject: (id: string, nickname: string | null) =>
    request<ProjectSummary>(`/projects/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify({ nickname }),
    }),

  metricsSummary: () => request<MetricsSummary>("/metrics/summary"),

  // `probe` costs a one-token generation per model on a single-GPU box, so it
  // is only ever sent when the user explicitly asks to check availability.
  listLocalModels: (probe = false) =>
    request<LocalModelList>(
      `/providers/local/models${probe ? "?probe=true" : ""}`,
    ),

  getProject: (id: string) =>
    request<ProjectResponse>(`/projects/${encodeURIComponent(id)}`),

  compileText: (
    documentText: string,
    persist = true,
    model?: string,
    nickname?: string,
    provider?: string,
  ) =>
    request<ProjectResponse>("/projects/compile", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        document_text: documentText,
        persist,
        provider: provider || null,
        model: model || null,
        nickname: nickname || null,
      }),
    }),

  compileUpload: (
    file: File,
    persist = true,
    model?: string,
    nickname?: string,
    provider?: string,
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("persist", String(persist));
    if (provider) form.append("provider", provider);
    if (model) form.append("model", model);
    if (nickname) form.append("nickname", nickname);
    return request<ProjectResponse>("/projects/compile-upload", {
      method: "POST",
      body: form,
    });
  },

  saveSpec: (id: string, specMarkdown: Record<string, string>) =>
    request<ProjectResponse>(`/projects/${encodeURIComponent(id)}/spec`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify({ spec_markdown: specMarkdown }),
    }),

  editProject: (
    id: string,
    editDocument: string,
    opts: { workflows?: string[]; author?: string; resolved?: ResolvedEdit } = {},
  ) =>
    request<ProjectResponse>(`/projects/${encodeURIComponent(id)}/edit`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        edit_document: editDocument,
        workflows: opts.workflows ?? null,
        author: opts.author ?? null,
        resolved: opts.resolved ?? null,
      }),
    }),

  previewEdit: (
    id: string,
    editDocument: string,
    opts: { workflows?: string[] } = {},
  ) =>
    request<EditPreviewResponse>(
      `/projects/${encodeURIComponent(id)}/edit/preview`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({
          edit_document: editDocument,
          workflows: opts.workflows ?? null,
        }),
      },
    ),

  validate: (id: string, specMarkdown?: Record<string, string>) =>
    request<ProjectResponse>(`/projects/${encodeURIComponent(id)}/validate`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ spec_markdown: specMarkdown ?? {} }),
    }),

  approve: (
    id: string,
    opts: {
      specMarkdown?: Record<string, string>;
      workflows?: string[];
      reviewer?: string;
      acceptIncomplete?: boolean;
      allowUnconfirmedReferences?: boolean;
    } = {},
  ) =>
    request<ProjectResponse>(`/projects/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        spec_markdown: opts.specMarkdown ?? {},
        workflows: opts.workflows ?? null,
        reviewer: opts.reviewer ?? null,
        accept_incomplete: opts.acceptIncomplete ?? false,
        allow_unconfirmed_references: opts.allowUnconfirmedReferences ?? false,
      }),
    }),

  // Conversational spec resolution. Each answer is one LLM round trip and is
  // applied immediately, so these stay plain synchronous calls (no job needed).
  getDialogue: (id: string) =>
    request<DialogueResponse>(`/projects/${encodeURIComponent(id)}/dialogue`),

  startDialogue: (id: string) =>
    request<DialogueResponse>(`/projects/${encodeURIComponent(id)}/dialogue`, {
      method: "POST",
    }),

  answerDialogue: (id: string, answer: string, option?: string | null) =>
    request<DialogueResponse>(
      `/projects/${encodeURIComponent(id)}/dialogue/answer`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ answer, option: option ?? null }),
      },
    ),

  // Draft the questions in the background so opening Resolve is instant. Safe to
  // call whenever the tab opens: the server no-ops when an agenda is already
  // waiting, already being drafted, or there is nothing to ask.
  prepareDialogue: (id: string) =>
    request<DialogueResponse>(
      `/projects/${encodeURIComponent(id)}/dialogue/prepare`,
      { method: "POST" },
    ),

  skipDialogue: (id: string) =>
    request<DialogueResponse>(
      `/projects/${encodeURIComponent(id)}/dialogue/skip`,
      { method: "POST" },
    ),

  endDialogue: (id: string) =>
    request<DialogueResponse>(`/projects/${encodeURIComponent(id)}/dialogue`, {
      method: "DELETE",
    }),

  // Free-form spec chat — the other door to the same gate. POST opens a session
  // implicitly, so there is no separate start call.
  getSpecChat: (id: string) =>
    request<SpecChatResponse>(`/projects/${encodeURIComponent(id)}/chat`),

  sendSpecChat: (
    id: string,
    message: string,
    slug?: string | null,
    option?: string | null,
  ) =>
    request<SpecChatResponse>(`/projects/${encodeURIComponent(id)}/chat`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        message,
        slug: slug ?? null,
        option: option ?? null,
      }),
    }),

  endSpecChat: (id: string) =>
    request<SpecChatResponse>(`/projects/${encodeURIComponent(id)}/chat`, {
      method: "DELETE",
    }),

  // Background runs (validate/approve). Start returns immediately; the run keeps
  // going server-side after navigation. Poll listJobs / getJob, cancel to stop.
  startJob: (id: string, body: JobStartBody) =>
    request<Job>(`/projects/${encodeURIComponent(id)}/jobs`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    }),

  listJobs: (projectId?: string) =>
    request<Job[]>(
      `/jobs${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`,
    ),

  // ---- knowledge bases -------------------------------------------------- //
  // A corpus zip becomes a Context Hub graph; indexing runs as a kb_ingest job
  // (poll listJobs / getJob, or the KB itself until status is "ready").
  listKnowledgeBases: () =>
    request<KnowledgeBaseListResponse>("/knowledge-bases").then(
      (r) => r.knowledge_bases,
    ),
  getKnowledgeBase: (id: string) =>
    request<KnowledgeBase>(`/knowledge-bases/${encodeURIComponent(id)}`),
  createKnowledgeBase: (
    file: File,
    opts: { name?: string; enrich?: boolean; provider?: string; model?: string } = {},
  ) => {
    const form = new FormData();
    form.append("file", file);
    if (opts.name) form.append("name", opts.name);
    if (opts.enrich !== undefined) form.append("enrich", String(opts.enrich));
    if (opts.provider) form.append("provider", opts.provider);
    if (opts.model) form.append("model", opts.model);
    return request<KnowledgeBase>("/knowledge-bases", { method: "POST", body: form });
  },
  deleteKnowledgeBase: (id: string) =>
    request<{ status: string }>(`/knowledge-bases/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  reindexKnowledgeBase: (
    id: string,
    body: { enrich?: boolean; provider?: string; model?: string } = {},
  ) =>
    request<KnowledgeBase>(`/knowledge-bases/${encodeURIComponent(id)}/reindex`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    }),
  retrieveFromKnowledgeBase: (
    id: string,
    prompt: string,
    opts: { budget?: number; maxHops?: number } = {},
  ) =>
    request<KbRetrieveResponse>(`/knowledge-bases/${encodeURIComponent(id)}/retrieve`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        prompt,
        budget: opts.budget ?? null,
        max_hops: opts.maxHops ?? 2,
      }),
    }),
  knowledgeBaseImpact: (id: string, seeds: string[], maxHops = 2) => {
    const params = new URLSearchParams();
    for (const s of seeds) params.append("seed", s);
    params.set("max_hops", String(maxHops));
    return request<KbImpactResponse>(
      `/knowledge-bases/${encodeURIComponent(id)}/impact?${params.toString()}`,
    );
  },
  knowledgeBaseSearch: (id: string, q: string, k = 10) =>
    request<KbSearchResponse>(
      `/knowledge-bases/${encodeURIComponent(id)}/search?q=${encodeURIComponent(q)}&k=${k}`,
    ),
  knowledgeBaseFiles: (id: string) =>
    request<KbFileListResponse>(`/knowledge-bases/${encodeURIComponent(id)}/files`).then(
      (r) => r.files,
    ),
  knowledgeBaseFile: (id: string, path: string) =>
    request<KbFileResponse>(
      `/knowledge-bases/${encodeURIComponent(id)}/files?path=${encodeURIComponent(path)}`,
    ),
  knowledgeBaseGraphSummary: (id: string, top = 15): Promise<KbGraphSummary> =>
    request<KbGraphSummaryResponse>(
      `/knowledge-bases/${encodeURIComponent(id)}/graph/summary?top=${top}`,
    ).then((r) => r.summary),

  // ---- change requests --------------------------------------------------- //
  // A BCR document grounded in a knowledge base, walked through the wizard
  // (impact → epic → stories → tdd). Slow steps run as cr_* jobs; answers are
  // synchronous LLM calls.
  listChangeRequests: () =>
    request<ChangeRequestListResponse>("/change-requests").then(
      (r): ChangeRequestSummary[] => r.change_requests,
    ),
  getChangeRequest: (id: string) =>
    request<ChangeRequestResponse>(`/change-requests/${encodeURIComponent(id)}`),
  createChangeRequest: (opts: {
    kbId: string;
    file?: File | null;
    text?: string;
    title?: string;
    provider?: string;
    model?: string;
  }) => {
    const form = new FormData();
    form.append("kb_id", opts.kbId);
    if (opts.file) form.append("file", opts.file);
    else if (opts.text) form.append("text", opts.text);
    if (opts.title) form.append("title", opts.title);
    if (opts.provider) form.append("provider", opts.provider);
    if (opts.model) form.append("model", opts.model);
    return request<ChangeRequestResponse>("/change-requests", { method: "POST", body: form });
  },
  deleteChangeRequest: (id: string) =>
    request<{ status: string }>(`/change-requests/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  startChangeWizard: (id: string, body: { provider?: string; model?: string } = {}) =>
    request<ChangeRequestResponse>(
      `/change-requests/${encodeURIComponent(id)}/wizard/start`,
      { method: "POST", headers: jsonHeaders, body: JSON.stringify(body) },
    ),
  answerChangeWizard: (id: string, answer: string, option?: string | null) =>
    request<ChangeRequestResponse>(
      `/change-requests/${encodeURIComponent(id)}/wizard/answer`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ answer, option: option ?? null }),
      },
    ),
  skipChangeWizard: (id: string) =>
    request<ChangeRequestResponse>(
      `/change-requests/${encodeURIComponent(id)}/wizard/skip`,
      { method: "POST" },
    ),
  draftChangeWizard: (id: string, step?: ChangeStepKind) =>
    request<ChangeRequestResponse>(
      `/change-requests/${encodeURIComponent(id)}/wizard/draft`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ step: step ?? null }),
      },
    ),
  reviseChangeWizard: (id: string, step: ChangeStepKind, message: string) =>
    request<ChangeRequestResponse>(
      `/change-requests/${encodeURIComponent(id)}/wizard/revise`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ step, message }),
      },
    ),
  getChangeArtifact: (id: string, kind: ChangeStepKind, version?: number) =>
    request<ArtifactResponse>(
      `/change-requests/${encodeURIComponent(id)}/artifacts/${kind}${
        version !== undefined ? `?version=${version}` : ""
      }`,
    ),
  updateChangeArtifact: (id: string, kind: ChangeStepKind, markdown: string, note?: string) =>
    request<ArtifactResponse>(
      `/change-requests/${encodeURIComponent(id)}/artifacts/${kind}`,
      {
        method: "PUT",
        headers: jsonHeaders,
        body: JSON.stringify({ markdown, note: note ?? "" }),
      },
    ),
  approveChangeArtifact: (id: string, kind: ChangeStepKind) =>
    request<ChangeRequestResponse>(
      `/change-requests/${encodeURIComponent(id)}/artifacts/${kind}/approve`,
      { method: "POST" },
    ),

  getJob: (jobId: string) => request<Job>(`/jobs/${encodeURIComponent(jobId)}`),

  cancelJob: (jobId: string) =>
    request<Job>(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),

  classifyCvpa: (id: string, workflow: string) =>
    request<CvpaPreviewResponse>(`/projects/${encodeURIComponent(id)}/cvpa`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ workflow }),
    }),

  projectFiles: (id: string) =>
    request<ProjectFilesResponse>(`/projects/${encodeURIComponent(id)}/files`),

  getWorkflow: (workflowId: string) =>
    request<WorkflowStateResponse>(
      `/workflow/${encodeURIComponent(workflowId)}`,
    ),

  approveWorkflow: (workflowId: string, reviewer?: string) =>
    request<WorkflowStateResponse>("/approve", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ workflow_id: workflowId, reviewer: reviewer ?? null }),
    }),

  rejectWorkflow: (workflowId: string, reason?: string, reviewer?: string) =>
    request<WorkflowStateResponse>("/reject", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        workflow_id: workflowId,
        reason: reason ?? null,
        reviewer: reviewer ?? null,
      }),
    }),

  // --- running generated bundles ---

  runnable: (id: string) =>
    request<RunnableListResponse>(`/projects/${encodeURIComponent(id)}/runnable`),

  startRun: (id: string, slug: string, input: Record<string, unknown>) =>
    request<Run>(`/projects/${encodeURIComponent(id)}/runs`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ slug, input }),
    }),

  listRuns: (id: string) =>
    request<Run[]>(`/projects/${encodeURIComponent(id)}/runs`),

  getRun: (runId: string) => request<Run>(`/runs/${encodeURIComponent(runId)}`),

  // One entry per declared parameter — a single object where several are
  // expected raises TypeError inside the handler and fails the workflow task.
  signalRun: (runId: string, name: string, args: unknown[]) =>
    request<Run>(`/runs/${encodeURIComponent(runId)}/signal`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name, args }),
    }),

  terminateRun: (runId: string) =>
    request<Run>(`/runs/${encodeURIComponent(runId)}`, { method: "DELETE" }),
};

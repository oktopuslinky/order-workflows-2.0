// Typed fetch client for the workflow-compiler FastAPI backend.
// The browser talks to the origin directly (CORS is enabled server-side).

import type {
  CvpaPreviewResponse,
  DialogueResponse,
  EditPreviewResponse,
  Job,
  JobStartBody,
  LocalModelList,
  MetricsSummary,
  ProjectFilesResponse,
  ProjectListResponse,
  ProjectResponse,
  ProjectSummary,
  ResolvedEdit,
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

  listLocalModels: () =>
    request<LocalModelList>("/providers/local/models"),

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

  answerDialogue: (id: string, answer: string) =>
    request<DialogueResponse>(
      `/projects/${encodeURIComponent(id)}/dialogue/answer`,
      { method: "POST", headers: jsonHeaders, body: JSON.stringify({ answer }) },
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
};

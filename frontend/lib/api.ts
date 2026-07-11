// Typed fetch client for the workflow-compiler FastAPI backend.
// The browser talks to the origin directly (CORS is enabled server-side).

import type {
  CvpaPreviewResponse,
  ProjectFilesResponse,
  ProjectResponse,
  WorkflowStateResponse,
} from "./types";

export interface ProjectIdList {
  project_ids: string[];
}

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
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(
      0,
      `Cannot reach the backend at ${API_BASE}. Is it running (uvicorn workflow_compiler.api.app:app)?`,
    );
  }
  if (!response.ok) {
    const detail = await extractDetail(response);
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

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  listProjects: () => request<ProjectIdList>("/projects"),

  getProject: (id: string) =>
    request<ProjectResponse>(`/projects/${encodeURIComponent(id)}`),

  compileText: (documentText: string, persist = true) =>
    request<ProjectResponse>("/projects/compile", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ document_text: documentText, persist }),
    }),

  compileUpload: (file: File, persist = true) => {
    const form = new FormData();
    form.append("file", file);
    form.append("persist", String(persist));
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

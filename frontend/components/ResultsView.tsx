"use client";

import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { saveAs } from "file-saver";
import JSZip from "jszip";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { MermaidView } from "./MermaidView";
import type { CompilationProject, WorkflowState } from "@/lib/types";

export function ResultsView({
  project,
  onRefetch,
}: {
  project: CompilationProject;
  onRefetch: () => void;
}) {
  const slugs = Object.keys(project.workflow_ids);
  const [active, setActive] = useState(slugs[0] ?? "");

  const states = useQueries({
    queries: slugs.map((slug) => ({
      queryKey: ["workflow", project.workflow_ids[slug]],
      queryFn: () => api.getWorkflow(project.workflow_ids[slug]),
    })),
  });
  const stateBySlug: Record<string, WorkflowState | undefined> = {};
  slugs.forEach((slug, i) => {
    stateBySlug[slug] = states[i].data?.state;
  });

  const files = useQuery({
    queryKey: ["projectFiles", project.project_id, project.updated_at],
    queryFn: () => api.projectFiles(project.project_id),
  });

  async function downloadZip() {
    if (!files.data) return;
    const zip = new JSZip();
    for (const f of files.data.files) zip.file(f.path, f.content);
    const blob = await zip.generateAsync({ type: "blob" });
    saveAs(blob, `${project.project_id.slice(0, 8)}-temporal.zip`);
  }

  if (slugs.length === 0) {
    return (
      <p className="p-4 text-sm text-slate-500">
        No compiled workflows yet. Approve the specs to generate code.
      </p>
    );
  }

  const state = stateBySlug[active];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2 dark:border-slate-800">
        <div className="flex flex-wrap gap-1">
          {slugs.map((slug) => (
            <button
              key={slug}
              onClick={() => setActive(slug)}
              className={`rounded px-2 py-1 text-xs ${
                slug === active
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
              }`}
            >
              {slug}
            </button>
          ))}
        </div>
        <button
          onClick={downloadZip}
          disabled={!files.data}
          className="ml-auto rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900"
        >
          Download .zip
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {state?.approval_status === "pending" && (
          <PendingOverrideCard state={state} onRefetch={onRefetch} />
        )}
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase text-slate-500">
              Diagram
            </h4>
            <div className="rounded-lg border border-slate-200 bg-white p-2 dark:border-slate-800 dark:bg-slate-900">
              <MermaidView source={state?.mermaid_diagram?.source ?? ""} />
            </div>
            <ReviewCVPA state={state} />
          </div>
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase text-slate-500">
              Generated files
            </h4>
            <CodeFiles files={state?.temporal_code?.files ?? []} />
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewCVPA({ state }: { state: WorkflowState | undefined }) {
  if (!state) return null;
  const health = state.review_report?.health_score;
  const assignments = state.cvpa_classification?.assignments ?? [];
  return (
    <div className="mt-3 space-y-3 text-xs">
      {health !== null && health !== undefined && (
        <p>
          <span className="text-slate-500">Graph health:</span>{" "}
          <span
            className={
              health >= 0.9 ? "text-emerald-500" : "text-amber-500"
            }
          >
            {(health * 100).toFixed(0)}%
          </span>
        </p>
      )}
      {assignments.length > 0 && (
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="py-1">Node</th>
              <th className="py-1">Phase</th>
            </tr>
          </thead>
          <tbody>
            {assignments.map((a) => (
              <tr key={a.node_id} className="border-t border-slate-200 dark:border-slate-800">
                <td className="py-1 font-mono">{a.node_id}</td>
                <td className="py-1 capitalize">{a.phase}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function CodeFiles({
  files,
}: {
  files: { path: string; content: string; language: string }[];
}) {
  const [active, setActive] = useState(0);
  if (files.length === 0) {
    return <p className="text-xs text-slate-400">No files.</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1">
        {files.map((f, i) => (
          <button
            key={f.path}
            onClick={() => setActive(i)}
            className={`rounded px-2 py-0.5 font-mono text-[11px] ${
              i === active
                ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                : "bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
            }`}
          >
            {f.path}
          </button>
        ))}
      </div>
      <pre className="max-h-[60vh] overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-800 dark:bg-slate-950">
        <code>{files[active]?.content}</code>
      </pre>
    </div>
  );
}

function PendingOverrideCard({
  state,
  onRefetch,
}: {
  state: WorkflowState;
  onRefetch: () => void;
}) {
  const approve = useMutation({
    mutationFn: () => api.approveWorkflow(state.workflow_id),
    onSuccess: onRefetch,
  });
  const reject = useMutation({
    mutationFn: () => api.rejectWorkflow(state.workflow_id, "manual reject"),
    onSuccess: onRefetch,
  });
  return (
    <div className="mb-3 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-xs">
      <p className="font-semibold text-amber-700 dark:text-amber-300">
        Below the graph-health threshold — pending manual review
      </p>
      {state.review_report?.issues?.slice(0, 4).map((issue) => (
        <p key={issue.id} className="mt-1 text-amber-700 dark:text-amber-300">
          • {issue.message}
        </p>
      ))}
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => approve.mutate()}
          disabled={approve.isPending}
          className="rounded bg-emerald-600 px-3 py-1 font-medium text-white disabled:opacity-40"
        >
          Approve anyway
        </button>
        <button
          onClick={() => reject.mutate()}
          disabled={reject.isPending}
          className="rounded bg-red-600 px-3 py-1 font-medium text-white disabled:opacity-40"
        >
          Reject
        </button>
      </div>
      {(approve.error || reject.error) && (
        <p className="mt-1 text-red-500">
          {((approve.error || reject.error) as ApiError).message}
        </p>
      )}
    </div>
  );
}

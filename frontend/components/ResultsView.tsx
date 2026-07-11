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
      <p className="p-4 text-sm text-[var(--muted)]">
        No compiled workflows yet. Approve the specs to generate code.
      </p>
    );
  }

  const state = stateBySlug[active];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {slugs.map((slug) => (
            <button
              key={slug}
              onClick={() => setActive(slug)}
              className={`cursor-pointer rounded-md border px-2 py-1 text-xs transition ${
                slug === active
                  ? "border-transparent bg-[var(--accent)] text-white"
                  : "border-[var(--border)] bg-[var(--surface-2)] text-[var(--muted)] hover:text-[var(--ink)]"
              }`}
            >
              {slug}
            </button>
          ))}
        </div>
        <button
          onClick={downloadZip}
          disabled={!files.data}
          className="btn btn-primary ml-auto"
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
            <h4 className="eyebrow mb-1.5">Diagram</h4>
            <div className="card p-2">
              <MermaidView source={state?.mermaid_diagram?.source ?? ""} />
            </div>
            <ReviewCVPA state={state} />
          </div>
          <div>
            <h4 className="eyebrow mb-1.5">Generated files</h4>
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
          <span className="text-[var(--muted)]">Graph health:</span>{" "}
          <span
            className={`font-medium ${
              health >= 0.9 ? "text-[var(--pass)]" : "text-[var(--gate)]"
            }`}
          >
            {(health * 100).toFixed(0)}%
          </span>
        </p>
      )}
      {assignments.length > 0 && (
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-left text-[var(--muted)]">
              <th className="py-1">Node</th>
              <th className="py-1">Phase</th>
            </tr>
          </thead>
          <tbody>
            {assignments.map((a) => (
              <tr key={a.node_id} className="border-t border-[var(--border)]">
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
    return <p className="text-xs text-[var(--faint)]">No files.</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1">
        {files.map((f, i) => (
          <button
            key={f.path}
            onClick={() => setActive(i)}
            className={`cursor-pointer rounded-md border px-2 py-0.5 font-mono text-[11px] transition ${
              i === active
                ? "border-transparent bg-[var(--ink)] text-[var(--paper)]"
                : "border-[var(--border)] bg-[var(--surface-2)] text-[var(--muted)] hover:text-[var(--ink)]"
            }`}
          >
            {f.path}
          </button>
        ))}
      </div>
      <pre className="max-h-[60vh] overflow-auto rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs">
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
    <div className="tone-gate mb-3 rounded-lg border p-3 text-xs">
      <p className="font-semibold">
        Below the graph-health threshold — pending manual review
      </p>
      {state.review_report?.issues?.slice(0, 4).map((issue) => (
        <p key={issue.id} className="mt-1">
          • {issue.message}
        </p>
      ))}
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => approve.mutate()}
          disabled={approve.isPending}
          className="btn btn-pass"
        >
          Approve anyway
        </button>
        <button
          onClick={() => reject.mutate()}
          disabled={reject.isPending}
          className="btn btn-danger"
        >
          Reject
        </button>
      </div>
      {(approve.error || reject.error) && (
        <p className="mt-1 text-[var(--block)]">
          {((approve.error || reject.error) as ApiError).message}
        </p>
      )}
    </div>
  );
}

"use client";

import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { saveAs } from "file-saver";
import JSZip from "jszip";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { ChangeOutputsView } from "./ChangeOutputsView";
import { FindingsPanel } from "./FindingsPanel";
import { MermaidView } from "./MermaidView";
import { RunPanel } from "./RunPanel";
import type { CompilationProject, SpecFinding, WorkflowState } from "@/lib/types";

export function ResultsView({
  project,
  onRefetch,
}: {
  project: CompilationProject;
  onRefetch: () => void;
}) {
  // Every workflow in the project, not just the ones that produced code: a
  // workflow the approve run skipped must say so, never just go missing.
  const slugs = project.specs.map((s) => s.slug);
  const compiled = slugs.filter((slug) => project.workflow_ids[slug]);
  const blockedBySlug: Record<string, SpecFinding[]> = {};
  for (const slug of slugs) {
    if (project.workflow_ids[slug]) continue;
    blockedBySlug[slug] = (project.validation_findings[slug] ?? []).filter(
      (f) => f.severity === "blocking",
    );
  }
  const blockedSlugs = slugs.filter((slug) => !project.workflow_ids[slug]);
  const [active, setActive] = useState(slugs[0] ?? "");
  // Grounded projects get a second view: the post-approval change outputs
  // (updated diagrams, modified code + diff, test documents).
  const grounded = Boolean(project.kb_id);
  const [view, setView] = useState<"workflows" | "changes">(
    grounded && project.change_outputs ? "changes" : "workflows",
  );

  const states = useQueries({
    queries: compiled.map((slug) => ({
      queryKey: ["workflow", project.workflow_ids[slug]],
      queryFn: () => api.getWorkflow(project.workflow_ids[slug]),
    })),
  });
  const stateBySlug: Record<string, WorkflowState | undefined> = {};
  compiled.forEach((slug, i) => {
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
  const blocked = blockedSlugs.includes(active);

  return (
    <div className="flex h-full flex-col">
      {grounded && (
        <div className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--surface-2)] px-3 py-1.5">
          <div className="seg">
            <button
              onClick={() => setView("workflows")}
              className={view === "workflows" ? "seg-active" : ""}
            >
              Workflows
            </button>
            <button
              onClick={() => setView("changes")}
              className={view === "changes" ? "seg-active" : ""}
            >
              Change outputs
              {project.change_outputs && (
                <span className="ml-1.5 pill tone-pass">
                  {Object.values(project.change_outputs.stages).filter((r) => r.status === "done").length}/3
                </span>
              )}
            </button>
          </div>
          <span className="text-xs text-[var(--faint)]">
            {view === "changes"
              ? "Diagrams, modified code base and test documents produced from the knowledge base after approval."
              : "Compiled Temporal code per workflow."}
          </span>
        </div>
      )}
      {grounded && view === "changes" ? (
        <ChangeOutputsView project={project} />
      ) : (
      <>
      {blockedSlugs.length > 0 && (
        <p className="tone-block border-b px-3 py-1.5 text-xs">
          No code was generated for {blockedSlugs.join(", ")} — blocked by findings
          below. The other {compiled.length} workflow
          {compiled.length === 1 ? "" : "s"} compiled.
        </p>
      )}
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
              {blockedSlugs.includes(slug) && (
                <span
                  className={`ml-1.5 ${slug === active ? "opacity-80" : "text-[var(--block)]"}`}
                >
                  blocked
                </span>
              )}
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
        {blocked ? (
          <BlockedWorkflow slug={active} findings={blockedBySlug[active] ?? []} />
        ) : (
          <>
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
                <RunPanel projectId={project.project_id} slug={active} />
              </div>
            </div>
          </>
        )}
      </div>
      </>
      )}
    </div>
  );
}

function BlockedWorkflow({
  slug,
  findings,
}: {
  slug: string;
  findings: SpecFinding[];
}) {
  return (
    <div className="mx-auto max-w-2xl">
      <div className="card tone-block p-3">
        <h4 className="text-sm font-medium">
          {slug} was not compiled — no code generated
        </h4>
        <p className="mt-1 text-xs opacity-80">
          Approve skipped this workflow because it still has{" "}
          {findings.length || "outstanding"} blocking finding
          {findings.length === 1 ? "" : "s"}. Fix them in the Spec tab and approve
          again — the other workflows keep the code they already produced.
        </p>
      </div>
      <div className="mt-3">
        <h4 className="eyebrow mb-1.5">Blocking findings</h4>
        <FindingsPanel findings={findings} />
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

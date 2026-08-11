"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useRuns } from "@/lib/runs";
import { APPROVE_STEPS, shortId, STAGE_LABEL, STAGE_TONE } from "@/lib/format";
import { DialoguePanel } from "@/components/DialoguePanel";
import { DiagramPanel } from "@/components/DiagramPanel";
import { EditHistory } from "@/components/EditHistory";
import { EditRequestPanel } from "@/components/EditRequestPanel";
import { FindingsPanel } from "@/components/FindingsPanel";
import { ResultsView } from "@/components/ResultsView";
import { RunningOverlay } from "@/components/RunningOverlay";
import { SpecEditor } from "@/components/SpecEditor";
import { SpecPreview } from "@/components/SpecPreview";
import { TimeSavedCard } from "@/components/TimeSaved";
import { WorkspaceSkeleton } from "@/components/Skeleton";
import {
  DependencyChecklist,
  EventKindEditor,
  OpenQuestions,
  TriggerCards,
  ValidateDiff,
} from "@/components/StructuredWidgets";
import type {
  CompilationProject,
  EditRecord,
  ProjectResponse,
  ProjectStage,
  ResolvedEdit,
} from "@/lib/types";

const VALIDATED_STAGES: ProjectStage[] = [
  "spec_validated",
  "spec_approved",
  "compiling",
  "completed",
];

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();

  const project = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.getProject(id),
  });

  return (
    <div className="flex h-full min-h-0 flex-col">
      {project.isLoading && <WorkspaceSkeleton />}
      {project.error && (
        <div className="p-6 text-sm text-[var(--block)]">
          {(project.error as ApiError).message}
          <div className="mt-2">
            <Link href="/" className="link-accent">
              ← Back to projects
            </Link>
          </div>
        </div>
      )}
      {project.data && (
        <Workspace
          data={project.data}
          onServerUpdate={() => project.refetch()}
        />
      )}
    </div>
  );
}

/**
 * Project identity in the action bar: the nickname (editable in place, same
 * flow as the Projects list) with the full project id alongside, so it's
 * always clear which project is open.
 */
function ProjectIdentity({
  project,
  onRenamed,
}: {
  project: CompilationProject;
  onRenamed: () => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(project.nickname ?? "");

  const rename = useMutation({
    mutationFn: (nickname: string | null) =>
      api.renameProject(project.project_id, nickname),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setEditing(false);
      onRenamed();
    },
  });

  const label = project.nickname?.trim();

  if (editing) {
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          rename.mutate(draft.trim() || null);
        }}
        className="flex min-w-0 items-center gap-1.5 rounded-md border border-[var(--accent)] px-1.5 py-0.5"
      >
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setEditing(false);
          }}
          placeholder="Project nickname"
          aria-label="Project nickname"
          className="w-44 min-w-0 bg-transparent px-1 text-sm outline-none"
        />
        <button
          type="submit"
          disabled={rename.isPending}
          className="btn btn-primary px-2 py-0.5 text-xs"
        >
          Save
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="btn btn-ghost px-2 py-0.5 text-xs"
        >
          Cancel
        </button>
        {rename.error && (
          <span className="text-xs text-[var(--block)]">
            {(rename.error as ApiError).message}
          </span>
        )}
      </form>
    );
  }

  return (
    <div className="group flex min-w-0 items-baseline gap-1.5">
      <span
        className={`truncate text-sm ${
          label
            ? "font-semibold text-[var(--ink)]"
            : "font-mono text-[var(--muted)]"
        }`}
        title={label || project.project_id}
      >
        {label || shortId(project.project_id)}
      </span>
      <button
        type="button"
        onClick={() => {
          setDraft(project.nickname ?? "");
          setEditing(true);
        }}
        aria-label={label ? `Rename ${label}` : "Name this project"}
        title="Rename"
        className="rounded-md p-1 text-[var(--faint)] transition hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
        </svg>
      </button>
      <span
        className="hidden select-all font-mono text-[11px] text-[var(--faint)] md:inline"
        title="Project id"
      >
        {project.project_id}
      </span>
    </div>
  );
}

function Workspace({
  data,
  onServerUpdate,
}: {
  data: ProjectResponse;
  onServerUpdate: () => void;
}) {
  const proj = data.project;
  const slugs = proj.specs.map((s) => s.slug);

  // Background validate/approve runs live in the global RunsProvider, so a run
  // this page started keeps going after the user navigates home and back.
  const runs = useRuns();
  const job = runs.jobForProject(proj.project_id);
  const running = job?.status === "running";

  const [buffers, setBuffers] = useState<Record<string, string>>(
    () => ({ ...data.spec_markdown }),
  );
  const [active, setActive] = useState(slugs[0] ?? "");
  const [tab, setTab] = useState<"spec" | "resolve" | "results">("spec");
  const [viewMode, setViewMode] = useState<"editor" | "preview" | "diagram">(
    "editor",
  );
  const [dirty, setDirty] = useState(
    () => !VALIDATED_STAGES.includes(proj.stage),
  );
  // Snapshot of what was sent to validate, and what came back — for the diff view.
  const [preValidate, setPreValidate] = useState<Record<string, string>>({});
  const [postValidate, setPostValidate] = useState<Record<string, string>>({});
  const [acceptIncomplete, setAcceptIncomplete] = useState(false);
  const [allowUnconfirmed, setAllowUnconfirmed] = useState(false);
  const [showEditPanel, setShowEditPanel] = useState(false);
  // The just-applied edit, for the success banner (cleared on validate/dismiss).
  const [lastEdit, setLastEdit] = useState<EditRecord | null>(null);

  // Re-seed buffers only when the set of slugs changes (a fresh project load).
  const seededFor = useRef(proj.project_id);
  useEffect(() => {
    if (seededFor.current !== proj.project_id) {
      setBuffers({ ...data.spec_markdown });
      setActive(proj.specs[0]?.slug ?? "");
      seededFor.current = proj.project_id;
    }
  }, [proj.project_id, data.spec_markdown, proj.specs]);

  function applyServer(resp: ProjectResponse) {
    setBuffers({ ...resp.spec_markdown });
  }

  const save = useMutation({
    mutationFn: () => api.saveSpec(proj.project_id, buffers),
    onSuccess: (resp) => {
      applyServer(resp);
      onServerUpdate();
    },
  });

  // Starting a run only kicks it off (it finishes in the background). The
  // result is applied by the completion effect below, keyed on the job id, so
  // it runs even if the user was on another page when the run finished.
  const startValidate = useMutation({
    mutationFn: () => {
      setPreValidate({ ...buffers });
      return runs.start(proj.project_id, { kind: "validate", spec_markdown: buffers });
    },
  });

  const editRequest = useMutation({
    mutationFn: ({
      document,
      resolved,
    }: {
      document: string;
      resolved: ResolvedEdit;
    }) => {
      // Snapshot so the diff view shows what the edit changed per spec.
      // The server attributes the edit to the signed-in account and replays
      // the previewed operations (no LLM re-interpretation).
      setPreValidate({ ...buffers });
      return api.editProject(proj.project_id, document, { resolved });
    },
    onSuccess: (resp) => {
      applyServer(resp);
      setPostValidate({ ...resp.spec_markdown });
      setDirty(true); // the edit re-arms the gate: validate must run again
      setShowEditPanel(false);
      setLastEdit(resp.project.edit_log.at(-1) ?? null);
      onServerUpdate();
    },
  });

  const startApprove = useMutation({
    mutationFn: () => {
      setPreValidate({ ...buffers });
      return runs.start(proj.project_id, {
        kind: "approve",
        spec_markdown: buffers,
        accept_incomplete: acceptIncomplete,
        allow_unconfirmed_references: allowUnconfirmed,
      });
    },
  });

  const cancelRun = useMutation({
    mutationFn: (jobId: string) => runs.cancel(jobId),
  });

  // Apply a finished run's result once, on the running → terminal edge — but
  // only for a run we actually saw in flight on this page (sawRunning). A run
  // that finished while the user was elsewhere already had the project query
  // refreshed by the RunsProvider, so we must not re-hijack the tab for it. We
  // pull the embedded ProjectResponse from GET /jobs/{id} so the diff view and
  // tab switch happen exactly as they did in the old synchronous onSuccess.
  const handledJob = useRef<string | null>(null);
  const sawRunning = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!job || job.project_id !== proj.project_id) return;
    if (job.status === "running") {
      sawRunning.current.add(job.job_id);
      return;
    }
    if (!sawRunning.current.has(job.job_id)) return;
    if (handledJob.current === job.job_id) return;
    handledJob.current = job.job_id;
    if (job.status !== "succeeded") return; // failed/canceled: nothing to apply
    api.getJob(job.job_id).then((full) => {
      if (!full.project) return;
      applyServer(full.project);
      setPostValidate({ ...full.project.spec_markdown });
      if (job.kind === "validate") {
        setDirty(false);
        setLastEdit(null);
      } else {
        setTab("results");
      }
      onServerUpdate();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.status]);

  const findings = proj.validation_findings[active] ?? [];
  const blockingCount = useMemo(
    () =>
      Object.values(proj.validation_findings)
        .flat()
        .filter((f) => f.severity === "blocking").length,
    [proj.validation_findings],
  );
  // Reachable once approval has run — including when it compiled nothing, since
  // Results is where a skipped workflow explains itself.
  const hasResults =
    proj.spec_approval_status === "approved" ||
    Object.keys(proj.workflow_ids).length > 0;
  const blockedSlugs = slugs.filter((slug) => !proj.workflow_ids[slug]);
  const starting = startValidate.isPending || startApprove.isPending;
  const busy = save.isPending || editRequest.isPending || running || starting;
  // Flow rule: Approve only after a validate has run on the current content.
  const canApprove = !dirty && !busy;
  // Cover the brief window between clicking a run and the job appearing in the
  // polled list, so the overlay never flickers off mid-start.
  const showOverlay = running || starting;

  function updateActive(md: string) {
    setBuffers((b) => ({ ...b, [active]: md }));
    setDirty(true);
  }

  function reAdd(line: string) {
    setBuffers((b) => ({ ...b, [active]: `${b[active].replace(/\n+$/, "")}\n${line}\n` }));
    setDirty(true);
  }

  const md = buffers[active] ?? "";

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Action bar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-2">
        <Link
          href="/"
          aria-label="Back to projects"
          className="rounded-md px-1.5 py-0.5 text-sm text-[var(--faint)] transition hover:bg-[var(--surface-2)] hover:text-[var(--accent)]"
        >
          ←
        </Link>
        <ProjectIdentity project={proj} onRenamed={onServerUpdate} />
        <span className={`pill ${STAGE_TONE[proj.stage]}`}>
          {STAGE_LABEL[proj.stage]}
        </span>
        {blockingCount > 0 && (
          <span className="pill tone-block">{blockingCount} blocking</span>
        )}
        <div className="seg ml-2">
          <button
            onClick={() => setTab("spec")}
            className={tab === "spec" ? "seg-active" : ""}
          >
            Spec
          </button>
          <button
            onClick={() => setTab("resolve")}
            className={tab === "resolve" ? "seg-active" : ""}
          >
            Resolve
          </button>
          <button
            onClick={() => setTab("results")}
            disabled={!hasResults}
            className={tab === "results" ? "seg-active" : ""}
          >
            Results
          </button>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setShowEditPanel(true)}
            disabled={busy}
            className="btn btn-ghost"
          >
            Edit request
          </button>
          <button
            onClick={() => save.mutate()}
            disabled={busy}
            className="btn btn-ghost"
          >
            Save
          </button>
          {running && job?.kind === "validate" ? (
            <button
              onClick={() => job && cancelRun.mutate(job.job_id)}
              disabled={cancelRun.isPending}
              className="btn btn-danger"
            >
              {cancelRun.isPending ? "Canceling…" : "Cancel validate"}
            </button>
          ) : (
            <button
              onClick={() => startValidate.mutate()}
              disabled={busy}
              className="btn btn-gate"
            >
              Validate
            </button>
          )}
          {running && job?.kind === "approve" ? (
            <button
              onClick={() => job && cancelRun.mutate(job.job_id)}
              disabled={cancelRun.isPending}
              className="btn btn-danger"
            >
              {cancelRun.isPending ? "Canceling…" : "Cancel approve"}
            </button>
          ) : (
            <button
              onClick={() => startApprove.mutate()}
              disabled={!canApprove}
              title={dirty ? "Run Validate first (approve checks the last validate)" : ""}
              className="btn btn-pass"
            >
              Approve
            </button>
          )}
        </div>
      </div>

      {lastEdit && tab === "spec" && (
        <p className="tone-pass flex items-center gap-2 border-b px-4 py-1 text-xs">
          <span>
            Edit applied —{" "}
            {Object.values(lastEdit.summary).flat().length} change
            {Object.values(lastEdit.summary).flat().length === 1 ? "" : "s"} across{" "}
            {Object.keys(lastEdit.summary).length} workflow
            {Object.keys(lastEdit.summary).length === 1 ? "" : "s"}. Review the
            diff in the right rail, then Validate.
          </span>
          <button
            onClick={() => setLastEdit(null)}
            aria-label="Dismiss"
            className="ml-auto cursor-pointer font-medium hover:opacity-70"
          >
            ×
          </button>
        </p>
      )}
      {dirty && tab === "spec" && (
        <p className="tone-gate border-b px-4 py-1 text-xs">
          Edited since last validate — Validate must run before Approve.
        </p>
      )}
      {(startApprove.error || startValidate.error || save.error || cancelRun.error) && (
        <p className="tone-block border-b px-4 py-1 text-xs">
          {
            (
              (startApprove.error ||
                startValidate.error ||
                save.error ||
                cancelRun.error) as ApiError
            ).message
          }
        </p>
      )}
      {proj.spec_approval_status === "approved" && blockedSlugs.length > 0 && (
        <p className="tone-block border-b px-4 py-1 text-xs">
          Approve skipped {blockedSlugs.join(", ")} — no code was generated for
          {blockedSlugs.length === 1 ? " it" : " them"}. Fix the blocking findings and
          approve again.
        </p>
      )}

      {showEditPanel && (
        <EditRequestPanel
          projectId={proj.project_id}
          slugs={slugs}
          editLog={proj.edit_log ?? []}
          specBefore={buffers}
          confirmBusy={editRequest.isPending}
          confirmError={
            editRequest.error ? (editRequest.error as ApiError).message : null
          }
          confirmErrorStatus={
            editRequest.error ? (editRequest.error as ApiError).status : null
          }
          onConfirm={(document, resolved) =>
            editRequest.mutate({ document, resolved })
          }
          onClose={() => setShowEditPanel(false)}
        />
      )}

      {tab === "resolve" ? (
        <div className="min-h-0 flex-1 overflow-auto p-4">
          <div className="mx-auto max-w-2xl">
            <h2 className="text-base font-semibold">Resolve open items</h2>
            <p className="mt-1 mb-4 text-sm text-[var(--muted)]">
              The compiler asks about what it could not settle from the
              document. Answer in plain language.
            </p>
            <DialoguePanel projectId={proj.project_id} />
          </div>
        </div>
      ) : tab === "results" ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-auto">
          {data.time_saved && (
            <div className="px-4 pt-3">
              <TimeSavedCard report={data.time_saved} />
            </div>
          )}
          <ResultsView project={proj} onRefetch={onServerUpdate} />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[180px_1fr_320px] grid-rows-[minmax(0,1fr)]">
          {/* Left: workflow tabs */}
          <aside className="overflow-auto border-r border-[var(--border)] p-2">
            <p className="eyebrow px-1 py-1">Workflows</p>
            {slugs.map((slug) => {
              const fc = (proj.validation_findings[slug] ?? []).filter(
                (f) => f.severity === "blocking",
              ).length;
              return (
                <button
                  key={slug}
                  onClick={() => setActive(slug)}
                  className={`mb-1 flex w-full cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-left text-xs transition ${
                    slug === active
                      ? "bg-[var(--accent-soft)] font-medium text-[var(--accent)]"
                      : "text-[var(--muted)] hover:bg-[var(--surface)] hover:text-[var(--ink)]"
                  }`}
                >
                  <span className="truncate">{slug}</span>
                  {fc > 0 && (
                    <span className="ml-1 rounded-full bg-[var(--block)] px-1 text-[10px] text-white">
                      {fc}
                    </span>
                  )}
                </button>
              );
            })}
            {proj.warnings.length > 0 && (
              <div className="tone-gate mt-3 rounded-lg border p-2 text-[11px]">
                {proj.warnings.map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </div>
            )}
          </aside>

          {/* Center: editor / preview */}
          <section className="relative flex min-h-0 flex-col bg-[var(--surface)]">
            {showOverlay && (
              <RunningOverlay
                title={job?.kind === "approve" ? "Compiling to Temporal code" : "Validating spec"}
                steps={job?.kind === "approve" ? APPROVE_STEPS : ["Folding edits", "LLM review passes"]}
                onCancel={job ? () => cancelRun.mutate(job.job_id) : undefined}
                canceling={cancelRun.isPending}
              />
            )}
            <div className="flex items-center gap-1 border-b border-[var(--border)] px-2 py-1 text-xs">
              {(["editor", "preview", "diagram"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setViewMode(mode)}
                  className={`cursor-pointer rounded-md px-2 py-0.5 capitalize transition ${
                    viewMode === mode
                      ? "bg-[var(--accent-soft)] font-semibold text-[var(--accent)]"
                      : "text-[var(--faint)] hover:text-[var(--ink)]"
                  }`}
                >
                  {mode}
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1">
              {viewMode === "preview" ? (
                <SpecPreview markdown={md} />
              ) : viewMode === "diagram" ? (
                <DiagramPanel
                  source={data.diagrams[active] ?? ""}
                  slug={active}
                  stale={dirty}
                  onClassify={() =>
                    api.classifyCvpa(proj.project_id, active).then((r) => r.diagram)
                  }
                />
              ) : (
                <SpecEditor value={md} onChange={updateActive} />
              )}
            </div>
          </section>

          {/* Right: findings + structured widgets */}
          <aside className="flex min-h-0 flex-col gap-3 overflow-auto border-l border-[var(--border)] p-3">
            <div>
              <h3 className="eyebrow mb-2">Findings</h3>
              <FindingsPanel findings={findings} />
            </div>
            <OpenQuestions markdown={md} onChange={updateActive} />
            <DependencyChecklist markdown={md} onChange={updateActive} />
            <TriggerCards markdown={md} onChange={updateActive} />
            <EventKindEditor markdown={md} onChange={updateActive} />
            <ValidateDiff
              before={preValidate[active] ?? ""}
              after={postValidate[active] ?? ""}
              onReAdd={reAdd}
            />
            <EditHistory records={proj.edit_log ?? []} />
            {data.time_saved && <TimeSavedCard report={data.time_saved} />}
            {(!canApprove || acceptIncomplete || allowUnconfirmed) && (
              <div className="card p-3 text-xs">
                <p className="eyebrow mb-2">Approve overrides</p>
                <label className="mb-1 flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={acceptIncomplete}
                    onChange={(e) => setAcceptIncomplete(e.target.checked)}
                  />
                  Accept unanswered required questions
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={allowUnconfirmed}
                    onChange={(e) => setAllowUnconfirmed(e.target.checked)}
                  />
                  Allow unconfirmed dependencies
                </label>
              </div>
            )}
            <p className="text-[11px] text-[var(--faint)]">
              The <span className="font-medium">Diagram</span> view shows this
              workflow&apos;s graph as of the last validate; run{" "}
              <span className="font-medium">Classify phases (CVPA)</span> there to
              color it. Generated code appears in Results after approval.
            </p>
          </aside>
        </div>
      )}
    </div>
  );
}

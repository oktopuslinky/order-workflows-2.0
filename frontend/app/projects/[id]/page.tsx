"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { APPROVE_STEPS, STAGE_LABEL, STAGE_TONE } from "@/lib/format";
import { DiagramPanel } from "@/components/DiagramPanel";
import { FindingsPanel } from "@/components/FindingsPanel";
import { ResultsView } from "@/components/ResultsView";
import { RunningOverlay } from "@/components/RunningOverlay";
import { SpecEditor } from "@/components/SpecEditor";
import { SpecPreview } from "@/components/SpecPreview";
import {
  DependencyChecklist,
  EventKindEditor,
  OpenQuestions,
  TriggerCards,
  ValidateDiff,
} from "@/components/StructuredWidgets";
import type { ProjectResponse, ProjectStage } from "@/lib/types";

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
      {project.isLoading && (
        <p className="p-6 text-sm text-[var(--muted)]">Loading project…</p>
      )}
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

function Workspace({
  data,
  onServerUpdate,
}: {
  data: ProjectResponse;
  onServerUpdate: () => void;
}) {
  const proj = data.project;
  const slugs = proj.specs.map((s) => s.slug);

  const [buffers, setBuffers] = useState<Record<string, string>>(
    () => ({ ...data.spec_markdown }),
  );
  const [active, setActive] = useState(slugs[0] ?? "");
  const [tab, setTab] = useState<"spec" | "results">("spec");
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

  const validate = useMutation({
    mutationFn: () => {
      setPreValidate({ ...buffers });
      return api.validate(proj.project_id, buffers);
    },
    onSuccess: (resp) => {
      applyServer(resp);
      setPostValidate({ ...resp.spec_markdown });
      setDirty(false);
      onServerUpdate();
    },
  });

  const approve = useMutation({
    mutationFn: () =>
      api.approve(proj.project_id, {
        specMarkdown: buffers,
        acceptIncomplete,
        allowUnconfirmedReferences: allowUnconfirmed,
      }),
    onSuccess: (resp) => {
      applyServer(resp);
      onServerUpdate();
      setTab("results");
    },
  });

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
  const busy = save.isPending || validate.isPending || approve.isPending;
  // Flow rule: Approve only after a validate has run on the current content.
  const canApprove = !dirty && !busy;

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
            onClick={() => setTab("results")}
            disabled={!hasResults}
            className={tab === "results" ? "seg-active" : ""}
          >
            Results
          </button>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => save.mutate()}
            disabled={busy}
            className="btn btn-ghost"
          >
            Save
          </button>
          <button
            onClick={() => validate.mutate()}
            disabled={busy}
            className="btn btn-gate"
          >
            Validate
          </button>
          <button
            onClick={() => approve.mutate()}
            disabled={!canApprove}
            title={dirty ? "Run Validate first (approve checks the last validate)" : ""}
            className="btn btn-pass"
          >
            Approve
          </button>
        </div>
      </div>

      {dirty && tab === "spec" && (
        <p className="tone-gate border-b px-4 py-1 text-xs">
          Edited since last validate — Validate must run before Approve.
        </p>
      )}
      {(approve.error || validate.error || save.error) && (
        <p className="tone-block border-b px-4 py-1 text-xs">
          {((approve.error || validate.error || save.error) as ApiError).message}
        </p>
      )}
      {proj.spec_approval_status === "approved" && blockedSlugs.length > 0 && (
        <p className="tone-block border-b px-4 py-1 text-xs">
          Approve skipped {blockedSlugs.join(", ")} — no code was generated for
          {blockedSlugs.length === 1 ? " it" : " them"}. Fix the blocking findings and
          approve again.
        </p>
      )}

      {tab === "results" ? (
        <ResultsView project={proj} onRefetch={onServerUpdate} />
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
            {(validate.isPending || approve.isPending) && (
              <RunningOverlay
                title={approve.isPending ? "Compiling to Temporal code" : "Validating spec"}
                steps={approve.isPending ? APPROVE_STEPS : ["Folding edits", "LLM review passes"]}
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

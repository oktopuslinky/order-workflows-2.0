"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { APPROVE_STEPS, STAGE_LABEL } from "@/lib/format";
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
        <p className="p-6 text-sm text-slate-500">Loading project…</p>
      )}
      {project.error && (
        <div className="p-6 text-sm text-red-500">
          {(project.error as ApiError).message}
          <div className="mt-2">
            <Link href="/" className="text-indigo-500 underline">
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
  const [showPreview, setShowPreview] = useState(false);
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
  const hasCode = Object.keys(proj.workflow_ids).length > 0;
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
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
        <Link href="/" className="text-sm text-slate-400 hover:text-indigo-500">
          ←
        </Link>
        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium dark:bg-slate-800">
          {STAGE_LABEL[proj.stage]}
        </span>
        {blockingCount > 0 && (
          <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs text-red-600 dark:text-red-300">
            {blockingCount} blocking
          </span>
        )}
        <div className="ml-2 flex overflow-hidden rounded-md border border-slate-300 text-xs dark:border-slate-700">
          <button
            onClick={() => setTab("spec")}
            className={`px-3 py-1 ${tab === "spec" ? "bg-indigo-600 text-white" : ""}`}
          >
            Spec
          </button>
          <button
            onClick={() => setTab("results")}
            disabled={!hasCode}
            className={`px-3 py-1 disabled:opacity-40 ${tab === "results" ? "bg-indigo-600 text-white" : ""}`}
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
        <p className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-1 text-xs text-amber-700 dark:text-amber-300">
          Edited since last validate — Validate must run before Approve.
        </p>
      )}
      {(approve.error || validate.error || save.error) && (
        <p className="border-b border-red-500/30 bg-red-500/10 px-4 py-1 text-xs text-red-600 dark:text-red-300">
          {((approve.error || validate.error || save.error) as ApiError).message}
        </p>
      )}

      {tab === "results" ? (
        <ResultsView project={proj} onRefetch={onServerUpdate} />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[180px_1fr_320px]">
          {/* Left: workflow tabs */}
          <aside className="overflow-auto border-r border-slate-200 p-2 dark:border-slate-800">
            <p className="px-1 py-1 text-[10px] font-semibold uppercase text-slate-400">
              Workflows
            </p>
            {slugs.map((slug) => {
              const fc = (proj.validation_findings[slug] ?? []).filter(
                (f) => f.severity === "blocking",
              ).length;
              return (
                <button
                  key={slug}
                  onClick={() => setActive(slug)}
                  className={`mb-1 flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs ${
                    slug === active
                      ? "bg-indigo-600 text-white"
                      : "hover:bg-slate-200 dark:hover:bg-slate-800"
                  }`}
                >
                  <span className="truncate">{slug}</span>
                  {fc > 0 && (
                    <span className="ml-1 rounded-full bg-red-500 px-1 text-[10px] text-white">
                      {fc}
                    </span>
                  )}
                </button>
              );
            })}
            {proj.warnings.length > 0 && (
              <div className="mt-3 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] text-amber-700 dark:text-amber-300">
                {proj.warnings.map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </div>
            )}
          </aside>

          {/* Center: editor / preview */}
          <section className="relative flex min-h-0 flex-col">
            {(validate.isPending || approve.isPending) && (
              <RunningOverlay
                title={approve.isPending ? "Compiling to Temporal code" : "Validating spec"}
                steps={approve.isPending ? APPROVE_STEPS : ["Folding edits", "LLM review passes"]}
              />
            )}
            <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-1 text-xs dark:border-slate-800">
              <button
                onClick={() => setShowPreview(false)}
                className={!showPreview ? "font-semibold text-indigo-500" : "text-slate-400"}
              >
                Editor
              </button>
              <button
                onClick={() => setShowPreview(true)}
                className={showPreview ? "font-semibold text-indigo-500" : "text-slate-400"}
              >
                Preview
              </button>
            </div>
            <div className="min-h-0 flex-1">
              {showPreview ? (
                <SpecPreview markdown={md} />
              ) : (
                <SpecEditor value={md} onChange={updateActive} />
              )}
            </div>
          </section>

          {/* Right: findings + structured widgets */}
          <aside className="flex min-h-0 flex-col gap-3 overflow-auto border-l border-slate-200 p-3 dark:border-slate-800">
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">
                Findings
              </h3>
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
              <div className="rounded-lg border border-slate-200 p-3 text-xs dark:border-slate-800">
                <p className="mb-2 font-semibold text-slate-500">Approve overrides</p>
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
            <p className="text-[11px] text-slate-400">
              CVPA-colored diagrams and generated code appear in Results after
              approval.
            </p>
          </aside>
        </div>
      )}
    </div>
  );
}

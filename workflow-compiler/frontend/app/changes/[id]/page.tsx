"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { useRuns } from "@/lib/runs";
import type { ChangeRequestResponse, ChangeStepKind } from "@/lib/types";
import { ArtifactPanel } from "@/components/ArtifactPanel";
import { ExportAllButton } from "@/components/ExportButtons";
import { RunningOverlay } from "@/components/RunningOverlay";
import { COMPILE_STEPS } from "@/lib/format";
import { ChangeChat } from "@/components/ChangeChat";
import { ChangeStagePill, STEP_LABEL, STEP_ORDER } from "@/components/ChangeStagePill";
import { ChangeStepper } from "@/components/ChangeStepper";

/** How often to re-check the change request while a job is attached to it. */
const JOB_POLL_MS = 3000;

export default function ChangeRequestPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const runs = useRuns();
  // null = follow the wizard's current step.
  const [selected, setSelected] = useState<ChangeStepKind | null>(null);
  const [showDoc, setShowDoc] = useState(false);

  const crQuery = useQuery({
    queryKey: ["change-request", id],
    queryFn: () => api.getChangeRequest(id),
    refetchInterval: (query) => {
      const data = query.state.data as ChangeRequestResponse | undefined;
      return data?.job && data.job.status === "running" ? JOB_POLL_MS : false;
    },
  });
  const res = crQuery.data;
  const cr = res?.change_request;

  // Prefer the job embedded in the response; the global poller is the fallback
  // (and is what refreshes this page when the job finishes elsewhere).
  const pollerJob = runs.jobForChangeRequest(id);
  const job =
    res?.job && res.job.status === "running"
      ? res.job
      : pollerJob?.status === "running"
        ? pollerJob
        : (res?.job ?? undefined);
  const running = job?.status === "running";

  // The response from a mutation is the freshest state we have — adopt it, and
  // wake the global poller so it tracks any job that was just started.
  const settle = (data: ChangeRequestResponse) => {
    queryClient.setQueryData(["change-request", id], data);
    queryClient.invalidateQueries({ queryKey: ["change-requests"] });
    queryClient.invalidateQueries({ queryKey: ["change-artifact", id] });
    if (data.job) queryClient.invalidateQueries({ queryKey: ["jobs"] });
  };

  // When a job finishes while the response still says "running", refetch.
  useEffect(() => {
    if (res?.job && res.job.status === "running" && pollerJob && pollerJob.job_id === res.job.job_id && pollerJob.status !== "running") {
      queryClient.invalidateQueries({ queryKey: ["change-request", id] });
    }
  }, [res?.job, pollerJob, queryClient, id]);

  const remove = useMutation({
    mutationFn: () => api.deleteChangeRequest(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["change-requests"] });
      router.push("/changes");
    },
  });

  // "Send to workflow GUI": compile the approved TDD into a KB-grounded project
  // (synchronous like the home page's compile) and open it. The wizard's own
  // provider is reused; the API defaults to cloud Nemotron when it has none.
  const sendToWorkflow = useMutation({
    mutationFn: () =>
      api.sendToWorkflow(id, {
        provider: cr?.wizard.provider ?? undefined,
        model: cr?.wizard.model ?? undefined,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["change-request", id] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${data.project.project_id}`);
    },
  });

  const currentStep: ChangeStepKind | null = res?.current_step ?? null;
  const stepKind: ChangeStepKind = useMemo(() => {
    if (selected) return selected;
    if (currentStep) return currentStep;
    // Complete: show the last step.
    if (cr?.stage === "complete") return "tdd";
    return "impact";
  }, [selected, currentStep, cr?.stage]);

  if (crQuery.error) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10">
        <p className="text-sm text-[var(--block)]">{(crQuery.error as ApiError).message}</p>
        <Link href="/changes" className="mt-3 inline-block text-sm text-[var(--accent)]">
          ← Change requests
        </Link>
      </div>
    );
  }
  if (!res || !cr) {
    return <div className="px-6 py-10 text-sm text-[var(--muted)]">Loading…</div>;
  }

  const step = cr.wizard.steps.find((s) => s.kind === stepKind) ?? {
    kind: stepKind,
    status: "pending" as const,
    questions: [],
    notes: [],
    turns: [],
    error: null,
    started_at: null,
    drafted_at: null,
    approved_at: null,
  };
  const artifact = cr.artifacts[stepKind];
  const isCurrent = stepKind === currentStep;
  const started = cr.wizard.started_at !== null;
  const tddApproved = cr.artifacts.tdd.status === "approved";

  return (
    <div className="relative mx-auto max-w-[88rem] px-6 py-8">
      {sendToWorkflow.isPending && (
        <RunningOverlay
          title="Compiling the TDD into a grounded workflow project"
          steps={[...COMPILE_STEPS, "Extracting the change spec (changes.md)"]}
        />
      )}
      {/* Header */}
      <div className="mb-5 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <Link href="/changes" className="text-xs text-[var(--faint)] hover:text-[var(--accent)]">
            ← Change requests
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{cr.title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)]">
            <ChangeStagePill stage={cr.stage} />
            {cr.bcr_meta.doc_id && <span className="font-mono">{cr.bcr_meta.doc_id}</span>}
            <span>
              KB:{" "}
              <Link href={`/knowledge/${cr.kb_id}`} className="link-accent">
                {cr.kb_name}
              </Link>
            </span>
            {cr.wizard.provider && (
              <span className="pill tone-accent">
                {cr.wizard.provider}
                {cr.wizard.model ? ` · ${cr.wizard.model}` : ""}
              </span>
            )}
            {cr.bcr_meta.target_workflow && (
              <span>workflow: {cr.bcr_meta.target_workflow}</span>
            )}
            {cr.bcr_meta.requested_by && <span>by {cr.bcr_meta.requested_by}</span>}
            {cr.source_filename && <span className="font-mono">{cr.source_filename}</span>}
            <span className="text-[var(--faint)]">updated {fmtRelative(cr.updated_at)}</span>
          </div>
          {(cr.ids.epic_id || cr.ids.story_ids.length > 0 || cr.ids.tdd_id) && (
            <div className="mt-2 flex flex-wrap items-center gap-1">
              {cr.ids.epic_id && (
                <span className="pill font-mono text-[11px]" title="Assigned EPIC id">
                  {cr.ids.epic_id}
                </span>
              )}
              {cr.ids.story_ids.map((s) => (
                <span key={s} className="pill font-mono text-[11px]" title="Assigned story id">
                  {s}
                </span>
              ))}
              {cr.ids.tdd_id && (
                <span className="pill font-mono text-[11px]" title="Assigned TDD id">
                  {cr.ids.tdd_id}
                </span>
              )}
              {cr.ids.next_test_case && (
                <span className="text-[11px] text-[var(--faint)]">
                  next test case {cr.ids.next_test_case}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn btn-ghost text-xs"
            onClick={() => setShowDoc((v) => !v)}
          >
            {showDoc ? "Hide document" : "Show document"}
          </button>
          {cr.wizard.steps.some((s) => s.status === "drafted" || s.status === "approved") && (
            <ExportAllButton crId={id} disabled={running} />
          )}
          {tddApproved && (
            <button
              type="button"
              className="btn btn-primary text-xs"
              disabled={running || sendToWorkflow.isPending}
              title="Compile the approved TDD into a workflow project grounded by this knowledge base"
              onClick={() => sendToWorkflow.mutate()}
            >
              {sendToWorkflow.isPending ? "Sending…" : "Send to workflow GUI"}
            </button>
          )}
          <button
            type="button"
            className="btn btn-danger text-xs"
            disabled={remove.isPending || running}
            onClick={() => {
              if (window.confirm(`Delete change request “${cr.title}”?`)) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
      </div>

      {sendToWorkflow.error && (
        <p className="tone-block mb-4 rounded-lg border px-3 py-2 text-sm">
          {(sendToWorkflow.error as ApiError).message}
        </p>
      )}
      {cr.project_ids.length > 0 && (
        <p className="tone-pass mb-4 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm">
          <span>Workflow project{cr.project_ids.length === 1 ? "" : "s"} from this TDD:</span>
          {cr.project_ids.map((pid) => (
            <Link key={pid} href={`/projects/${pid}`} className="link-accent font-mono text-xs">
              {pid.slice(0, 8)}
            </Link>
          ))}
        </p>
      )}
      {running && job && (
        <div className="tone-info mb-4 rounded-lg border px-3 py-2 text-sm" role="status">
          {job.kind === "cr_questions"
            ? "Drafting questions…"
            : job.kind === "cr_revise"
              ? "Revising artifact…"
              : "Drafting artifact…"}{" "}
          {job.progress?.message}
          {job.progress?.total ? ` (${job.progress.done}/${job.progress.total})` : ""}
        </div>
      )}
      {job && job.status === "failed" && (
        <div className="tone-block mb-4 rounded-lg border px-3 py-2 text-sm">
          The last job failed: {job.error ?? "unknown error"} — try again.
        </div>
      )}
      {cr.warnings.length > 0 && (
        <ul className="mb-4 space-y-1 text-xs text-[var(--muted)]">
          {cr.warnings.map((w) => (
            <li key={w}>! {w}</li>
          ))}
        </ul>
      )}

      {showDoc && (
        <section className="card mb-5 p-5">
          <div className="flex flex-wrap items-baseline gap-3">
            <h2 className="text-base font-semibold">Change request document</h2>
            {cr.requirements.length > 0 && (
              <span className="text-xs text-[var(--faint)]">
                {cr.requirements.length} requirement{cr.requirements.length === 1 ? "" : "s"}
              </span>
            )}
          </div>
          {cr.requirements.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm">
              {cr.requirements.map((r) => (
                <li key={r.id} className="flex gap-2">
                  <span className="pill font-mono text-[11px]">{r.id}</span>
                  <span>{r.text}</span>
                </li>
              ))}
            </ul>
          )}
          {cr.impact_seed_terms.length > 0 && (
            <div className="mt-3">
              <div className="text-xs uppercase tracking-wide text-[var(--faint)]">Seed terms</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {cr.impact_seed_terms.map((t) => (
                  <span key={t} className="pill font-mono text-[11px]">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}
          <pre className="mt-3 max-h-80 overflow-auto rounded-md border border-[var(--border)] p-2 font-mono text-[11px] leading-snug whitespace-pre-wrap">
            {cr.document_text}
          </pre>
        </section>
      )}

      {/* Stepper */}
      <div className="mb-5">
        <ChangeStepper
          steps={cr.wizard.steps}
          current={currentStep}
          selected={stepKind}
          running={running}
          onSelect={(k) => setSelected(k === currentStep ? null : k)}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.3fr]">
        {/* Chat column */}
        <section className="card flex min-h-0 flex-col p-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold">
              {STEP_LABEL[stepKind]}
              {isCurrent && (
                <span className="ml-2 text-xs font-normal text-[var(--accent)]">current step</span>
              )}
            </h2>
            {!isCurrent && currentStep && (
              <button
                type="button"
                className="ml-auto text-xs text-[var(--accent)]"
                onClick={() => setSelected(null)}
              >
                Jump to {STEP_LABEL[currentStep]} →
              </button>
            )}
            {step.questions.length > 0 && (
              <span className="ml-auto text-xs text-[var(--faint)]">
                {step.questions.filter((q) => q.status === "answered").length}/
                {step.questions.length} answered
              </span>
            )}
          </div>
          <ChangeChat
            key={stepKind}
            crId={id}
            step={step}
            isCurrent={isCurrent}
            started={started}
            question={isCurrent ? res.question : null}
            questionOptions={isCurrent ? res.question_options : []}
            job={running ? job : undefined}
            artifactStatus={artifact.status}
            defaultProvider={cr.wizard.provider}
            onResponse={(data) => {
              settle(data);
              // Follow the wizard again once the current step advances.
              if (data.current_step !== currentStep) setSelected(null);
            }}
          />
          {cr.stage === "complete" && (
            <p className="tone-pass mt-3 rounded-md border px-2.5 py-2 text-xs">
              All {STEP_ORDER.length} artifacts approved — this change request is complete.
            </p>
          )}
        </section>

        {/* Artifact column */}
        <ArtifactPanel
          key={stepKind}
          crId={id}
          crVersion={cr.version}
          kbId={cr.kb_id}
          kind={stepKind}
          artifact={artifact}
          running={running}
          onResponse={(data) => {
            settle(data);
            setSelected(null);
          }}
        />
      </div>
    </div>
  );
}

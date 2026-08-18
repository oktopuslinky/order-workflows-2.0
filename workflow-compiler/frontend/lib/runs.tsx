"use client";

// Global registry of background validate/approve runs.
//
// The server owns the runs (see api/jobs.py), so this provider is just a live
// mirror: it polls `GET /jobs` while anything is in flight, which is what lets a
// run survive the user leaving the project page or reloading — on any page load
// we rediscover the run from the server. When a run finishes while the user is
// elsewhere, we raise a toast and refresh the affected project queries so its
// badge updates in place.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Job, JobKind, JobStartBody, JobStatus } from "@/lib/types";

interface Toast {
  id: number;
  tone: "pass" | "block";
  message: string;
  projectId: string;
  /** Where clicking the toast goes (a project page or a knowledge-base page). */
  href: string;
}

interface RunsContextValue {
  /** Every run visible to the caller, newest first. */
  jobs: Job[];
  /** The most recent run for a project (active preferred), or undefined. */
  jobForProject: (projectId: string) => Job | undefined;
  /** True while a run for the project is in flight. */
  isRunning: (projectId: string) => boolean;
  /** The most recent ingest job for a knowledge base (active preferred). */
  jobForKnowledgeBase: (kbId: string) => Job | undefined;
  /** The most recent wizard job for a change request (active preferred). */
  jobForChangeRequest: (crId: string) => Job | undefined;
  /** Start a run; resolves to the created Job, rejects on 409/other errors. */
  start: (projectId: string, body: JobStartBody) => Promise<Job>;
  /** Cancel a run; the project is left exactly as it was. */
  cancel: (jobId: string) => Promise<void>;
}

const RunsContext = createContext<RunsContextValue | null>(null);

const KIND_LABEL: Record<JobKind, string> = {
  validate: "Validation",
  approve: "Approval",
  predraft: "Question drafting",
  kb_ingest: "Knowledge-base indexing",
  cr_questions: "Drafting questions",
  cr_draft: "Drafting artifact",
  cr_revise: "Revising artifact",
  change_outputs: "Change outputs",
};

const CR_SUCCESS: Partial<Record<JobKind, string>> = {
  cr_questions: "Change request: questions are ready.",
  cr_draft: "Change request: artifact drafted.",
  cr_revise: "Change request: artifact revised.",
};

const TERMINAL: ReadonlySet<JobStatus> = new Set([
  "succeeded",
  "failed",
  "canceled",
]);

export function RunsProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { user } = useAuth();

  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastSeq = useRef(0);

  // Last-seen status per job, so we fire completion side-effects exactly once on
  // the running → terminal edge (not on every poll that re-reports "succeeded").
  const seen = useRef<Map<string, JobStatus>>(new Map());

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.listJobs(),
    enabled: !!user,
    // Poll only while something is running; otherwise the list is static until
    // the next start/cancel invalidates it.
    refetchInterval: (query) => {
      const data = query.state.data as Job[] | undefined;
      return data?.some((j) => j.status === "running") ? 1500 : false;
    },
  });

  const jobs = jobsQuery.data ?? [];

  function pushToast(t: Omit<Toast, "id">) {
    const id = ++toastSeq.current;
    setToasts((prev) => [...prev, { ...t, id }]);
    // Auto-dismiss after a while; the badge on the project persists regardless.
    setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id));
    }, 8000);
  }

  // Detect running → terminal transitions and react (toast + refresh queries).
  useEffect(() => {
    for (const job of jobs) {
      const prev = seen.current.get(job.job_id);
      seen.current.set(job.job_id, job.status);
      if (prev === job.status || !TERMINAL.has(job.status)) continue;
      const isKb = job.scope_kind === "knowledge_base";
      const isCr = job.scope_kind === "change_request";
      const href = isKb
        ? `/knowledge/${job.scope_id}`
        : isCr
          ? `/changes/${job.scope_id}`
          : `/projects/${job.project_id}`;
      const refresh = () => {
        if (isKb) {
          queryClient.invalidateQueries({ queryKey: ["knowledge-base", job.scope_id] });
          queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
        } else if (isCr) {
          queryClient.invalidateQueries({ queryKey: ["change-request", job.scope_id] });
          queryClient.invalidateQueries({ queryKey: ["change-artifact", job.scope_id] });
          queryClient.invalidateQueries({ queryKey: ["change-requests"] });
        } else {
          queryClient.invalidateQueries({ queryKey: ["project", job.project_id] });
          queryClient.invalidateQueries({ queryKey: ["projects"] });
          queryClient.invalidateQueries({ queryKey: ["metrics-summary"] });
          queryClient.invalidateQueries({ queryKey: ["change-outputs", job.project_id] });
        }
      };
      // First time we observe this run as finished.
      if (prev === undefined && job.status !== "running") {
        // Job was already terminal when we first loaded (e.g. finished before a
        // refresh) — don't toast for history, just make sure views are fresh.
        refresh();
        continue;
      }
      refresh();

      const label = KIND_LABEL[job.kind];
      if (job.status === "succeeded") {
        pushToast({
          tone: "pass",
          projectId: job.project_id,
          href,
          message: isKb
            ? "Knowledge base indexed and ready."
            : isCr
              ? (CR_SUCCESS[job.kind] ?? `${label} complete.`)
              : job.kind === "approve"
              ? "Approval complete — code generated."
              : job.kind === "change_outputs"
                ? "Change outputs ready — diagrams, code diff and test documents."
                : "Validation complete.",
        });
      } else if (job.status === "failed") {
        pushToast({
          tone: "block",
          projectId: job.project_id,
          href,
          message: `${label} failed${job.error ? `: ${job.error}` : "."}`,
        });
      }
      // canceled: user-initiated, no toast.
    }
    // Drop bookkeeping for jobs the server has pruned.
    if (jobs.length) {
      const live = new Set(jobs.map((j) => j.job_id));
      for (const id of seen.current.keys()) {
        if (!live.has(id)) seen.current.delete(id);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs]);

  const startMutation = useMutation({
    mutationFn: (vars: { projectId: string; body: JobStartBody }) =>
      api.startJob(vars.projectId, vars.body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => api.cancelJob(jobId),
    onSuccess: (job) => {
      // Reflect the settled status immediately, then let the project refetch.
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["project", job.project_id] });
    },
  });

  const value: RunsContextValue = {
    jobs,
    jobForProject: (projectId) => {
      const forProject = jobs.filter(
        (j) => j.scope_kind === "project" && j.project_id === projectId,
      );
      return (
        forProject.find((j) => j.status === "running") ?? forProject[0] ?? undefined
      );
    },
    isRunning: (projectId) =>
      jobs.some(
        (j) =>
          j.scope_kind === "project" &&
          j.project_id === projectId &&
          j.status === "running",
      ),
    jobForKnowledgeBase: (kbId) => {
      const forKb = jobs.filter(
        (j) => j.scope_kind === "knowledge_base" && j.scope_id === kbId,
      );
      return forKb.find((j) => j.status === "running") ?? forKb[0] ?? undefined;
    },
    jobForChangeRequest: (crId) => {
      const forCr = jobs.filter(
        (j) => j.scope_kind === "change_request" && j.scope_id === crId,
      );
      return forCr.find((j) => j.status === "running") ?? forCr[0] ?? undefined;
    },
    start: (projectId, body) =>
      startMutation.mutateAsync({ projectId, body }),
    cancel: async (jobId) => {
      await cancelMutation.mutateAsync(jobId);
    },
  };

  return (
    <RunsContext.Provider value={value}>
      {children}
      <ToastHost
        toasts={toasts}
        onOpen={(href) => router.push(href)}
        onDismiss={(id) => setToasts((prev) => prev.filter((x) => x.id !== id))}
      />
    </RunsContext.Provider>
  );
}

export function useRuns(): RunsContextValue {
  const ctx = useContext(RunsContext);
  if (!ctx) throw new Error("useRuns must be used within a RunsProvider");
  return ctx;
}

/** Bottom-right stack of completion toasts; each links to its project. */
function ToastHost({
  toasts,
  onOpen,
  onDismiss,
}: {
  toasts: Toast[];
  onOpen: (href: string) => void;
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2 text-sm shadow-lg ${
            t.tone === "pass" ? "tone-pass" : "tone-block"
          }`}
        >
          <button
            type="button"
            onClick={() => onOpen(t.href)}
            className="min-w-0 flex-1 text-left"
            title="Open"
          >
            {t.message}
          </button>
          <button
            type="button"
            onClick={() => onDismiss(t.id)}
            aria-label="Dismiss"
            className="cursor-pointer font-medium leading-none hover:opacity-70"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

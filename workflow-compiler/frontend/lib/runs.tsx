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
}

interface RunsContextValue {
  /** Every run visible to the caller, newest first. */
  jobs: Job[];
  /** The most recent run for a project (active preferred), or undefined. */
  jobForProject: (projectId: string) => Job | undefined;
  /** True while a run for the project is in flight. */
  isRunning: (projectId: string) => boolean;
  /** Start a run; resolves to the created Job, rejects on 409/other errors. */
  start: (projectId: string, body: JobStartBody) => Promise<Job>;
  /** Cancel a run; the project is left exactly as it was. */
  cancel: (jobId: string) => Promise<void>;
}

const RunsContext = createContext<RunsContextValue | null>(null);

const KIND_LABEL: Record<JobKind, string> = {
  validate: "Validation",
  approve: "Approval",
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
      // First time we observe this run as finished.
      if (prev === undefined && job.status !== "running") {
        // Job was already terminal when we first loaded (e.g. finished before a
        // refresh) — don't toast for history, just make sure views are fresh.
        queryClient.invalidateQueries({ queryKey: ["project", job.project_id] });
        continue;
      }
      queryClient.invalidateQueries({ queryKey: ["project", job.project_id] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["metrics-summary"] });

      const label = KIND_LABEL[job.kind];
      if (job.status === "succeeded") {
        pushToast({
          tone: "pass",
          projectId: job.project_id,
          message:
            job.kind === "approve"
              ? "Approval complete — code generated."
              : "Validation complete.",
        });
      } else if (job.status === "failed") {
        pushToast({
          tone: "block",
          projectId: job.project_id,
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
      const forProject = jobs.filter((j) => j.project_id === projectId);
      return (
        forProject.find((j) => j.status === "running") ?? forProject[0] ?? undefined
      );
    },
    isRunning: (projectId) =>
      jobs.some((j) => j.project_id === projectId && j.status === "running"),
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
        onOpen={(projectId) => router.push(`/projects/${projectId}`)}
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
  onOpen: (projectId: string) => void;
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
            onClick={() => onOpen(t.projectId)}
            className="min-w-0 flex-1 text-left"
            title="Open project"
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

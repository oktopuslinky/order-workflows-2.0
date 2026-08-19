"use client";

// Run a generated workflow without leaving the app (RUN_WORKFLOWS_HANDOFF §5).
//
// Two rules shape this component:
//   * Absent Temporal is a *disabled* control with a reason, never a click-time
//     error (§5.4) — so the Run button gates on GET /projects/{id}/runnable.
//   * A compensated run is visibly different from a failed one (§8) — a saga
//     that rolled back cleanly did its job, and must not read as a crash.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  Run,
  RunnableWorkflow,
  RunState,
  SignalDescriptor,
  WorkflowInputField,
} from "@/lib/types";

/** Parse a starter.py literal into the value the form should start with. */
function initialValue(field: WorkflowInputField): string {
  const sample = field.sample.trim();
  // Strings arrive quoted (`"ORD-1"`); show the text, not the quotes.
  if (/^".*"$/.test(sample)) return sample.slice(1, -1);
  if (sample === "None") return "";
  return sample;
}

/** Turn a form value back into the JSON the API expects for its declared type. */
function coerce(field: WorkflowInputField, raw: string): unknown {
  const type = field.type.trim();
  if (type === "str") return raw;
  if (type === "bool") return raw === "true";
  if (type === "int") return raw.trim() === "" ? 0 : Number.parseInt(raw, 10);
  if (type === "float") return raw.trim() === "" ? 0 : Number.parseFloat(raw);
  // dict and list are edited as JSON. Invalid JSON is caught before submit so
  // the failure is a form message rather than a 422 from the server.
  return JSON.parse(raw);
}

function isJsonType(type: string): boolean {
  const t = type.trim();
  return t === "dict" || t === "list";
}

const STATE_TONE: Record<RunState, string> = {
  running: "tone-gate",
  completed: "tone-pass",
  // A clean rollback is not a crash — it gets the gate tone, not the block one.
  compensated: "tone-gate",
  failed: "tone-block",
  terminated: "tone-block",
  timed_out: "tone-block",
  canceled: "tone-block",
};

const STATE_LABEL: Record<RunState, string> = {
  running: "Running",
  completed: "Completed",
  compensated: "Compensated — rolled back cleanly",
  failed: "Failed",
  terminated: "Terminated",
  timed_out: "Timed out",
  canceled: "Canceled",
};

export function RunPanel({
  projectId,
  slug,
  onRunChanged,
}: {
  projectId: string;
  slug: string;
  /** The live run and its declared signals, for diagram highlighting. */
  onRunChanged?: (run: Run | null, signalNames: string[]) => void;
}) {
  const queryClient = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);

  const runnable = useQuery({
    queryKey: ["runnable", projectId],
    queryFn: () => api.runnable(projectId),
  });

  const workflow = runnable.data?.workflows.find((w) => w.slug === slug);
  const temporal = runnable.data?.temporal;

  // Poll only while the run is live; a terminal run never changes again.
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId as string),
    enabled: runId !== null,
    refetchInterval: (query) =>
      query.state.data && query.state.data.state !== "running" ? false : 1500,
  });

  // Surface the live run to the parent so the diagram can follow along. The
  // effect (not the query callback) is what guarantees the parent also hears
  // about the poll updates and the reset to null on unmount.
  const signalNames = (workflow?.signals ?? []).map((s) => s.name);
  const signalKey = signalNames.join(",");
  useEffect(() => {
    onRunChanged?.(run.data ?? null, signalKey ? signalKey.split(",") : []);
  }, [run.data, signalKey, onRunChanged]);
  useEffect(() => () => onRunChanged?.(null, []), [onRunChanged]);

  const start = useMutation({
    mutationFn: (input: Record<string, unknown>) =>
      api.startRun(projectId, slug, input),
    onSuccess: (started) => {
      setRunId(started.run_id);
      queryClient.invalidateQueries({ queryKey: ["runs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["runnable", projectId] });
    },
  });

  if (runnable.isLoading) {
    return <p className="text-xs text-[var(--faint)]">Checking what can run…</p>;
  }
  if (!workflow) return null;

  return (
    <div className="mt-3">
      <h4 className="eyebrow mb-1.5">Run</h4>
      <div className="card p-3">
        <Availability workflow={workflow} detail={temporal?.detail ?? null} reachable={temporal?.reachable ?? false} address={temporal?.address ?? ""} />
        <InputForm
          workflow={workflow}
          disabled={!workflow.runnable || !temporal?.reachable || start.isPending}
          pending={start.isPending}
          onSubmit={(input) => start.mutate(input)}
        />
        {start.error && (
          <p className="mt-2 text-xs text-[var(--block)]">
            {(start.error as ApiError).message}
          </p>
        )}
        {run.data && (
          <RunStatusView
            run={run.data}
            signals={workflow.signals}
            onChanged={(updated) => {
              queryClient.setQueryData(["run", updated.run_id], updated);
            }}
          />
        )}
      </div>
    </div>
  );
}

function Availability({
  workflow,
  reachable,
  address,
  detail,
}: {
  workflow: RunnableWorkflow;
  reachable: boolean;
  address: string;
  detail: string | null;
}) {
  if (!workflow.runnable) {
    return (
      <p className="tone-block mb-2 rounded-md border px-2 py-1 text-xs">
        No generated bundle for {workflow.slug} — approve the specs first.
      </p>
    );
  }
  if (!reachable) {
    return (
      <p className="tone-gate mb-2 rounded-md border px-2 py-1 text-xs">
        No Temporal server at {address || "the configured address"} —{" "}
        {detail ?? "start one with `temporal server start-dev`"}.
      </p>
    );
  }
  return (
    <p className="mb-2 text-xs text-[var(--muted)]">
      Queue <span className="font-mono">{workflow.task_queue}</span>
      {!workflow.materialized && " · the bundle will be written to disk on first run"}
    </p>
  );
}

function InputForm({
  workflow,
  disabled,
  pending,
  onSubmit,
}: {
  workflow: RunnableWorkflow;
  disabled: boolean;
  pending: boolean;
  onSubmit: (input: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  // Re-seed when the workflow changes: the defaults come from its own spec.
  useEffect(() => {
    const seeded: Record<string, string> = {};
    for (const field of workflow.inputs) seeded[field.name] = initialValue(field);
    setValues(seeded);
    setError(null);
  }, [workflow]);

  function submit() {
    const input: Record<string, unknown> = {};
    for (const field of workflow.inputs) {
      try {
        input[field.name] = coerce(field, values[field.name] ?? "");
      } catch {
        setError(`${field.name} is not valid JSON for a ${field.type}.`);
        return;
      }
    }
    setError(null);
    onSubmit(input);
  }

  return (
    <div>
      {workflow.inputs.length > 0 ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {workflow.inputs.map((field) => (
            <label key={field.name} className="text-xs">
              <span className="text-[var(--muted)]">
                {field.name}
                <span className="ml-1 font-mono text-[10px] text-[var(--faint)]">
                  {field.type}
                </span>
              </span>
              {field.type.trim() === "bool" ? (
                <select
                  value={values[field.name] ?? "True"}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [field.name]: e.target.value }))
                  }
                  className="mt-0.5 w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1"
                >
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : (
                <input
                  value={values[field.name] ?? ""}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [field.name]: e.target.value }))
                  }
                  placeholder={isJsonType(field.type) ? "JSON" : undefined}
                  className="mt-0.5 w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 font-mono"
                />
              )}
            </label>
          ))}
        </div>
      ) : (
        <p className="text-xs text-[var(--faint)]">
          This workflow declares no inputs.
        </p>
      )}
      {error && <p className="mt-1.5 text-xs text-[var(--block)]">{error}</p>}
      <button
        onClick={submit}
        disabled={disabled}
        className="btn btn-primary mt-2"
      >
        {pending ? "Starting…" : "Run workflow"}
      </button>
    </div>
  );
}

function RunStatusView({
  run,
  signals,
  onChanged,
}: {
  run: Run;
  signals: SignalDescriptor[];
  onChanged: (run: Run) => void;
}) {
  const terminate = useMutation({
    mutationFn: () => api.terminateRun(run.run_id),
    onSuccess: onChanged,
  });

  return (
    <div className="mt-3 border-t border-[var(--border)] pt-3">
      <div className="flex items-center gap-2">
        <span className={`pill ${STATE_TONE[run.state]}`}>
          {STATE_LABEL[run.state]}
        </span>
        <span className="font-mono text-[11px] text-[var(--faint)]">
          {run.workflow_id}
        </span>
        {run.state === "running" && (
          <button
            onClick={() => terminate.mutate()}
            disabled={terminate.isPending}
            className="btn btn-danger ml-auto"
          >
            Terminate
          </button>
        )}
      </div>

      {run.result && (
        <p className="mt-1.5 text-xs">
          <span className="text-[var(--muted)]">Result:</span>{" "}
          <span className="font-mono">{run.result}</span>
        </p>
      )}
      {run.error && <p className="mt-1.5 text-xs text-[var(--block)]">{run.error}</p>}
      {run.bundle_kept.length > 0 && (
        <p className="mt-1.5 text-xs text-[var(--muted)]">
          Kept your edits to {run.bundle_kept.join(", ")} — the bundle on disk is
          what ran.
        </p>
      )}

      {signals.length > 0 && run.state === "running" && (
        <SignalControls run={run} signals={signals} onChanged={onChanged} />
      )}

      {run.events.length > 0 && (
        <div className="mt-2">
          <h5 className="eyebrow mb-1">Steps</h5>
          <ol className="max-h-48 overflow-auto text-xs">
            {run.events.map((event, i) => (
              <li
                key={`${event.kind}-${i}`}
                className="flex gap-2 border-t border-[var(--border)] py-0.5"
              >
                <span className="w-36 shrink-0 text-[var(--faint)]">
                  {event.kind.replace(/_/g, " ")}
                </span>
                <span className="font-mono">{event.detail}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function SignalControls({
  run,
  signals,
  onChanged,
}: {
  run: Run;
  signals: SignalDescriptor[];
  onChanged: (run: Run) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [args, setArgs] = useState<Record<string, string>>({});

  const send = useMutation({
    mutationFn: (signal: SignalDescriptor) =>
      // One argument per declared parameter, and the *spec* name — sending the
      // snake_cased method name reaches nothing at all (§6.2).
      api.signalRun(
        run.run_id,
        signal.name,
        signal.params.map((p) => args[`${signal.name}.${p}`] ?? ""),
      ),
    onSuccess: (updated) => {
      setOpen(null);
      onChanged(updated);
    },
  });

  return (
    <div className="mt-2">
      <h5 className="eyebrow mb-1">Signals</h5>
      <div className="flex flex-wrap gap-1">
        {signals.map((signal) => (
          <button
            key={signal.name}
            onClick={() => setOpen(open === signal.name ? null : signal.name)}
            className="seg"
          >
            {signal.name}
          </button>
        ))}
      </div>
      {signals
        .filter((s) => s.name === open)
        .map((signal) => (
          <div key={signal.name} className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
            {signal.params.map((param) => (
              <label key={param} className="text-xs">
                <span className="text-[var(--muted)]">{param}</span>
                <input
                  value={args[`${signal.name}.${param}`] ?? ""}
                  onChange={(e) =>
                    setArgs((a) => ({
                      ...a,
                      [`${signal.name}.${param}`]: e.target.value,
                    }))
                  }
                  className="mt-0.5 w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 font-mono"
                />
              </label>
            ))}
            <div className="sm:col-span-2">
              <button
                onClick={() => send.mutate(signal)}
                disabled={send.isPending}
                className="btn btn-primary"
              >
                Send {signal.name}
              </button>
              {send.error && (
                <span className="ml-2 text-xs text-[var(--block)]">
                  {(send.error as ApiError).message}
                </span>
              )}
            </div>
          </div>
        ))}
    </div>
  );
}

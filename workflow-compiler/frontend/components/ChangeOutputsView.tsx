"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { diffLines } from "diff";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, ApiError, saveDownload } from "@/lib/api";
import { useRuns } from "@/lib/runs";
import type {
  ChangedFile,
  ChangeOutputs,
  ChangeOutputStage,
  CompilationProject,
  SmokeResult,
  StageRecord,
  UpdatedDiagram,
} from "@/lib/types";
import { CHANGE_OUTPUT_STAGES } from "@/lib/types";
import { MermaidView } from "./MermaidView";

const STAGE_LABEL: Record<ChangeOutputStage, string> = {
  diagrams: "Diagrams",
  code: "Code",
  tests_doc: "Test cases",
};

/**
 * "Change outputs" — the post-approval deliverables of a knowledge-base-grounded
 * project: updated Mermaid diagrams (original ⇄ updated), the modified code base
 * with a per-file diff, and the updated test-case matrix + test-plan addendum.
 * The outputs are produced by a `change_outputs` job (chained after approve, or
 * started here per stage); this view polls while one runs.
 */
export function ChangeOutputsView({ project }: { project: CompilationProject }) {
  const runs = useRuns();
  const queryClient = useQueryClient();
  const pid = project.project_id;
  const runningJob = runs.jobs.find(
    (j) => j.scope_kind === "project" && j.project_id === pid && j.status === "running",
  );
  const outputsRunning = runningJob?.kind === "change_outputs";
  const query = useQuery({
    queryKey: ["change-outputs", pid],
    queryFn: () => api.changeOutputs(pid),
    refetchInterval: outputsRunning ? 3000 : false,
  });
  const [stage, setStage] = useState<ChangeOutputStage>("diagrams");
  const [regenStage, setRegenStage] = useState<ChangeOutputStage | "all">("all");
  const regenerate = useMutation({
    mutationFn: () => api.regenerateChangeOutputs(pid, regenStage),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["change-outputs", pid] });
    },
  });
  const downloadAll = useMutation({
    mutationFn: async () => saveDownload(await api.exportChangeOutputsZip(pid)),
  });

  const outputs = query.data?.outputs ?? project.change_outputs ?? null;
  const available = query.data?.available ?? Boolean(project.kb_id && Object.keys(project.workflow_ids).length);
  const busy = Boolean(runningJob) || regenerate.isPending;
  const progress = runningJob?.progress;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-3 py-2">
        <div className="seg">
          {CHANGE_OUTPUT_STAGES.map((s) => (
            <button
              key={s}
              onClick={() => setStage(s)}
              className={stage === s ? "seg-active" : ""}
            >
              {STAGE_LABEL[s]}
              <StagePill record={outputs?.stages?.[s]} running={outputsRunning && progress?.message.startsWith(s)} />
            </button>
          ))}
        </div>
        {outputsRunning && (
          <span className="pill tone-info" title={progress?.message ?? ""}>
            running{progress && progress.total ? ` · ${progress.done}/${progress.total}` : ""}
            {progress?.message ? ` · ${progress.message}` : ""}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <select
            value={regenStage}
            onChange={(e) => setRegenStage(e.target.value as ChangeOutputStage | "all")}
            disabled={busy || !available}
            className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-xs"
            aria-label="Stage to regenerate"
          >
            <option value="all">all stages</option>
            {CHANGE_OUTPUT_STAGES.map((s) => (
              <option key={s} value={s}>
                {STAGE_LABEL[s]}
              </option>
            ))}
          </select>
          <button
            onClick={() => regenerate.mutate()}
            disabled={busy || !available}
            className="btn btn-gate"
            title="Run the selected stage(s) again (cloud Nemotron by default)"
          >
            {outputs ? "Regenerate" : "Generate"}
          </button>
          <button
            onClick={() => downloadAll.mutate()}
            disabled={!outputs || downloadAll.isPending}
            className="btn btn-primary"
          >
            Download all (.zip)
          </button>
        </div>
      </div>
      {(regenerate.error || downloadAll.error) && (
        <p className="tone-block border-b px-3 py-1.5 text-xs" data-testid="change-outputs-error">
          {(regenerate.error as ApiError | null)?.status === 409
            ? "Another job is running for this project — wait for it to finish, then regenerate. "
            : ""}
          {((regenerate.error || downloadAll.error) as ApiError).message}
        </p>
      )}

      {outputs?.warnings?.length ? (
        <details className="tone-gate border-b px-3 py-1.5 text-xs">
          <summary className="cursor-pointer">
            {outputs.warnings.length} warning{outputs.warnings.length === 1 ? "" : "s"} (grounding /
            checks)
          </summary>
          <ul className="mt-1 list-disc pl-4">
            {outputs.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {!available ? (
          <p className="text-sm text-[var(--muted)]">
            Change outputs need a knowledge-base-grounded project with a compiled workflow —
            approve the specs first.
          </p>
        ) : !outputs ? (
          <p className="text-sm text-[var(--muted)]">
            {outputsRunning
              ? "Generating diagrams, code and test documents from the knowledge base…"
              : "No change outputs yet — they are produced after approve; use Generate to run them now."}
          </p>
        ) : stage === "diagrams" ? (
          <DiagramsPanel outputs={outputs} projectId={pid} />
        ) : stage === "code" ? (
          <CodePanel outputs={outputs} projectId={pid} />
        ) : (
          <TestCasesPanel outputs={outputs} projectId={pid} />
        )}
        {outputs && outputs.provenance.length > 0 && (
          <details className="mt-4 text-xs text-[var(--muted)]">
            <summary className="cursor-pointer">
              Sources ({outputs.provenance.length} knowledge-base files / spans)
            </summary>
            <ul className="mt-1 list-disc pl-4 font-mono">
              {outputs.provenance.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}

function StagePill({ record, running }: { record?: StageRecord; running?: boolean }) {
  if (running) return <span className="ml-1.5 pill tone-info">running</span>;
  if (!record || record.status === "pending") return null;
  const tone =
    record.status === "done" ? "tone-pass" : record.status === "failed" ? "tone-block" : "tone-info";
  const secs = record.seconds != null ? ` ${Math.round(record.seconds)}s` : "";
  return (
    <span className={`ml-1.5 pill ${tone}`} title={record.error || undefined}>
      {record.status}
      {secs}
    </span>
  );
}

// ---------------------------------------------------------------- diagrams

function DiagramsPanel({ outputs, projectId }: { outputs: ChangeOutputs; projectId: string }) {
  const diagrams = outputs.diagrams;
  const [activeName, setActiveName] = useState(diagrams[0]?.name ?? "");
  const [side, setSide] = useState<"updated" | "original">("updated");
  const [showSource, setShowSource] = useState(false);
  const flow = useMutation({
    mutationFn: async () => saveDownload(await api.changeOutputFile(projectId, "system-flow-diagram.md")),
  });
  const active: UpdatedDiagram | undefined =
    diagrams.find((d) => d.name === activeName) ?? diagrams[0];
  if (!active) {
    return <p className="text-xs text-[var(--faint)]">No diagrams were generated.</p>;
  }
  const source = side === "original" ? (active.original ?? "") : active.updated;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1">
        {diagrams.map((d) => (
          <button
            key={d.name}
            onClick={() => {
              setActiveName(d.name);
              if (!d.original) setSide("updated");
            }}
            className={`cursor-pointer rounded-md border px-2 py-0.5 font-mono text-[11px] transition ${
              d.name === active.name
                ? "border-transparent bg-[var(--ink)] text-[var(--paper)]"
                : "border-[var(--border)] bg-[var(--surface-2)] text-[var(--muted)] hover:text-[var(--ink)]"
            }`}
            title={d.source_path || "new diagram"}
          >
            {d.name}
            {d.original === null && <span className="ml-1 opacity-70">new</span>}
            {d.checks.length > 0 && <span className="ml-1 text-[var(--gate)]">⚠</span>}
          </button>
        ))}
        {outputs.system_flow_md && (
          <button onClick={() => flow.mutate()} className="btn btn-ghost ml-auto" disabled={flow.isPending}>
            system-flow-diagram.md
          </button>
        )}
      </div>
      <div className="flex items-center gap-2 text-xs">
        <div className="seg">
          <button
            onClick={() => setSide("updated")}
            className={side === "updated" ? "seg-active" : ""}
          >
            Updated
          </button>
          <button
            onClick={() => setSide("original")}
            disabled={active.original === null}
            className={side === "original" ? "seg-active" : ""}
            title={active.original === null ? "This diagram is new" : undefined}
          >
            Original
          </button>
        </div>
        <span className="pill tone-info">{active.kind}</span>
        <label className="ml-auto flex items-center gap-1 text-[var(--muted)]">
          <input type="checkbox" checked={showSource} onChange={(e) => setShowSource(e.target.checked)} />
          source
        </label>
      </div>
      {active.checks.length > 0 && (
        <p className="tone-gate rounded-md border px-2 py-1 text-xs">
          Checks: {active.checks.join("; ")}
        </p>
      )}
      {active.notes && side === "updated" && (
        <p className="text-xs text-[var(--muted)]">{active.notes}</p>
      )}
      <div className="card p-2">
        {source.trim() ? <MermaidView source={source} /> : <p className="text-xs text-[var(--faint)]">Empty.</p>}
      </div>
      {showSource && (
        <pre className="max-h-[50vh] overflow-auto rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs">
          <code>{source}</code>
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- code

const STATUS_TONE: Record<ChangedFile["status"], string> = {
  modified: "tone-gate",
  added: "tone-pass",
  removed: "tone-block",
  unchanged: "tone-info",
};

function CodePanel({ outputs, projectId }: { outputs: ChangeOutputs; projectId: string }) {
  const files = outputs.code.files;
  const changed = files.filter((f) => f.status !== "unchanged");
  const [activePath, setActivePath] = useState(changed[0]?.path ?? files[0]?.path ?? "");
  const [mode, setMode] = useState<"unified" | "split" | "updated">("unified");
  const [showUnchanged, setShowUnchanged] = useState(false);
  const patch = useMutation({
    mutationFn: async () => saveDownload(await api.changeOutputFile(projectId, "changes.patch")),
  });
  const active = files.find((f) => f.path === activePath) ?? files[0];
  const listed = showUnchanged ? files : changed;
  if (!active) {
    return <p className="text-xs text-[var(--faint)]">No code files were produced.</p>;
  }
  return (
    <div className="grid gap-3 lg:grid-cols-[260px_1fr]">
      <div className="flex flex-col gap-1 text-xs">
        <div className="mb-1 flex items-center justify-between">
          <span className="eyebrow">Files ({changed.length} changed)</span>
          <label className="flex items-center gap-1 text-[var(--muted)]">
            <input type="checkbox" checked={showUnchanged} onChange={(e) => setShowUnchanged(e.target.checked)} />
            unchanged
          </label>
        </div>
        {listed.map((f) => (
          <button
            key={f.path}
            onClick={() => setActivePath(f.path)}
            className={`flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 text-left font-mono text-[11px] transition ${
              f.path === active.path
                ? "border-transparent bg-[var(--ink)] text-[var(--paper)]"
                : "border-[var(--border)] bg-[var(--surface-2)] text-[var(--muted)] hover:text-[var(--ink)]"
            }`}
            title={f.reason}
          >
            <span className="truncate">{f.path}</span>
            <span className={`pill ml-auto ${STATUS_TONE[f.status]}`}>{f.status}</span>
            {!f.checks.ast_ok && <span className="text-[var(--block)]" title={f.checks.ast_error}>syntax</span>}
          </button>
        ))}
        <p className="mt-2 text-[var(--faint)]">
          Rewrite order: {outputs.code.order.map((p) => p.split("/").pop()).join(" → ") || "—"}
        </p>
        <SmokeCard smoke={outputs.code.smoke ?? null} />
        <button onClick={() => patch.mutate()} className="btn btn-ghost mt-1" disabled={patch.isPending}>
          changes.patch
        </button>
      </div>
      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
          <span className="font-mono">{active.path}</span>
          <span className={`pill ${STATUS_TONE[active.status]}`}>{active.status}</span>
          <ChecksBadges file={active} />
          <div className="seg ml-auto">
            <button onClick={() => setMode("unified")} className={mode === "unified" ? "seg-active" : ""}>
              Unified
            </button>
            <button onClick={() => setMode("split")} className={mode === "split" ? "seg-active" : ""}>
              Side by side
            </button>
            <button onClick={() => setMode("updated")} className={mode === "updated" ? "seg-active" : ""}>
              Updated file
            </button>
          </div>
        </div>
        {active.reason && <p className="mb-2 text-xs text-[var(--muted)]">Why: {active.reason}</p>}
        {active.checks.problems && active.checks.problems.length > 0 && (
          <details className="mb-2 text-xs">
            <summary className="cursor-pointer text-[var(--muted)]">
              Repair rounds: {active.checks.repair_rounds ?? active.checks.problems.length} — what each
              round was asked to fix
            </summary>
            <ol className="mt-1 list-decimal space-y-1 pl-5">
              {active.checks.problems.map((p, i) => (
                <li key={i}>
                  <pre className="whitespace-pre-wrap font-mono text-[11px] text-[var(--muted)]">{p}</pre>
                </li>
              ))}
            </ol>
          </details>
        )}
        {mode === "unified" ? (
          <UnifiedDiff file={active} />
        ) : mode === "split" ? (
          <SplitDiff file={active} />
        ) : (
          <pre className="max-h-[70vh] overflow-auto rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs">
            <code>{active.updated || "(removed)"}</code>
          </pre>
        )}
      </div>
    </div>
  );
}

function ChecksBadges({ file }: { file: ChangedFile }) {
  const c = file.checks;
  return (
    <>
      <span className={`pill ${c.ast_ok ? "tone-pass" : "tone-block"}`} title={c.ast_error || "ast.parse ok"}>
        ast {c.ast_ok ? "ok" : "fail"}
      </span>
      {c.ruff_ok !== null && (
        <span className={`pill ${c.ruff_ok ? "tone-pass" : "tone-gate"}`} title={c.ruff_output || "ruff ok"}>
          ruff {c.ruff_ok ? "ok" : "findings"}
        </span>
      )}
      {c.repaired && (
        <span className="pill tone-info" title={(c.problems ?? []).join(String.fromCharCode(10, 10)) || undefined}>
          repaired{c.repair_rounds && c.repair_rounds > 1 ? ` ×${c.repair_rounds}` : ""}
        </span>
      )}
      {c.style_normalised && (
        <span className="pill tone-info" title="Typing generics / blank lines normalised to the original file's style">
          style kept
        </span>
      )}
      {c.truncated && <span className="pill tone-info">continued</span>}
    </>
  );
}

function SmokeCard({ smoke }: { smoke: SmokeResult | null }) {
  if (!smoke) {
    return (
      <p className="mt-2 text-[var(--faint)]" data-testid="smoke-card">
        Bundle smoke test: not run.
      </p>
    );
  }
  const tone =
    smoke.status === "passed" ? "tone-pass" : smoke.status === "failed" ? "tone-block" : "tone-gate";
  const failing = Object.entries(smoke.import_errors);
  return (
    <details className="mt-2 rounded-md border border-[var(--border)] px-2 py-1" data-testid="smoke-card">
      <summary className="cursor-pointer">
        Bundle smoke test <span className={`pill ${tone}`}>{smoke.status}</span>{" "}
        <span className="text-[var(--faint)]">
          {smoke.compiled} compiled · {smoke.imported.length}/{smoke.modules.length} imported
          {smoke.seconds ? ` · ${smoke.seconds.toFixed(1)}s` : ""}
        </span>
      </summary>
      <div className="mt-1 space-y-1 text-[11px]">
        <p className="text-[var(--faint)]">
          py_compile + import of the export layout in a child interpreter — a verdict on the draft,
          not a gate.
        </p>
        {smoke.note && <p className="text-[var(--muted)]">{smoke.note}</p>}
        {smoke.compile_errors.map((e) => (
          <pre key={e} className="whitespace-pre-wrap font-mono text-[var(--block)]">{e}</pre>
        ))}
        {failing.map(([mod, err]) => (
          <div key={mod}>
            <span className="font-mono">{mod}</span>
            <pre className="whitespace-pre-wrap font-mono text-[var(--block)]">{err}</pre>
          </div>
        ))}
        {smoke.status === "passed" && (
          <p className="text-[var(--muted)]">Every module imported: {smoke.imported.join(", ")}</p>
        )}
      </div>
    </details>
  );
}

function UnifiedDiff({ file }: { file: ChangedFile }) {
  if (!file.unified_diff) {
    return <p className="text-xs text-[var(--faint)]">No changes in this file.</p>;
  }
  const lines = file.unified_diff.split("\n");
  return (
    <pre className="max-h-[70vh] overflow-auto rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-0 text-xs">
      <code>
        {lines.map((line, i) => {
          const cls = line.startsWith("+++") || line.startsWith("---")
            ? "text-[var(--muted)] font-semibold"
            : line.startsWith("@@")
              ? "text-[var(--accent)]"
              : line.startsWith("+")
                ? "diff-add"
                : line.startsWith("-")
                  ? "diff-del"
                  : "";
          return (
            <div key={i} className={`whitespace-pre px-3 ${cls}`}>
              {line || " "}
            </div>
          );
        })}
      </code>
    </pre>
  );
}

function SplitDiff({ file }: { file: ChangedFile }) {
  const rows = useMemo(() => {
    const parts = diffLines(file.original, file.updated);
    const out: { left: string; right: string; kind: "same" | "add" | "del" | "change" }[] = [];
    let pendingDel: string[] = [];
    const flush = () => {
      for (const l of pendingDel) out.push({ left: l, right: "", kind: "del" });
      pendingDel = [];
    };
    for (const part of parts) {
      const ls = part.value.replace(/\n$/, "").split("\n");
      if (part.removed) {
        flush();
        pendingDel = ls;
      } else if (part.added) {
        ls.forEach((l, i) => {
          if (i < pendingDel.length) out.push({ left: pendingDel[i], right: l, kind: "change" });
          else out.push({ left: "", right: l, kind: "add" });
        });
        if (pendingDel.length > ls.length) {
          for (const l of pendingDel.slice(ls.length)) out.push({ left: l, right: "", kind: "del" });
        }
        pendingDel = [];
      } else {
        flush();
        for (const l of ls) out.push({ left: l, right: l, kind: "same" });
      }
    }
    flush();
    return out;
  }, [file.original, file.updated]);
  return (
    <div className="max-h-[70vh] overflow-auto rounded-lg border border-[var(--border)] bg-[var(--surface-2)] text-xs">
      <table className="w-full table-fixed border-collapse font-mono">
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="align-top">
              <td className={`w-1/2 whitespace-pre-wrap border-r border-[var(--border)] px-2 ${r.kind === "del" || r.kind === "change" ? "diff-del" : ""}`}>
                {r.left || " "}
              </td>
              <td className={`w-1/2 whitespace-pre-wrap px-2 ${r.kind === "add" || r.kind === "change" ? "diff-add" : ""}`}>
                {r.right || " "}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- test cases

function TestCasesPanel({ outputs, projectId }: { outputs: ChangeOutputs; projectId: string }) {
  const tests = outputs.tests_doc;
  const newIds = new Set(tests.new_ids);
  const changedIds = new Set(tests.changed_ids);
  const [onlyChanged, setOnlyChanged] = useState(false);
  const xlsx = useMutation({
    mutationFn: async () => saveDownload(await api.changeOutputFile(projectId, "test-cases.xlsx")),
  });
  const docx = useMutation({
    mutationFn: async () => saveDownload(await api.changeOutputFile(projectId, "test-plan-addendum.docx")),
  });
  if (!tests.test_cases.length) {
    return <p className="text-xs text-[var(--faint)]">No test-case rows were produced.</p>;
  }
  const rows = onlyChanged
    ? tests.test_cases.filter((r) => newIds.has(r.tc_id) || changedIds.has(r.tc_id))
    : tests.test_cases;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="pill tone-pass">{tests.new_ids.length} new</span>
        <span className="pill tone-gate">{tests.changed_ids.length} updated</span>
        <span className="text-[var(--muted)]">
          {tests.test_cases.length} rows · source {tests.matrix_source || "—"}
        </span>
        <label className="flex items-center gap-1 text-[var(--muted)]">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
          only new / updated
        </label>
        <div className="ml-auto flex gap-2">
          <button onClick={() => xlsx.mutate()} className="btn btn-primary" disabled={xlsx.isPending}>
            Download .xlsx
          </button>
          <button onClick={() => docx.mutate()} className="btn btn-ghost" disabled={docx.isPending || !tests.test_plan_addendum_md}>
            Test-plan addendum .docx
          </button>
        </div>
      </div>
      <div className="max-h-[55vh] overflow-auto rounded-lg border border-[var(--border)]">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-[var(--surface-2)] text-left text-[var(--muted)]">
            <tr>
              {["TC ID", "Title", "Steps", "Expected Result", "Type", "Automated", "Linked", "Notes"].map((h) => (
                <th key={h} className="px-2 py-1 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const tone = newIds.has(r.tc_id) ? "tone-pass" : changedIds.has(r.tc_id) ? "tone-gate" : "";
              return (
                <tr key={r.tc_id} className={`border-t border-[var(--border)] align-top ${tone}`}>
                  <td className="px-2 py-1 font-mono">
                    {r.tc_id}
                    {newIds.has(r.tc_id) && <span className="ml-1 opacity-70">new</span>}
                    {changedIds.has(r.tc_id) && <span className="ml-1 opacity-70">updated</span>}
                  </td>
                  <td className="px-2 py-1">{r.title}</td>
                  <td className="whitespace-pre-wrap px-2 py-1">{r.steps}</td>
                  <td className="whitespace-pre-wrap px-2 py-1">{r.expected}</td>
                  <td className="px-2 py-1">{r.type}</td>
                  <td className="px-2 py-1">{r.automated}</td>
                  <td className="px-2 py-1">{r.linked}</td>
                  <td className="whitespace-pre-wrap px-2 py-1">{r.notes}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {tests.test_plan_addendum_md && (
        <details className="card p-3 text-sm" open>
          <summary className="cursor-pointer text-xs font-semibold">
            Test-plan addendum ({tests.test_plan_id || "TP"} · {tests.change_request_id || "change"})
          </summary>
          <div className="prose-spec mt-2 text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{tests.test_plan_addendum_md}</ReactMarkdown>
          </div>
        </details>
      )}
    </div>
  );
}

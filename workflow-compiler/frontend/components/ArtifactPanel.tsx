"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { SpecEditor } from "@/components/SpecEditor";
import { SpecPreview } from "@/components/SpecPreview";
import { STEP_LABEL } from "@/components/ChangeStagePill";
import { ArtifactExportButtons } from "@/components/ExportButtons";
import type {
  Artifact,
  ArtifactResponse,
  ChangeRequestResponse,
  ChangeStepKind,
  SourceRef,
} from "@/lib/types";

const SOURCE_LABEL: Record<string, string> = {
  llm_draft: "draft",
  llm_revision: "revision",
  human_edit: "edit",
};

/**
 * The right-hand column of the wizard: the artifact for the selected step —
 * version picker, preview/edit toggle, save-as-new-version, approve, coverage,
 * and the KB sources the draft was grounded in (each expandable to the file).
 * Mount it with `key={kind}` so switching steps resets the local view.
 */
export function ArtifactPanel({
  crId,
  kbId,
  kind,
  artifact,
  running,
  onResponse,
}: {
  crId: string;
  kbId: string;
  kind: ChangeStepKind;
  /** The artifact as embedded in the change request (latest version). */
  artifact: Artifact;
  /** A job is running for this change request — disable mutations. */
  running: boolean;
  onResponse: (data: ChangeRequestResponse) => void;
}) {
  const queryClient = useQueryClient();
  const [version, setVersion] = useState<number | null>(null); // null = latest
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [buffer, setBuffer] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [openSource, setOpenSource] = useState<string | null>(null);

  const hasArtifact = artifact.status !== "empty";
  const viewingLatest = version === null || version === artifact.version;

  // Older versions come from the API; the latest is already in the CR.
  const older = useQuery({
    queryKey: ["change-artifact", crId, kind, version],
    queryFn: () => api.getChangeArtifact(crId, kind, version as number),
    enabled: hasArtifact && !viewingLatest,
  });

  const shown: {
    markdown: string;
    version: number;
    sources: SourceRef[];
    coverage: number | null;
  } = useMemo(() => {
    if (!viewingLatest && older.data) {
      const d: ArtifactResponse = older.data;
      return { markdown: d.markdown, version: d.version, sources: d.sources, coverage: d.coverage };
    }
    return {
      markdown: artifact.markdown,
      version: artifact.version,
      sources: artifact.sources,
      coverage: artifact.coverage,
    };
  }, [viewingLatest, older.data, artifact]);

  const save = useMutation({
    mutationFn: () => api.updateChangeArtifact(crId, kind, buffer, note.trim() || undefined),
    onSuccess: () => {
      setError(null);
      setMode("preview");
      setVersion(null);
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["change-request", crId] });
      queryClient.invalidateQueries({ queryKey: ["change-artifact", crId] });
      queryClient.invalidateQueries({ queryKey: ["change-requests"] });
    },
    onError: (err) => setError(describe(err)),
  });
  const approve = useMutation({
    mutationFn: () => api.approveChangeArtifact(crId, kind),
    onSuccess: (data) => {
      setError(null);
      setVersion(null);
      setMode("preview");
      onResponse(data);
    },
    onError: (err) => setError(describe(err)),
  });

  const busy = running || save.isPending || approve.isPending;
  const approved = artifact.status === "approved";

  const enterEdit = () => {
    setBuffer(shown.markdown);
    setMode("edit");
  };

  return (
    <section className="card flex min-h-0 flex-col p-5" data-testid="artifact-panel">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{STEP_LABEL[kind]} artifact</h2>
        <span
          className={`pill ${
            approved ? "tone-pass" : artifact.status === "drafted" ? "tone-gate" : "tone-info"
          }`}
        >
          {approved ? "approved" : artifact.status === "drafted" ? "drafted" : "no draft yet"}
        </span>
        {hasArtifact && (
          <select
            value={shown.version}
            onChange={(e) => {
              const v = Number(e.target.value);
              setVersion(v === artifact.version ? null : v);
              setMode("preview");
            }}
            disabled={mode === "edit"}
            aria-label="Version"
            className="ml-auto cursor-pointer rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-xs text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
          >
            {[...artifact.history]
              .sort((a, b) => b.version - a.version)
              .map((h) => (
                <option key={h.version} value={h.version}>
                  v{h.version} · {SOURCE_LABEL[h.source] ?? h.source}
                  {h.note ? ` · ${h.note}` : ""} · {fmtRelative(h.at)}
                </option>
              ))}
          </select>
        )}
      </div>

      {!hasArtifact ? (
        <p className="mt-4 text-sm text-[var(--faint)]">
          Nothing drafted yet — answer the questions on the left, or press “Draft now”.
        </p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="seg text-xs" role="tablist" aria-label="View">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "preview"}
                className={mode === "preview" ? "seg-active" : ""}
                onClick={() => setMode("preview")}
              >
                Preview
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "edit"}
                className={mode === "edit" ? "seg-active" : ""}
                onClick={enterEdit}
                disabled={busy || approved}
                title={approved ? "Approved artifacts are read-only" : "Edit the markdown"}
              >
                Edit
              </button>
            </div>
            {!viewingLatest && (
              <span className="pill tone-info">
                viewing v{shown.version} (latest is v{artifact.version})
              </span>
            )}
            {shown.coverage !== null && shown.coverage !== undefined && (
              <span
                className={`pill ${shown.coverage < 0.5 ? "tone-gate" : "tone-pass"}`}
                title="Share of the request's terms covered by the retrieved knowledge"
              >
                coverage {(shown.coverage * 100).toFixed(0)}%
              </span>
            )}
            <div className="ml-auto flex items-center gap-2">
              {mode === "edit" ? (
                <>
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Note for this version (optional)"
                    className="w-48 rounded-md border border-[var(--border-strong)] bg-transparent px-2 py-1 text-xs outline-none focus:border-[var(--accent)]"
                  />
                  <button
                    type="button"
                    className="btn btn-primary text-xs"
                    disabled={busy || buffer === shown.markdown || !buffer.trim()}
                    onClick={() => save.mutate()}
                  >
                    {save.isPending ? "Saving…" : "Save edit"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost text-xs"
                    disabled={busy}
                    onClick={() => setMode("preview")}
                  >
                    Cancel
                  </button>
                </>
              ) : approved ? (
                <span className="text-xs text-[var(--faint)]">
                  approved {artifact.approved_at ? fmtRelative(artifact.approved_at) : ""}
                </span>
              ) : (
                <button
                  type="button"
                  className="btn btn-pass text-xs"
                  disabled={busy || artifact.status !== "drafted" || !viewingLatest}
                  onClick={() => approve.mutate()}
                  title={
                    !viewingLatest
                      ? "Switch to the latest version to approve"
                      : "Approve the latest version and move to the next step"
                  }
                >
                  {approve.isPending ? "Approving…" : "Approve"}
                </button>
              )}
            </div>
          </div>

          {mode === "preview" && (
            <div className="mt-2">
              <ArtifactExportButtons crId={crId} kind={kind} approved={approved} disabled={busy} />
            </div>
          )}

          {error && (
            <p className="tone-block mt-2 rounded-md border px-2.5 py-2 text-xs">{error}</p>
          )}

          <div className="mt-3 h-[32rem] overflow-hidden rounded-md border border-[var(--border)] bg-[var(--surface)]">
            {older.isLoading && !viewingLatest ? (
              <p className="p-4 text-sm text-[var(--faint)]">Loading v{version}…</p>
            ) : older.error && !viewingLatest ? (
              <p className="p-4 text-sm text-[var(--block)]">
                {(older.error as ApiError).message}
              </p>
            ) : mode === "edit" ? (
              <SpecEditor value={buffer} onChange={setBuffer} />
            ) : (
              <SpecPreview markdown={shown.markdown} />
            )}
          </div>

          <SourcesFooter
            kbId={kbId}
            sources={shown.sources}
            open={openSource}
            onToggle={(p) => setOpenSource(openSource === p ? null : p)}
          />
        </>
      )}
    </section>
  );
}

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "A job is already running for this change request — wait for it to finish.";
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

/** The KB files the draft was grounded in; a path expands to the file text. */
function SourcesFooter({
  kbId,
  sources,
  open,
  onToggle,
}: {
  kbId: string;
  sources: SourceRef[];
  open: string | null;
  onToggle: (path: string) => void;
}) {
  const file = useQuery({
    queryKey: ["knowledge-base-file", kbId, open],
    queryFn: () => api.knowledgeBaseFile(kbId, open as string),
    enabled: !!open,
  });
  const highlighted = useMemo(() => {
    const spans = sources.find((s) => s.path === open)?.spans ?? [];
    const set = new Set<number>();
    for (const [a, b] of spans) for (let i = a; i <= b; i++) set.add(i);
    return set;
  }, [sources, open]);

  return (
    <div className="mt-3">
      <div className="text-xs uppercase tracking-wide text-[var(--faint)]">
        Sources <span className="normal-case">({sources.length})</span>
      </div>
      {sources.length === 0 ? (
        <p className="mt-1 text-xs text-[var(--faint)]">No knowledge-base sources recorded.</p>
      ) : (
        <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
          {sources.map((s) => (
            <li key={s.path} className="flex flex-wrap items-baseline gap-x-2">
              <button
                type="button"
                onClick={() => onToggle(s.path)}
                className={`cursor-pointer text-left break-all hover:text-[var(--accent)] ${
                  open === s.path ? "text-[var(--accent)]" : ""
                }`}
                title="Show the file"
              >
                {s.path}
              </button>
              {s.spans.length > 0 && (
                <span className="text-[var(--faint)]">
                  lines {s.spans.map(([a, b]) => (a === b ? `${a}` : `${a}-${b}`)).join(", ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {open && (
        <div className="mt-2 rounded-md border border-[var(--border)]">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-2 py-1 font-mono text-[11px] text-[var(--muted)]">
            <span className="break-all">{open}</span>
            <span className="shrink-0">
              {file.data ? `${file.data.size.toLocaleString()} B` : ""}
              {file.data?.extracted ? " · extracted text" : ""}
            </span>
          </div>
          <div className="max-h-72 overflow-auto p-2 font-mono text-[11px] leading-snug">
            {file.isLoading ? (
              "Loading…"
            ) : file.error ? (
              <span className="text-[var(--block)]">{(file.error as ApiError).message}</span>
            ) : (
              <FileLines text={file.data?.text ?? ""} highlighted={highlighted} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Numbered lines; the ones inside a source span are tinted. */
function FileLines({ text, highlighted }: { text: string; highlighted: Set<number> }) {
  const lines = text.split(/\r?\n/);
  return (
    <table className="w-full border-collapse">
      <tbody>
        {lines.map((line, i) => {
          const n = i + 1;
          const hit = highlighted.has(n);
          return (
            <tr key={n} className={hit ? "bg-[var(--accent-soft)]" : ""}>
              <td className="w-8 select-none pr-2 text-right align-top text-[var(--faint)] tabular-nums">
                {n}
              </td>
              <td className="whitespace-pre-wrap break-all align-top">{line}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

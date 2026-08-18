"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { useRuns } from "@/lib/runs";
import type { ChangeRequestSummary } from "@/lib/types";
import { ChangeStagePill, STEP_LABEL } from "@/components/ChangeStagePill";

// Kept in sync with the backend (api/dependencies.py SELECTABLE_PROVIDERS) and
// with the knowledge page. Cloud first: the wizard is several long calls.
const PROVIDER_OPTIONS = [
  { value: "nemotron", label: "Nemotron (cloud)" },
  { value: "local-fallback", label: "Spark + cloud fallback" },
  { value: "local", label: "Spark (local only)" },
] as const;

export default function ChangesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const runs = useRuns();
  const [kbId, setKbId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [provider, setProvider] = useState<string>("nemotron");
  const [mode, setMode] = useState<"file" | "text">("file");
  const fileInput = useRef<HTMLInputElement>(null);

  const kbs = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api.listKnowledgeBases(),
  });
  const readyKbs = (kbs.data ?? []).filter((kb) => kb.status === "ready");
  const effectiveKbId = kbId || readyKbs[0]?.kb_id || "";

  const list = useQuery({
    queryKey: ["change-requests"],
    queryFn: () => api.listChangeRequests(),
    // The RunsProvider poller invalidates on job completion; a slow refetch
    // keeps stage/step fresh while a wizard is working elsewhere.
    refetchInterval: (query) =>
      (query.state.data as ChangeRequestSummary[] | undefined)?.some(
        (cr) => cr.stage === "in_progress",
      )
        ? 5000
        : false,
  });

  const create = useMutation({
    mutationFn: () =>
      api.createChangeRequest({
        kbId: effectiveKbId,
        file: mode === "file" ? file : null,
        text: mode === "text" ? text : undefined,
        title: title || undefined,
        provider,
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["change-requests"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      router.push(`/changes/${res.change_request.cr_id}`);
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteChangeRequest(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["change-requests"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const items = list.data ?? [];
  const canSubmit =
    !!effectiveKbId && (mode === "file" ? !!file : text.trim().length > 0) && !create.isPending;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Change requests</h1>
        <p className="mt-1 max-w-3xl text-sm text-[var(--muted)]">
          A business change request (BCR) grounded in a knowledge base. The wizard
          walks it through impact analysis, an EPIC, user stories and a technical
          design — asking you questions along the way — and every artifact cites
          the corpus it was drawn from.
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
        {/* New change request */}
        <section className="card p-5">
          <h2 className="text-lg font-semibold">New change request</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Upload the BCR (.docx, .md or .txt) or paste its text.
          </p>

          <div className="mt-4 flex items-center gap-2">
            <label htmlFor="cr-kb" className="w-20 text-sm text-[var(--muted)]">
              Knowledge
            </label>
            <select
              id="cr-kb"
              value={effectiveKbId}
              onChange={(e) => setKbId(e.target.value)}
              className="flex-1 cursor-pointer rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
              data-testid="cr-kb"
            >
              {readyKbs.length === 0 && <option value="">No ready knowledge base</option>}
              {readyKbs.map((kb) => (
                <option key={kb.kb_id} value={kb.kb_id}>
                  {kb.name}
                </option>
              ))}
            </select>
          </div>
          {kbs.data && readyKbs.length === 0 && (
            <p className="mt-1 pl-[5.5rem] text-xs text-[var(--faint)]">
              <Link href="/knowledge" className="link-accent">
                Upload and index a knowledge base
              </Link>{" "}
              first.
            </p>
          )}

          <div className="mt-3 flex items-center gap-2">
            <span className="w-20 text-sm text-[var(--muted)]">Document</span>
            <div className="seg" role="tablist" aria-label="Document source">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "file"}
                className={mode === "file" ? "seg-active" : ""}
                onClick={() => setMode("file")}
              >
                Upload
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "text"}
                className={mode === "text" ? "seg-active" : ""}
                onClick={() => setMode("text")}
              >
                Paste text
              </button>
            </div>
          </div>

          {mode === "file" ? (
            <label
              className="mt-3 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-[var(--border-strong)] px-4 py-6 text-center text-sm transition hover:border-[var(--accent)] hover:bg-[var(--accent-soft)]/40"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const f = e.dataTransfer.files?.[0];
                if (f) setFile(f);
              }}
            >
              <input
                ref={fileInput}
                type="file"
                className="hidden"
                accept=".docx,.md,.txt,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                data-testid="cr-file"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {file ? (
                <span className="font-medium text-[var(--accent)]">
                  {file.name}{" "}
                  <span className="text-[var(--faint)]">({Math.round(file.size / 1024)} KB)</span>
                </span>
              ) : (
                <span className="text-[var(--muted)]">
                  Drag a .docx / .md / .txt here, or click to choose
                </span>
              )}
            </label>
          ) : (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={8}
              placeholder="Paste the change request text…"
              className="mt-3 w-full resize-y rounded-md border border-[var(--border-strong)] bg-transparent p-2 font-mono text-xs outline-none focus:border-[var(--accent)]"
              data-testid="cr-text"
            />
          )}

          <div className="mt-3 flex items-center gap-2">
            <label htmlFor="cr-title" className="w-20 text-sm text-[var(--muted)]">
              Title
            </label>
            <input
              id="cr-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Optional — defaults to the document's title"
              className="flex-1 rounded-md border border-[var(--border-strong)] bg-transparent px-2 py-1 text-sm outline-none focus:border-[var(--accent)]"
            />
          </div>

          <div className="mt-3 flex items-center gap-2">
            <label htmlFor="cr-provider" className="w-20 text-sm text-[var(--muted)]">
              Provider
            </label>
            <select
              id="cr-provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="flex-1 cursor-pointer rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
            >
              {PROVIDER_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          {create.error && (
            <p className="mt-3 text-sm text-[var(--block)]">
              {(create.error as ApiError).message}
            </p>
          )}

          <button
            disabled={!canSubmit}
            onClick={() => create.mutate()}
            className="btn btn-primary mt-4 w-full justify-center py-2"
            data-testid="cr-submit"
          >
            {create.isPending ? "Creating…" : "Create change request"}
          </button>
        </section>

        {/* List */}
        <section className="card p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">Existing</h2>
            <span className="text-xs text-[var(--faint)]">
              {items.length} change request{items.length === 1 ? "" : "s"}
            </span>
          </div>
          {list.isLoading && <p className="mt-4 text-sm text-[var(--muted)]">Loading…</p>}
          {list.error && (
            <p className="mt-4 text-sm text-[var(--block)]">
              {(list.error as ApiError).message}
            </p>
          )}
          {!list.isLoading && items.length === 0 && (
            <p className="mt-4 text-sm text-[var(--muted)]">
              None yet — create one on the left.
            </p>
          )}
          <ul className="mt-3 divide-y divide-[var(--border)]">
            {items.map((cr) => {
              const job = runs.jobForChangeRequest(cr.cr_id);
              const running = job?.status === "running";
              return (
                <li key={cr.cr_id} className="flex items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/changes/${cr.cr_id}`}
                      className="font-medium hover:text-[var(--accent)]"
                    >
                      {cr.title}
                    </Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)]">
                      <ChangeStagePill stage={cr.stage} />
                      {cr.doc_id && <span className="font-mono">{cr.doc_id}</span>}
                      <span>
                        KB:{" "}
                        <Link
                          href={`/knowledge/${cr.kb_id}`}
                          className="hover:text-[var(--accent)]"
                        >
                          {cr.kb_name}
                        </Link>
                      </span>
                      {cr.current_step && (
                        <span className="pill tone-accent">
                          step: {STEP_LABEL[cr.current_step]}
                        </span>
                      )}
                      <span className="text-[var(--faint)]">{fmtRelative(cr.updated_at)}</span>
                    </div>
                    {running && job?.progress?.message && (
                      <div className="mt-1 font-mono text-[11px] text-[var(--faint)]">
                        {job.progress.message}
                        {job.progress.total
                          ? ` (${job.progress.done}/${job.progress.total})`
                          : ""}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    className="btn btn-ghost text-xs"
                    onClick={() => {
                      if (window.confirm(`Delete change request “${cr.title}”?`)) {
                        remove.mutate(cr.cr_id);
                      }
                    }}
                    disabled={remove.isPending}
                    title="Delete the change request and its artifacts"
                  >
                    Delete
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      </div>
    </div>
  );
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { useRuns } from "@/lib/runs";
import type { KnowledgeBase } from "@/lib/types";
import { KbStatusPill } from "@/components/KbStatusPill";

// Kept in sync with the backend (api/dependencies.py SELECTABLE_PROVIDERS).
// Cloud first: enrichment is one call per corpus file and must not land on the
// single-GPU Spark gateway by default.
const PROVIDER_OPTIONS = [
  { value: "nemotron", label: "Nemotron (cloud)" },
  { value: "local-fallback", label: "Spark + cloud fallback" },
  { value: "local", label: "Spark (local only)" },
] as const;

export default function KnowledgePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const runs = useRuns();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [enrich, setEnrich] = useState(true);
  const [provider, setProvider] = useState<string>("nemotron");
  const fileInput = useRef<HTMLInputElement>(null);

  const list = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api.listKnowledgeBases(),
    // While something is ingesting the poller in RunsProvider refreshes the
    // list on completion; a slow refetch here keeps stats moving meanwhile.
    refetchInterval: (query) =>
      (query.state.data as KnowledgeBase[] | undefined)?.some(
        (kb) => kb.status === "ingesting",
      )
        ? 3000
        : false,
  });

  const create = useMutation({
    mutationFn: () =>
      api.createKnowledgeBase(file as File, {
        name: name || undefined,
        enrich,
        provider,
      }),
    onSuccess: (kb) => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      router.push(`/knowledge/${kb.kb_id}`);
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteKnowledgeBase(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const items = list.data ?? [];

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge bases</h1>
        <p className="mt-1 max-w-3xl text-sm text-[var(--muted)]">
          A knowledge base is a zipped corpus — business docs, diagrams, code and
          tests — indexed into a graph. It grounds change requests and specs
          later; here you can upload one, watch it index, and ask it questions.
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
        {/* Upload */}
        <section className="card p-5">
          <h2 className="text-lg font-semibold">New knowledge base</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Zip a folder such as{" "}
            <code className="font-mono text-xs">examples/knowledge_bases/order-lifecycle</code>{" "}
            (a single top-level folder is stripped automatically).
          </p>

          <label
            className="mt-4 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-[var(--border-strong)] px-4 py-6 text-center text-sm transition hover:border-[var(--accent)] hover:bg-[var(--accent-soft)]/40"
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
              accept=".zip,application/zip"
              data-testid="kb-file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            {file ? (
              <span className="font-medium text-[var(--accent)]">
                {file.name}{" "}
                <span className="text-[var(--faint)]">
                  ({Math.round(file.size / 1024)} KB)
                </span>
              </span>
            ) : (
              <span className="text-[var(--muted)]">
                Drag a corpus .zip here, or click to choose
              </span>
            )}
          </label>

          <div className="mt-3 flex items-center gap-2">
            <label htmlFor="kb-name" className="w-16 text-sm text-[var(--muted)]">
              Name
            </label>
            <input
              id="kb-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Optional — defaults to the file name"
              className="flex-1 rounded-md border border-[var(--border-strong)] bg-transparent px-2 py-1 text-sm outline-none focus:border-[var(--accent)]"
            />
          </div>

          <div className="mt-3 flex items-center gap-2">
            <label htmlFor="kb-provider" className="w-16 text-sm text-[var(--muted)]">
              Provider
            </label>
            <select
              id="kb-provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              disabled={!enrich}
              className="flex-1 cursor-pointer rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
            >
              {PROVIDER_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          <label className="mt-3 flex cursor-pointer items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={enrich}
              onChange={(e) => setEnrich(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">LLM enrichment</span>
              <span className="block text-xs text-[var(--muted)]">
                Per-file summaries, topics, entities and process clusters — one
                model call per document/module, run one after another. On cloud
                Nemotron the sample corpus (22 files) takes roughly 10–30 min
                the first time, and a single call can stall for several minutes
                before it is retried; re-indexing reuses cached answers. Static
                indexing alone takes seconds. Keep this page open — progress
                shows below as n/total.
              </span>
            </span>
          </label>

          {create.error && (
            <p className="mt-3 text-sm text-[var(--block)]">
              {(create.error as ApiError).message}
            </p>
          )}

          <button
            disabled={!file || create.isPending}
            onClick={() => create.mutate()}
            className="btn btn-primary mt-4 w-full justify-center py-2"
          >
            {create.isPending ? "Uploading…" : "Upload and index"}
          </button>
        </section>

        {/* List */}
        <section className="card p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">Existing</h2>
            <span className="text-xs text-[var(--faint)]">
              {items.length} knowledge base{items.length === 1 ? "" : "s"}
            </span>
          </div>
          {list.isLoading && (
            <p className="mt-4 text-sm text-[var(--muted)]">Loading…</p>
          )}
          {list.error && (
            <p className="mt-4 text-sm text-[var(--block)]">
              {(list.error as ApiError).message}
            </p>
          )}
          {!list.isLoading && items.length === 0 && (
            <p className="mt-4 text-sm text-[var(--muted)]">
              None yet — upload a corpus on the left.
            </p>
          )}
          <ul className="mt-3 divide-y divide-[var(--border)]">
            {items.map((kb) => {
              const job = kb.job ?? runs.jobForKnowledgeBase(kb.kb_id);
              const running = job?.status === "running";
              return (
                <li key={kb.kb_id} className="flex items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/knowledge/${kb.kb_id}`}
                      className="font-medium hover:text-[var(--accent)]"
                    >
                      {kb.name}
                    </Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)]">
                      <KbStatusPill status={kb.status} running={running} />
                      <span>
                        {kb.stats.nodes.toLocaleString()} nodes ·{" "}
                        {kb.stats.edges.toLocaleString()} edges · {kb.stats.files} files
                      </span>
                      {kb.llm_enriched && (
                        <span className="pill tone-accent">enriched · {kb.provider_used}</span>
                      )}
                      <span className="text-[var(--faint)]">
                        {fmtRelative(kb.updated_at)}
                      </span>
                    </div>
                    {running && job?.progress?.message && (
                      <div className="mt-1 font-mono text-[11px] text-[var(--faint)]">
                        {job.progress.message}
                        {job.progress.total
                          ? ` (${job.progress.done}/${job.progress.total})`
                          : ""}
                      </div>
                    )}
                    {kb.status === "failed" && kb.error && (
                      <div className="mt-1 text-xs text-[var(--block)]">{kb.error}</div>
                    )}
                  </div>
                  <button
                    type="button"
                    className="btn btn-ghost text-xs"
                    onClick={() => {
                      if (window.confirm(`Delete knowledge base “${kb.name}”?`)) {
                        remove.mutate(kb.kb_id);
                      }
                    }}
                    disabled={remove.isPending}
                    title="Delete the corpus and graph"
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

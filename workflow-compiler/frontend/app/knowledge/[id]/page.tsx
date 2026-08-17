"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { useRuns } from "@/lib/runs";
import type { KgPacket, KnowledgeBase } from "@/lib/types";
import { KbStatusPill } from "@/components/KbStatusPill";

// Node types in display order; anything else follows alphabetically.
const TYPE_ORDER = [
  "Document",
  "Module",
  "Class",
  "Function",
  "Chunk",
  "Epic",
  "UserStory",
  "TestCase",
  "Requirement",
  "Component",
  "Service",
  "DataArtifact",
  "Config",
  "Repository",
];

export default function KnowledgeBasePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const runs = useRuns();

  const kbQuery = useQuery({
    queryKey: ["knowledge-base", id],
    queryFn: () => api.getKnowledgeBase(id),
    refetchInterval: (query) =>
      (query.state.data as KnowledgeBase | undefined)?.status === "ingesting" ? 2000 : false,
  });
  const kb = kbQuery.data;
  const job = kb?.job ?? runs.jobForKnowledgeBase(id);
  const running = kb?.status === "ingesting" || job?.status === "running";
  const ready = kb?.status === "ready" && !running;

  const reindex = useMutation({
    mutationFn: (enrich: boolean) => api.reindexKnowledgeBase(id, { enrich }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-base", id] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteKnowledgeBase(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });
      router.push("/knowledge");
    },
  });

  if (kbQuery.error) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10">
        <p className="text-sm text-[var(--block)]">{(kbQuery.error as ApiError).message}</p>
        <Link href="/knowledge" className="mt-3 inline-block text-sm text-[var(--accent)]">
          ← Knowledge bases
        </Link>
      </div>
    );
  }
  if (!kb) {
    return <div className="px-6 py-10 text-sm text-[var(--muted)]">Loading…</div>;
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-5 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <Link href="/knowledge" className="text-xs text-[var(--faint)] hover:text-[var(--accent)]">
            ← Knowledge bases
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{kb.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)]">
            <KbStatusPill status={kb.status} running={running} />
            <span className="font-mono">{kb.kb_id}</span>
            <span>
              {kb.source.kind === "zip" ? "zip" : "folder"}: {kb.source.filename ?? "—"}
            </span>
            {kb.indexed_at && <span>indexed {fmtRelative(kb.indexed_at)}</span>}
            {kb.llm_enriched ? (
              <span className="pill tone-accent">
                enriched · {kb.provider_used}
                {kb.model_used ? ` · ${kb.model_used}` : ""}
              </span>
            ) : (
              <span className="pill">static index</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn btn-ghost text-xs"
            disabled={running || reindex.isPending}
            onClick={() => reindex.mutate(false)}
            title="Rebuild the graph without LLM calls"
          >
            Reindex (static)
          </button>
          <button
            type="button"
            className="btn btn-ghost text-xs"
            disabled={running || reindex.isPending}
            onClick={() => reindex.mutate(true)}
            title="Rebuild with LLM enrichment (cached results are reused)"
          >
            Reindex + enrich
          </button>
          <button
            type="button"
            className="btn btn-danger text-xs"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(`Delete knowledge base “${kb.name}”?`)) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
      </div>

      {running && (
        <div className="tone-info mb-4 rounded-lg border px-3 py-2 text-sm">
          Indexing… {job?.progress?.message}
          {job?.progress?.total ? ` (${job.progress.done}/${job.progress.total})` : ""}
        </div>
      )}
      {kb.status === "failed" && (
        <div className="tone-block mb-4 rounded-lg border px-3 py-2 text-sm">
          Indexing failed: {kb.error ?? "unknown error"} — fix the corpus or reindex.
        </div>
      )}
      {kb.warnings.length > 0 && (
        <ul className="mb-4 space-y-1 text-xs text-[var(--muted)]">
          {kb.warnings.map((w) => (
            <li key={w}>! {w}</li>
          ))}
        </ul>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <div className="space-y-6">
          <StatsCard kb={kb} />
          <CatalogCard kb={kb} />
          <FilesCard kbId={id} ready={ready} />
        </div>
        <div className="space-y-6">
          <AskCard kbId={id} ready={ready} />
          <ImpactCard kbId={id} ready={ready} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- cards

function StatsCard({ kb }: { kb: KnowledgeBase }) {
  const entries = useMemo(() => {
    const items = Object.entries(kb.stats.by_type);
    return items.sort((a, b) => {
      const ia = TYPE_ORDER.indexOf(a[0]);
      const ib = TYPE_ORDER.indexOf(b[0]);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a[0].localeCompare(b[0]);
    });
  }, [kb.stats.by_type]);
  return (
    <section className="card p-5">
      <h2 className="text-base font-semibold">Graph</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        {kb.stats.nodes.toLocaleString()} nodes · {kb.stats.edges.toLocaleString()} edges ·{" "}
        {kb.stats.files} corpus files
      </p>
      {entries.length > 0 ? (
        <table className="mt-3 w-full text-sm">
          <tbody>
            {entries.map(([type, count]) => (
              <tr key={type} className="border-t border-[var(--border)]">
                <td className="py-1 pr-2 font-mono text-xs">{type}</td>
                <td className="py-1 text-right tabular-nums">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-3 text-sm text-[var(--faint)]">No graph yet.</p>
      )}
    </section>
  );
}

function CatalogCard({ kb }: { kb: KnowledgeBase }) {
  const groups: [string, string[]][] = [
    ["Epics", kb.catalog.epics],
    ["User stories", kb.catalog.stories],
    ["Test cases", kb.catalog.test_cases],
    ["Requirements", kb.catalog.requirements],
  ];
  return (
    <section className="card p-5">
      <h2 className="text-base font-semibold">Catalog</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Business ids declared in the corpus (new artifacts number after these).
      </p>
      <dl className="mt-3 space-y-2 text-sm">
        {groups.map(([label, ids]) => (
          <div key={label}>
            <dt className="text-xs uppercase tracking-wide text-[var(--faint)]">
              {label} <span className="normal-case">({ids.length})</span>
            </dt>
            <dd className="mt-0.5 flex flex-wrap gap-1">
              {ids.length === 0 && <span className="text-[var(--faint)]">—</span>}
              {ids.map((i) => (
                <span key={i} className="pill font-mono text-[11px]">
                  {i}
                </span>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function FilesCard({ kbId, ready }: { kbId: string; ready: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const files = useQuery({
    queryKey: ["knowledge-base-files", kbId],
    queryFn: () => api.knowledgeBaseFiles(kbId),
    enabled: ready,
  });
  const file = useQuery({
    queryKey: ["knowledge-base-file", kbId, open],
    queryFn: () => api.knowledgeBaseFile(kbId, open as string),
    enabled: ready && !!open,
  });
  const tree = useMemo(() => groupByDir(files.data ?? []), [files.data]);
  return (
    <section className="card p-5">
      <h2 className="text-base font-semibold">Corpus files</h2>
      {!ready && <p className="mt-2 text-sm text-[var(--faint)]">Available once indexed.</p>}
      {files.data && (
        <div className="mt-2 max-h-72 overflow-auto text-xs">
          {tree.map(([dir, names]) => (
            <div key={dir} className="mb-2">
              <div className="font-mono text-[var(--faint)]">{dir || "."}</div>
              <ul className="ml-3">
                {names.map((n) => {
                  const path = dir ? `${dir}/${n}` : n;
                  return (
                    <li key={path}>
                      <button
                        type="button"
                        onClick={() => setOpen(open === path ? null : path)}
                        className={`cursor-pointer font-mono hover:text-[var(--accent)] ${
                          open === path ? "text-[var(--accent)]" : ""
                        }`}
                      >
                        {n}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
      {open && (
        <div className="mt-3 rounded-md border border-[var(--border)]">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-2 py-1 font-mono text-[11px] text-[var(--muted)]">
            <span>{open}</span>
            <span>
              {file.data ? `${file.data.size.toLocaleString()} B` : ""}
              {file.data?.extracted ? " · extracted text" : ""}
            </span>
          </div>
          <pre className="max-h-72 overflow-auto p-2 font-mono text-[11px] leading-snug whitespace-pre-wrap">
            {file.isLoading ? "Loading…" : file.error ? (file.error as ApiError).message : file.data?.text}
          </pre>
        </div>
      )}
    </section>
  );
}

function AskCard({ kbId, ready }: { kbId: string; ready: boolean }) {
  const [prompt, setPrompt] = useState("how does dispatch compensate provisioning");
  const [budget, setBudget] = useState(2000);
  const [packet, setPacket] = useState<KgPacket | null>(null);
  const [showRendered, setShowRendered] = useState(false);
  const ask = useMutation({
    mutationFn: () => api.retrieveFromKnowledgeBase(kbId, prompt, { budget }),
    onSuccess: (r) => setPacket(r.packet),
  });
  return (
    <section className="card p-5" data-testid="ask-card">
      <h2 className="text-base font-semibold">Ask the graph</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        What a prompt retrieves: BM25 anchors → traversal → real file spans. This
        is the packet later phases prepend to LLM prompts.
      </p>
      <form
        className="mt-3 flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready && prompt.trim()) ask.mutate();
        }}
      >
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={2}
          className="w-full resize-y rounded-md border border-[var(--border-strong)] bg-transparent p-2 text-sm outline-none focus:border-[var(--accent)]"
          data-testid="ask-prompt"
        />
        <div className="flex items-center gap-2">
          <label className="text-xs text-[var(--muted)]" htmlFor="budget">
            Budget
          </label>
          <input
            id="budget"
            type="number"
            min={500}
            max={12000}
            step={500}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
            className="w-24 rounded-md border border-[var(--border-strong)] bg-transparent px-2 py-1 text-xs outline-none"
          />
          <button
            type="submit"
            className="btn btn-primary ml-auto text-xs"
            disabled={!ready || ask.isPending || !prompt.trim()}
            data-testid="ask-submit"
          >
            {ask.isPending ? "Retrieving…" : "Retrieve"}
          </button>
        </div>
      </form>
      {ask.error && (
        <p className="mt-2 text-sm text-[var(--block)]">{(ask.error as ApiError).message}</p>
      )}
      {packet && (
        <div className="mt-4 space-y-3 text-sm" data-testid="ask-result">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`pill ${packet.low_confidence ? "tone-gate" : "tone-pass"}`}>
              coverage {(packet.coverage * 100).toFixed(0)}%
              {packet.low_confidence ? " · low confidence" : ""}
            </span>
            <span className="pill">{packet.total_tokens} tokens</span>
            <span className="pill">{packet.sections.length} sections</span>
            {packet.focus_domain && <span className="pill">focus: {packet.focus_domain}</span>}
            {packet.uncovered_terms.length > 0 && (
              <span className="text-[var(--faint)]">
                uncovered: {packet.uncovered_terms.join(", ")}
              </span>
            )}
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-[var(--faint)]">Seeds</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {packet.seeds.map((s) => (
                <span key={s} className="pill font-mono text-[11px]">
                  {s}
                </span>
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-[var(--faint)]">Sources</div>
            <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
              {packet.files.map((f) => (
                <li key={f.path} className="flex flex-wrap gap-x-2">
                  <span>{f.path}</span>
                  <span className="text-[var(--faint)]">
                    [{f.band}]{" "}
                    {f.spans.length ? `lines ${f.spans.map(([a, b]) => `${a}-${b}`).join(", ")}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <button
              type="button"
              className="text-xs text-[var(--accent)]"
              onClick={() => setShowRendered((v) => !v)}
            >
              {showRendered ? "Hide" : "Show"} rendered packet
            </button>
            {showRendered && (
              <pre className="mt-2 max-h-96 overflow-auto rounded-md border border-[var(--border)] p-2 font-mono text-[11px] leading-snug whitespace-pre-wrap">
                {packet.rendered}
              </pre>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function ImpactCard({ kbId, ready }: { kbId: string; ready: boolean }) {
  const [seed, setSeed] = useState("");
  const [hops, setHops] = useState(2);
  const impact = useMutation({
    mutationFn: () =>
      api.knowledgeBaseImpact(
        kbId,
        seed.split(",").map((s) => s.trim()).filter(Boolean),
        hops,
      ),
  });
  const rows = impact.data?.rows ?? [];
  return (
    <section className="card p-5">
      <h2 className="text-base font-semibold">Impact</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Deterministic traversal over dependency edges from a node id or a search
        term (comma-separate several).
      </p>
      <form
        className="mt-3 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready && seed.trim()) impact.mutate();
        }}
      >
        <input
          value={seed}
          onChange={(e) => setSeed(e.target.value)}
          placeholder="e.g. complete_order, mod:existing_Codebase/shared/types.py"
          className="flex-1 rounded-md border border-[var(--border-strong)] bg-transparent px-2 py-1 text-sm outline-none focus:border-[var(--accent)]"
        />
        <select
          value={hops}
          onChange={(e) => setHops(Number(e.target.value))}
          className="rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-xs"
          aria-label="Hops"
        >
          {[1, 2, 3].map((h) => (
            <option key={h} value={h}>
              {h} hop{h > 1 ? "s" : ""}
            </option>
          ))}
        </select>
        <button
          type="submit"
          className="btn btn-primary text-xs"
          disabled={!ready || impact.isPending || !seed.trim()}
        >
          {impact.isPending ? "…" : "Trace"}
        </button>
      </form>
      {impact.error && (
        <p className="mt-2 text-sm text-[var(--block)]">{(impact.error as ApiError).message}</p>
      )}
      {impact.data && (
        <div className="mt-3 max-h-80 overflow-auto">
          {rows.length === 0 ? (
            <p className="text-sm text-[var(--faint)]">Nothing reached — no such node or term.</p>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-left text-[var(--faint)]">
                <tr>
                  <th className="py-1 pr-2">hops</th>
                  <th className="py-1 pr-2">type</th>
                  <th className="py-1 pr-2">node</th>
                  <th className="py-1">via</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.node_id} className="border-t border-[var(--border)] align-top">
                    <td className="py-1 pr-2 tabular-nums">{r.hops}</td>
                    <td className="py-1 pr-2">{r.type}</td>
                    <td className="py-1 pr-2 font-mono break-all">{r.node_id}</td>
                    <td className="py-1 font-mono text-[var(--faint)] break-all">{r.via}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- helpers

function groupByDir(paths: string[]): [string, string[]][] {
  const map = new Map<string, string[]>();
  for (const p of paths) {
    const idx = p.lastIndexOf("/");
    const dir = idx === -1 ? "" : p.slice(0, idx);
    const name = idx === -1 ? p : p.slice(idx + 1);
    const list = map.get(dir) ?? [];
    list.push(name);
    map.set(dir, list);
  }
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

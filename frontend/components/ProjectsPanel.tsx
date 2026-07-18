"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useRuns } from "@/lib/runs";
import { fmtRelative, shortId, STAGE_LABEL, STAGE_TONE } from "@/lib/format";
import type { ProjectSummary } from "@/lib/types";
import { ProjectRowsSkeleton } from "@/components/Skeleton";

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

/**
 * The Projects list: searchable, paginated, and renameable in place. Page size
 * is a persisted per-user preference (default 10); search and paging are local.
 */
export function ProjectsPanel() {
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
  });
  const { user, setUser } = useAuth();
  const pageSize = user?.preferences.projects_page_size ?? 10;

  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);

  const all = useMemo(
    () => projects.data?.projects ?? [],
    [projects.data],
  );
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (p) =>
        (p.nickname ?? "").toLowerCase().includes(q) ||
        p.project_id.toLowerCase().includes(q),
    );
  }, [all, query]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(page, pageCount);
  const start = (current - 1) * pageSize;
  const visible = filtered.slice(start, start + pageSize);

  // Persist a new page size to the user's profile and refresh the auth context.
  const savePageSize = useMutation({
    mutationFn: (size: number) => api.updateProfile({ preferences: { ...user!.preferences, projects_page_size: size } }),
    onSuccess: (updated) => {
      setUser(updated);
      setPage(1);
    },
  });

  return (
    <section className="card flex flex-col p-5">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Projects</h2>
        {all.length > 0 && (
          <span className="text-xs text-[var(--faint)] [font-variant-numeric:tabular-nums]">
            {filtered.length}
            {query ? ` of ${all.length}` : ""}
          </span>
        )}
      </div>

      {/* Search */}
      <div className="mt-3">
        <label htmlFor="project-search" className="sr-only">
          Search projects
        </label>
        <input
          id="project-search"
          type="search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
          placeholder="Search projects…"
          className="w-full rounded-md border border-[var(--border-strong)] bg-transparent px-3 py-1.5 text-sm outline-none focus:border-[var(--accent)]"
        />
      </div>

      {projects.isLoading && <ProjectRowsSkeleton rows={Math.min(pageSize, 4)} />}

      {projects.error && (
        <p className="mt-3 text-sm text-[var(--block)]">
          {(projects.error as ApiError).message}
        </p>
      )}

      {projects.data && all.length === 0 && (
        <p className="mt-3 text-sm text-[var(--muted)]">
          No projects yet. Compile a document to begin.
        </p>
      )}

      {projects.data && all.length > 0 && filtered.length === 0 && (
        <p className="mt-3 text-sm text-[var(--muted)]">
          No projects match “{query}”.
        </p>
      )}

      {visible.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {visible.map((p) => (
            <ProjectRow key={p.project_id} project={p} />
          ))}
        </ul>
      )}

      {/* Footer: pagination + page size */}
      {filtered.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--muted)]">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              className="btn btn-ghost px-2 py-1 text-xs"
              disabled={current <= 1}
              onClick={() => setPage(current - 1)}
            >
              ‹ Prev
            </button>
            <span className="px-1 [font-variant-numeric:tabular-nums]">
              {current} / {pageCount}
            </span>
            <button
              type="button"
              className="btn btn-ghost px-2 py-1 text-xs"
              disabled={current >= pageCount}
              onClick={() => setPage(current + 1)}
            >
              Next ›
            </button>
          </div>
          <label className="flex items-center gap-1.5">
            <span className="text-[var(--faint)]">Per page</span>
            <select
              value={pageSize}
              disabled={!user || savePageSize.isPending}
              onChange={(e) => savePageSize.mutate(Number(e.target.value))}
              className="cursor-pointer rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-1.5 py-0.5 text-xs outline-none focus:border-[var(--accent)]"
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
    </section>
  );
}

/** One project row: label + stage badge + age, with inline rename. */
function ProjectRow({ project }: { project: ProjectSummary }) {
  const queryClient = useQueryClient();
  const runs = useRuns();
  const job = runs.jobForProject(project.project_id);
  const running = job?.status === "running";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(project.nickname ?? "");

  const rename = useMutation({
    mutationFn: (nickname: string | null) =>
      api.renameProject(project.project_id, nickname),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setEditing(false);
    },
  });

  const cancelRun = useMutation({
    mutationFn: (jobId: string) => runs.cancel(jobId),
  });

  const label = project.nickname?.trim();

  if (editing) {
    return (
      <li>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            rename.mutate(draft.trim() || null);
          }}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--accent)] px-2 py-1.5"
        >
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setEditing(false);
            }}
            placeholder="Project nickname"
            aria-label="Project nickname"
            className="min-w-0 flex-1 bg-transparent px-1 text-sm outline-none"
          />
          <button
            type="submit"
            disabled={rename.isPending}
            className="btn btn-primary px-2 py-1 text-xs"
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="btn btn-ghost px-2 py-1 text-xs"
          >
            Cancel
          </button>
        </form>
      </li>
    );
  }

  return (
    <li className="group flex items-center gap-2 rounded-lg border border-[var(--border)] transition hover:border-[var(--accent)] hover:bg-[var(--accent-soft)]">
      <Link
        href={`/projects/${project.project_id}`}
        className="min-w-0 flex-1 px-3 py-2"
      >
        <div className="flex items-center gap-2">
          <span
            className={`truncate text-sm ${
              label
                ? "font-medium text-[var(--ink)]"
                : "font-mono text-[var(--muted)]"
            }`}
          >
            {label || shortId(project.project_id)}
          </span>
        </div>
        <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--faint)]">
          <span className={`pill border ${STAGE_TONE[project.stage]}`}>
            {STAGE_LABEL[project.stage]}
          </span>
          {running && (
            <span className="pill tone-accent inline-flex items-center gap-1">
              <span className="h-2 w-2 animate-spin rounded-full border border-current border-t-transparent" />
              {job?.kind === "approve" ? "Compiling…" : "Validating…"}
            </span>
          )}
          <span>
            {project.workflow_count} workflow
            {project.workflow_count === 1 ? "" : "s"}
          </span>
          <span aria-hidden>·</span>
          <span>{fmtRelative(project.updated_at)}</span>
        </div>
      </Link>
      {running && job && (
        <button
          type="button"
          onClick={() => cancelRun.mutate(job.job_id)}
          disabled={cancelRun.isPending}
          title="Cancel run — keeps the current version"
          className="mr-1 rounded-md px-2 py-1 text-xs text-[var(--block)] transition hover:bg-[var(--block-soft)]"
        >
          {cancelRun.isPending ? "…" : "Cancel"}
        </button>
      )}
      <button
        type="button"
        onClick={() => {
          setDraft(project.nickname ?? "");
          setEditing(true);
        }}
        aria-label={label ? `Rename ${label}` : "Name this project"}
        title="Rename"
        className="mr-2 rounded-md p-1.5 text-[var(--faint)] opacity-0 transition hover:bg-[var(--surface-2)] hover:text-[var(--ink)] focus-visible:opacity-100 group-hover:opacity-100"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
        </svg>
      </button>
    </li>
  );
}

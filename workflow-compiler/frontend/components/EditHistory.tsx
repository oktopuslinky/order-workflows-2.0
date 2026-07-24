"use client";

import type { EditRecord } from "@/lib/types";

/** Right-rail audit trail of applied edit requests, newest first. */
export function EditHistory({ records }: { records: EditRecord[] }) {
  if (records.length === 0) return null;
  return (
    <div>
      <h3 className="eyebrow mb-2">Edit history</h3>
      <div className="flex flex-col gap-2">
        {[...records].reverse().map((record) => (
          <HistoryEntry key={record.edit_id} record={record} />
        ))}
      </div>
    </div>
  );
}

function HistoryEntry({ record }: { record: EditRecord }) {
  const slugs = Object.keys(record.summary);
  const changeCount = Object.values(record.summary).flat().length;
  return (
    <details className="card p-2 text-xs">
      <summary className="cursor-pointer select-none">
        <span className="font-medium text-[var(--ink)]">
          {new Date(record.created_at).toLocaleString()}
        </span>
        {record.author && (
          <span className="text-[var(--muted)]"> — {record.author}</span>
        )}
        <span className="block text-[var(--muted)]">
          {changeCount} change{changeCount === 1 ? "" : "s"} across {slugs.length}{" "}
          workflow{slugs.length === 1 ? "" : "s"}
        </span>
      </summary>
      <div className="mt-2 flex flex-col gap-2 border-t border-[var(--border)] pt-2">
        {(record.workflows_added.length > 0 ||
          record.workflows_removed.length > 0) && (
          <div className="flex flex-wrap gap-1">
            {record.workflows_added.map((s) => (
              <span key={s} className="pill tone-pass">
                + {s}
              </span>
            ))}
            {record.workflows_removed.map((s) => (
              <span key={s} className="pill tone-block">
                − {s}
              </span>
            ))}
          </div>
        )}
        {Object.entries(record.summary).map(([slug, lines]) => (
          <div key={slug}>
            <p className="font-medium text-[var(--ink)]">{slug}</p>
            <ul className="mt-0.5 list-disc pl-4 text-[var(--muted)]">
              {lines.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
            {(record.resolved_patches?.[slug] ?? []).length > 0 && (
              <ul className="mt-1 flex flex-col gap-0.5 font-mono text-[11px] text-[var(--faint)]">
                {(record.resolved_patches[slug] ?? []).map((p, i) => (
                  <li key={i} className="break-all">
                    {p.action} · {p.target}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
        {(record.trigger_ops ?? []).length + (record.xref_ops ?? []).length >
          0 && (
          <p className="text-[var(--muted)]">
            {(record.trigger_ops ?? []).length} trigger op(s),{" "}
            {(record.xref_ops ?? []).length} dependency op(s)
          </p>
        )}
        <details>
          <summary className="cursor-pointer text-[var(--faint)]">
            Show request document
          </summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2 font-mono text-[11px] whitespace-pre-wrap">
            {record.document}
          </pre>
        </details>
      </div>
    </details>
  );
}

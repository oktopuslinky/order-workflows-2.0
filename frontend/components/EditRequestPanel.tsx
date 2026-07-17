"use client";

import { useRef, useState } from "react";
import type { EditRecord } from "@/lib/types";

const TEMPLATE = `# Edit Request

## Workflow: <slug>

### Add

-

### Modify

-

### Remove

-

## Reason

`;

/** Paste/upload a workflow edit-request document and apply it to the project. */
export function EditRequestPanel({
  editLog,
  busy,
  error,
  onSubmit,
  onClose,
}: {
  editLog: EditRecord[];
  busy: boolean;
  error: string | null;
  onSubmit: (document: string, author: string | null) => void;
  onClose: () => void;
}) {
  const [doc, setDoc] = useState(TEMPLATE);
  const [author, setAuthor] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  async function loadFile(file: File | undefined) {
    if (!file) return;
    setDoc(await file.text());
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-6">
      <div className="card flex max-h-full w-full max-w-2xl flex-col overflow-hidden bg-[var(--surface)] p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="eyebrow">Edit request</h3>
          <button onClick={onClose} className="btn btn-ghost" disabled={busy}>
            Close
          </button>
        </div>
        <p className="mb-2 text-xs text-[var(--muted)]">
          Describe changes per workflow (see <code>docs/EDIT_FORMAT_GUIDE.md</code>).
          Applying an edit re-arms the gate: Validate and Approve must run again.
        </p>
        <textarea
          value={doc}
          onChange={(e) => setDoc(e.target.value)}
          spellCheck={false}
          className="min-h-[220px] flex-1 resize-y rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2 font-mono text-xs"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            accept=".md,.txt"
            className="hidden"
            onChange={(e) => loadFile(e.target.files?.[0])}
          />
          <button
            onClick={() => fileInput.current?.click()}
            className="btn btn-ghost"
            disabled={busy}
          >
            Upload .md
          </button>
          <input
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            placeholder="Author (optional)"
            className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-xs"
          />
          <button
            onClick={() => onSubmit(doc, author.trim() || null)}
            disabled={busy || !doc.trim()}
            className="btn btn-gate ml-auto"
          >
            {busy ? "Applying…" : "Apply edit"}
          </button>
        </div>
        {error && <p className="tone-block mt-2 rounded-md border p-2 text-xs whitespace-pre-wrap">{error}</p>}

        {editLog.length > 0 && (
          <div className="mt-3 max-h-40 overflow-auto border-t border-[var(--border)] pt-2">
            <p className="eyebrow mb-1">Edit history</p>
            {[...editLog].reverse().map((record) => (
              <div key={record.edit_id} className="mb-2 text-[11px] text-[var(--muted)]">
                <p className="font-medium text-[var(--ink)]">
                  {new Date(record.created_at).toLocaleString()}
                  {record.author ? ` — ${record.author}` : ""}
                </p>
                {Object.entries(record.summary).map(([slug, lines]) => (
                  <p key={slug} className="truncate">
                    <span className="font-medium">{slug}</span>: {lines.join("; ")}
                  </p>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

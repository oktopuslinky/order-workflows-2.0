"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { RunningOverlay } from "@/components/RunningOverlay";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { EditPreviewResponse, EditRecord, ResolvedEdit } from "@/lib/types";

const PREVIEW_STEPS = ["Parsing skeleton", "Interpreting entries (LLM)"];

function template(slug: string | undefined): string {
  return `# Edit Request

## Workflow: ${slug ?? "<slug>"}

### Add

-

### Modify

-

### Remove

-

## Reason

`;
}

function workflowSection(slug: string): string {
  return `\n## Workflow: ${slug}\n\n### Modify\n\n- \n`;
}

/** Trimmed-line set difference — enough to show what an edit adds/removes. */
function lineDiff(
  before: string,
  after: string,
): { added: string[]; removed: string[] } {
  const beforeLines = before.split("\n").map((line) => line.trimEnd());
  const afterLines = after.split("\n").map((line) => line.trimEnd());
  const beforeSet = new Set(beforeLines);
  const afterSet = new Set(afterLines);
  return {
    added: afterLines.filter((line) => line.trim() && !beforeSet.has(line)),
    removed: beforeLines.filter((line) => line.trim() && !afterSet.has(line)),
  };
}

/**
 * Two-step edit-request dialog: compose the document, preview what the LLM
 * understood (nothing applied), then confirm — the confirm replays the
 * previewed operations server-side with no re-interpretation.
 */
export function EditRequestPanel({
  projectId,
  slugs,
  editLog,
  specBefore,
  confirmBusy,
  confirmError,
  confirmErrorStatus,
  onConfirm,
  onClose,
}: {
  projectId: string;
  slugs: string[];
  editLog: EditRecord[];
  /** Current per-slug spec markdown, the "before" side of the preview diff. */
  specBefore: Record<string, string>;
  confirmBusy: boolean;
  confirmError: string | null;
  confirmErrorStatus: number | null;
  onConfirm: (document: string, resolved: ResolvedEdit) => void;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const [initialDoc] = useState(() => template(slugs[0]));
  const [doc, setDoc] = useState(initialDoc);
  const [step, setStep] = useState<"compose" | "review">("compose");
  const [preview, setPreview] = useState<EditPreviewResponse | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const textArea = useRef<HTMLTextAreaElement>(null);
  const dialog = useRef<HTMLDivElement>(null);

  const previewMut = useMutation({
    mutationFn: (document: string) => api.previewEdit(projectId, document),
    onSuccess: (response) => {
      setPreview(response);
      setStep("review");
    },
  });

  const busy = confirmBusy || previewMut.isPending;
  // A 409 on confirm means the project changed since this preview.
  const stale = confirmErrorStatus === 409;

  // Focus the editor on open; restore focus to the trigger on close.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    textArea.current?.focus();
    return () => previous?.focus();
  }, []);

  const requestClose = useCallback(() => {
    if (busy) return;
    const dirty = doc.trim() !== initialDoc.trim() && doc.trim() !== "";
    if (dirty && !window.confirm("Discard this edit request?")) return;
    onClose();
  }, [busy, doc, initialDoc, onClose]);

  // Escape closes (with the discard confirm); Tab wraps inside the dialog.
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      requestClose();
      return;
    }
    if (e.key !== "Tab" || !dialog.current) return;
    const focusables = dialog.current.querySelectorAll<HTMLElement>(
      'button, [href], input, textarea, summary, [tabindex]:not([tabindex="-1"])',
    );
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  async function loadFile(file: File | undefined) {
    if (!file) return;
    setDoc(await file.text());
  }

  function insertSection(slug: string) {
    setDoc((d) => `${d.replace(/\n+$/, "\n")}${workflowSection(slug)}`);
    textArea.current?.focus();
  }

  function backToCompose() {
    setStep("compose");
    setPreview(null);
    previewMut.reset();
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-6"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) requestClose();
      }}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-request-title"
        onKeyDown={onKeyDown}
        className="card relative flex max-h-full w-full max-w-2xl flex-col overflow-hidden bg-[var(--surface)] p-4"
      >
        {busy && (
          <RunningOverlay
            title={
              previewMut.isPending ? "Previewing edit request" : "Applying previewed edit"
            }
            steps={previewMut.isPending ? PREVIEW_STEPS : ["Applying patches"]}
            stepSeconds={12}
          />
        )}
        <div className="mb-2 flex items-center justify-between">
          <h3 id="edit-request-title" className="eyebrow">
            {step === "compose" ? "Edit request" : "Edit request — preview"}
          </h3>
          <button onClick={requestClose} className="btn btn-ghost" disabled={busy}>
            Close
          </button>
        </div>

        {step === "compose" ? (
          <>
            <p className="mb-2 text-xs text-[var(--muted)]">
              For quick wording fixes, edit the spec text directly in the Spec
              tab. Submit an <span className="font-medium">edit request</span>{" "}
              when you want changes interpreted and applied for you, with an
              audit-log entry — see the{" "}
              <Link href="/guide/edits" target="_blank" className="link-accent">
                edit format guide
              </Link>
              . Nothing is applied until you confirm the preview.
            </p>
            {slugs.length > 0 && (
              <div className="mb-2 flex flex-wrap items-center gap-1">
                <span className="text-[11px] text-[var(--faint)]">
                  Insert workflow section:
                </span>
                {slugs.map((slug) => (
                  <button
                    key={slug}
                    onClick={() => insertSection(slug)}
                    disabled={busy || doc.includes(`## Workflow: ${slug}`)}
                    title={
                      doc.includes(`## Workflow: ${slug}`)
                        ? "Already in the document"
                        : `Add a '## Workflow: ${slug}' section`
                    }
                    className="cursor-pointer rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-2 py-0.5 font-mono text-[11px] text-[var(--muted)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:cursor-default disabled:opacity-40"
                  >
                    {slug}
                  </button>
                ))}
              </div>
            )}
            <label
              htmlFor="edit-request-doc"
              className="mb-1 text-[11px] font-medium text-[var(--muted)]"
            >
              Edit request document
            </label>
            <textarea
              id="edit-request-doc"
              ref={textArea}
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
              {user && (
                <span className="text-[11px] text-[var(--faint)]">
                  Editing as{" "}
                  <span className="font-medium">{user.display_name}</span>
                </span>
              )}
              <button
                onClick={() => previewMut.mutate(doc)}
                disabled={busy || !doc.trim()}
                className="btn btn-gate ml-auto"
              >
                {previewMut.isPending ? "Previewing…" : "Preview edit"}
              </button>
            </div>
            {previewMut.error && (
              <p
                role="alert"
                className="tone-block mt-2 rounded-md border p-2 text-xs whitespace-pre-wrap"
              >
                {(previewMut.error as ApiError).message}
              </p>
            )}
          </>
        ) : (
          preview && (
            <div className="flex min-h-0 flex-col">
              <p className="mb-2 text-xs text-[var(--muted)]">
                This is what will change.{" "}
                <span className="font-medium">Nothing has been applied yet</span>{" "}
                — confirm to apply exactly these operations, or go back to
                rephrase.
              </p>
              <div className="min-h-0 flex-1 overflow-auto pr-1">
                {(preview.workflows_added.length > 0 ||
                  preview.workflows_removed.length > 0) && (
                  <div className="mb-2 flex flex-wrap gap-1">
                    {preview.workflows_added.map((slug) => (
                      <span key={slug} className="pill tone-pass">
                        + {slug}
                      </span>
                    ))}
                    {preview.workflows_removed.map((slug) => (
                      <span key={slug} className="pill tone-block">
                        − {slug}
                      </span>
                    ))}
                  </div>
                )}
                {Object.entries(preview.record.summary).map(([slug, lines]) => (
                  <div key={slug} className="mb-3">
                    <p className="font-mono text-xs font-semibold text-[var(--ink)]">
                      {slug}
                    </p>
                    <ul className="mt-1 flex flex-col gap-0.5 text-xs">
                      {lines.map((line, i) => (
                        <li
                          key={i}
                          className={
                            line.startsWith("warning:") ||
                            line.startsWith("skipped")
                              ? "text-[var(--gate)]"
                              : "text-[var(--muted)]"
                          }
                        >
                          • {line}
                        </li>
                      ))}
                    </ul>
                    <SlugDiff
                      before={specBefore[slug] ?? ""}
                      after={preview.spec_markdown[slug] ?? ""}
                    />
                  </div>
                ))}
              </div>
              {stale && (
                <p
                  role="alert"
                  className="tone-gate mt-2 rounded-md border p-2 text-xs"
                >
                  The project changed since this preview — preview again to
                  continue.
                </p>
              )}
              {confirmError && !stale && (
                <p
                  role="alert"
                  className="tone-block mt-2 rounded-md border p-2 text-xs whitespace-pre-wrap"
                >
                  {confirmError}
                </p>
              )}
              <div className="mt-3 flex items-center gap-2 border-t border-[var(--border)] pt-3">
                <button onClick={backToCompose} className="btn btn-ghost" disabled={busy}>
                  ← Back
                </button>
                {stale ? (
                  <button
                    onClick={() => previewMut.mutate(doc)}
                    disabled={busy}
                    className="btn btn-gate ml-auto"
                  >
                    Preview again
                  </button>
                ) : (
                  <button
                    onClick={() => onConfirm(doc, preview.resolved)}
                    disabled={busy}
                    className="btn btn-pass ml-auto"
                  >
                    {confirmBusy ? "Applying…" : "Confirm & apply"}
                  </button>
                )}
              </div>
            </div>
          )
        )}

        {step === "compose" && editLog.length > 0 && (
          <p className="mt-3 border-t border-[var(--border)] pt-2 text-xs text-[var(--muted)]">
            {editLog.length} previous edit{editLog.length === 1 ? "" : "s"} — see{" "}
            <span className="font-medium">Edit history</span> in the sidebar.
          </p>
        )}
      </div>
    </div>
  );
}

function SlugDiff({ before, after }: { before: string; after: string }) {
  const { added, removed } = lineDiff(before, after);
  if (added.length === 0 && removed.length === 0) return null;
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-[11px] text-[var(--faint)]">
        Spec diff (+{added.length} / −{removed.length} lines)
      </summary>
      <pre className="mt-1 max-h-40 overflow-auto rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
        {removed.map((line, i) => (
          <span key={`r${i}`} className="block text-[var(--block)]">
            − {line}
          </span>
        ))}
        {added.map((line, i) => (
          <span key={`a${i}`} className="block text-[var(--pass)]">
            + {line}
          </span>
        ))}
      </pre>
    </details>
  );
}

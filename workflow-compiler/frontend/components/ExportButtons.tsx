"use client";

import { useState } from "react";

import { api, ApiError, saveDownload } from "@/lib/api";
import type { ChangeStepKind } from "@/lib/types";

type Format = "docx" | "md" | "xlsx";

const FORMAT_LABEL: Record<Format, string> = {
  docx: "Word (.docx)",
  md: "Markdown (.md)",
  xlsx: "Test cases (.xlsx)",
};

/**
 * Deterministic export buttons for one artifact: Word (the stories artifact
 * downloads a zip with one document per story), the markdown source, and — for
 * the impact analysis — the affected-test-cases preview workbook. Unapproved
 * artifacts export as the latest version labelled DRAFT (the server suffixes
 * the filename with -DRAFT); the caller shows that in the button title.
 */
export function ArtifactExportButtons({
  crId,
  kind,
  approved,
  disabled,
}: {
  crId: string;
  kind: ChangeStepKind;
  approved: boolean;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState<Format | null>(null);
  const [error, setError] = useState<string | null>(null);
  const formats: Format[] = kind === "impact" ? ["docx", "xlsx", "md"] : ["docx", "md"];

  async function run(format: Format) {
    setBusy(format);
    setError(null);
    try {
      saveDownload(await api.exportChangeArtifact(crId, kind, format));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const hint = approved
    ? "Export the approved version"
    : "Not approved yet — exports the latest version labelled DRAFT";
  return (
    <div className="flex flex-wrap items-center gap-1" data-testid="artifact-export">
      <span className="text-xs text-[var(--faint)]">Export:</span>
      {formats.map((format) => (
        <button
          key={format}
          type="button"
          className="btn btn-ghost text-xs"
          disabled={disabled || busy !== null}
          title={`${FORMAT_LABEL[format]} — ${hint}${
            kind === "stories" && format === "docx" ? " (zip with one document per story)" : ""
          }`}
          onClick={() => run(format)}
        >
          {busy === format ? "…" : `.${format}`}
        </button>
      ))}
      {error && <span className="text-xs text-[var(--block)]">{error}</span>}
    </div>
  );
}

/** "Export all" — every artifact as Word/Excel + markdown sources + manifest in one zip. */
export function ExportAllButton({ crId, disabled }: { crId: string; disabled?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      saveDownload(await api.exportChangeRequestZip(crId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button
        type="button"
        className="btn btn-ghost text-xs"
        disabled={disabled || busy}
        onClick={run}
        title="Download every drafted artifact as Word/Excel plus the markdown sources (zip)"
      >
        {busy ? "Exporting…" : "Export all (.zip)"}
      </button>
      {error && <span className="text-xs text-[var(--block)]">{error}</span>}
    </>
  );
}

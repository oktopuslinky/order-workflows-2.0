import type { KnowledgeBaseStatus } from "@/lib/types";

/** Status pill for a knowledge base (ready / indexing… / failed). */
export function KbStatusPill({
  status,
  running,
}: {
  status: KnowledgeBaseStatus;
  running?: boolean;
}) {
  const tone =
    status === "ready" ? "tone-pass" : status === "failed" ? "tone-block" : "tone-info";
  const label = status === "ingesting" || running ? "indexing…" : status;
  return <span className={`pill ${tone}`}>{label}</span>;
}

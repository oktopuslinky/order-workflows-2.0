"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api";
import { SEVERITY_STYLE, SEVERITY_TAG } from "@/lib/format";
import type { DialogueResponse } from "@/lib/types";

/**
 * Conversational spec resolution: the compiler asks about its findings, the
 * user answers in ordinary prose, and each answer patches the spec immediately.
 *
 * The panel is deliberately thin — the server decides what to ask, when an
 * answer needs a clarifying follow-up, and when one gets parked. `prompt` is
 * always the exact text to show, so the client never has to work out whether it
 * is displaying a question or a follow-up.
 */
export function DialoguePanel({
  projectId,
  onSpecUpdated,
}: {
  projectId: string;
  /**
   * Called with the freshly rendered spec whenever an answer changed it, so the
   * workspace can adopt it. Every response carries `spec_markdown`, so the
   * caller never has to wait for the project refetch to land.
   */
  onSpecUpdated?: (specMarkdown: Record<string, string>) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<DialogueResponse | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  const state = useQuery({
    queryKey: ["dialogue", projectId],
    queryFn: () => api.getDialogue(projectId),
  });

  const session = state.data?.session ?? null;
  const prompt = state.data?.prompt ?? null;

  // After each answer the spec changed underneath the rest of the page.
  const refreshProject = () =>
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });

  const settle = (data: DialogueResponse) => {
    queryClient.setQueryData(["dialogue", projectId], data);
    setLast(data);
    setDraft("");
    setError(null);
    refreshProject();
    // Refetching the project is not enough: the workspace keeps the spec in
    // local editor buffers that only re-seed when the project id changes. Left
    // alone they would still hold the pre-dialogue text — the Spec tab would
    // show stale markdown, and Approve (which posts those buffers) would write
    // them back over everything the dialogue just applied. Hand over the
    // server's own rendering instead. Only on a real change: a skip, or merely
    // opening a session, must not disturb what the user is editing.
    if (data.changes.length > 0 || data.parked_as) {
      onSpecUpdated?.(data.spec_markdown);
    }
  };

  const fail = (e: unknown) =>
    setError(e instanceof ApiError ? e.message : "Something went wrong.");

  const start = useMutation({
    mutationFn: () => api.startDialogue(projectId),
    onSuccess: (data) => {
      settle(data);
      setLast(null);
    },
    onError: fail,
  });

  const answer = useMutation({
    mutationFn: (text: string) => api.answerDialogue(projectId, text),
    onSuccess: settle,
    onError: fail,
  });

  const skip = useMutation({
    mutationFn: () => api.skipDialogue(projectId),
    onSuccess: settle,
    onError: fail,
  });

  const end = useMutation({
    mutationFn: () => api.endDialogue(projectId),
    onSuccess: (data) => {
      settle(data);
      setLast(null);
    },
    onError: fail,
  });

  const busy =
    start.isPending || answer.isPending || skip.isPending || end.isPending;

  // Keep focus in the answer box as questions advance — this is a conversation,
  // and reaching for the mouse between every answer breaks the rhythm.
  useEffect(() => {
    if (prompt && !busy) box.current?.focus();
  }, [prompt, busy]);

  if (state.isLoading) {
    return <p className="text-sm text-[var(--muted)]">Loading…</p>;
  }

  // --- No session open ----------------------------------------------------
  if (!session) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-[var(--muted)]">
          Answer questions about this project&apos;s findings in your own words.
          Each answer updates the spec straight away — there is no form to fill
          in and nothing to save.
        </p>
        {error && <p className="text-xs tone-block rounded-md px-2.5 py-2">{error}</p>}
        <div>
          <button
            onClick={() => start.mutate()}
            disabled={busy}
            className="btn btn-primary px-3 py-1.5 text-sm"
          >
            {start.isPending ? "Reading the findings…" : "Start resolving"}
          </button>
        </div>
      </div>
    );
  }

  // --- Session finished ---------------------------------------------------
  if (!prompt) {
    const parked = session.questions.filter((q) => q.status === "parked").length;
    const skipped = session.questions.filter((q) => q.status === "skipped").length;
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm">
          <span className="font-medium">All done.</span>{" "}
          {session.questions.filter((q) => q.status === "answered").length} of{" "}
          {session.questions.length} answered
          {parked > 0 && `, ${parked} parked as open questions`}
          {skipped > 0 && `, ${skipped} skipped`}.
        </p>
        <p className="text-xs text-[var(--muted)]">
          The specs changed, so validation needs to run again before approval.
        </p>
        {last && <Outcome data={last} />}
        <div className="flex gap-2">
          <button
            onClick={() => end.mutate()}
            disabled={busy}
            className="btn btn-primary px-3 py-1.5 text-sm"
          >
            Close
          </button>
          <button
            onClick={() => start.mutate()}
            disabled={busy}
            className="btn btn-ghost px-3 py-1.5 text-sm"
          >
            Ask again
          </button>
        </div>
      </div>
    );
  }

  // --- A question is waiting ----------------------------------------------
  const q = state.data?.question ?? null;
  const answered = state.data?.answered ?? 0;
  const total = state.data?.total ?? 0;
  const position = total - (state.data?.remaining ?? 0) + 1;
  const isFollowup = (q?.followups.length ?? 0) > 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between text-xs text-[var(--muted)]">
        <span>
          Question {Math.min(position, total)} of {total}
          {answered > 0 && ` · ${answered} applied`}
        </span>
        <button
          onClick={() => end.mutate()}
          disabled={busy}
          className="btn btn-ghost px-2 py-0.5 text-xs"
        >
          Finish later
        </button>
      </div>

      <div
        className={`rounded-md border px-3 py-2.5 ${
          q ? SEVERITY_STYLE[q.severity] : "tone-info"
        }`}
      >
        <div className="flex items-center gap-2 text-xs">
          <span className="font-mono font-bold">
            {q ? SEVERITY_TAG[q.severity] : "INFO"}
          </span>
          {q?.slug && <span className="opacity-70">{q.slug}</span>}
          {q?.section && <span className="opacity-70">› {q.section}</span>}
          {isFollowup && <span className="pill ml-auto">follow-up</span>}
        </div>
        <p className="mt-1.5 text-sm leading-snug">{prompt}</p>
      </div>

      {last && <Outcome data={last} />}
      {error && <p className="text-xs tone-block rounded-md px-2.5 py-2">{error}</p>}

      <textarea
        ref={box}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends; Shift+Enter is a newline. Answers are usually a sentence.
          if (e.key === "Enter" && !e.shiftKey && draft.trim() && !busy) {
            e.preventDefault();
            answer.mutate(draft.trim());
          }
        }}
        rows={3}
        disabled={busy}
        placeholder="Answer in your own words…"
        className="w-full resize-y rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
      />

      <div className="flex items-center gap-2">
        <button
          onClick={() => answer.mutate(draft.trim())}
          disabled={busy || !draft.trim()}
          className="btn btn-primary px-3 py-1.5 text-sm"
        >
          {answer.isPending ? "Applying…" : "Answer"}
        </button>
        <button
          onClick={() => skip.mutate()}
          disabled={busy}
          className="btn btn-ghost px-3 py-1.5 text-sm"
        >
          Skip
        </button>
        <span className="ml-auto text-xs text-[var(--faint)]">
          Enter to send · Shift+Enter for a new line
        </span>
      </div>
    </div>
  );
}

/** What the previous answer did — applied changes, a park, or warnings. */
function Outcome({ data }: { data: DialogueResponse }) {
  if (!data.changes.length && !data.parked_as && !data.warnings.length) return null;
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2.5 py-2 text-xs">
      {data.changes.length > 0 && (
        <>
          <p className="font-medium text-[var(--pass)]">Applied to the spec</p>
          <ul className="mt-1 flex flex-col gap-0.5 text-[var(--muted)]">
            {data.changes.map((c, i) => (
              <li key={i} className="font-mono">
                {c}
              </li>
            ))}
          </ul>
        </>
      )}
      {data.parked_as && (
        <>
          <p className="font-medium">Recorded as an open question</p>
          <p className="mt-1 italic text-[var(--muted)]">{data.parked_as}</p>
        </>
      )}
      {data.warnings.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-[var(--gate)]">
          {data.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

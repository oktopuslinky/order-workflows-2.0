"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api";
import { SuggestedAnswers } from "@/components/SuggestedAnswers";
import type { SpecChatResponse, SpecChatTurn } from "@/lib/types";

/**
 * Free-form spec editing: the user says what they want changed and it is
 * patched straight into the spec.
 *
 * The other door to the same gate as `DialoguePanel`. That one works from an
 * agenda — the validator asks, the user answers. This one runs the other
 * direction and needs no prior validate, so it is available the moment a
 * project has specs.
 *
 * The panel stays thin for the same reason: the server decides whether an
 * instruction applied, needs one clarifying question, or gets parked. The
 * client only renders the transcript it is handed.
 */
export function SpecChatPanel({
  projectId,
  slugs,
  onSpecUpdated,
}: {
  projectId: string;
  /** Workflow slugs in this project; the picker only appears when there are 2+. */
  slugs: string[];
  /**
   * Called with the freshly rendered spec whenever a message changed it. Same
   * contract as DialoguePanel: every response carries `spec_markdown`, so the
   * workspace adopts the server's own rendering rather than racing a refetch.
   */
  onSpecUpdated?: (specMarkdown: Record<string, string>) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  // The suggestion the draft came from, cleared as soon as the user edits it.
  const [picked, setPicked] = useState<string | null>(null);
  const [slug, setSlug] = useState<string>(slugs[0] ?? "");
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const tail = useRef<HTMLDivElement>(null);

  const state = useQuery({
    queryKey: ["spec-chat", projectId],
    queryFn: () => api.getSpecChat(projectId),
  });

  const session = state.data?.session ?? null;
  const turns = session?.turns ?? [];
  const awaiting = state.data?.awaiting_clarification ?? false;
  const options = state.data?.options ?? [];

  // Keep the chosen workflow valid if the project's specs change underneath us.
  useEffect(() => {
    if (slugs.length > 0 && !slugs.includes(slug)) setSlug(slugs[0]);
  }, [slugs, slug]);

  const settle = (data: SpecChatResponse) => {
    queryClient.setQueryData(["spec-chat", projectId], data);
    setDraft("");
    setPicked(null);
    setError(null);
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    // Only on a real change — merely reading the transcript back must not
    // disturb what the user is editing in the Spec tab. See DialoguePanel.
    if (data.changes.length > 0 || data.parked_as) {
      onSpecUpdated?.(data.spec_markdown);
    }
  };

  const fail = (e: unknown) =>
    setError(e instanceof ApiError ? e.message : "Something went wrong.");

  const send = useMutation({
    mutationFn: (text: string) =>
      // While a clarification is open the server already knows which spec it
      // concerns; re-sending the picker's value would let a stray click
      // redirect the reply to a different workflow.
      api.sendSpecChat(
        projectId,
        text,
        awaiting ? null : slug || null,
        text === picked ? picked : null,
      ),
    onSuccess: settle,
    onError: fail,
  });

  const clear = useMutation({
    mutationFn: () => api.endSpecChat(projectId),
    onSuccess: settle,
    onError: fail,
  });

  const busy = send.isPending || clear.isPending;

  useEffect(() => {
    if (!busy) box.current?.focus();
  }, [busy, turns.length]);

  useEffect(() => {
    tail.current?.scrollIntoView({ block: "end" });
  }, [turns.length, busy]);

  if (state.isLoading) {
    return <p className="text-sm text-[var(--muted)]">Loading…</p>;
  }

  const submit = () => {
    const text = draft.trim();
    if (text && !busy) send.mutate(text);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2 text-xs text-[var(--muted)]">
        <span>
          {turns.length === 0
            ? "Say what you want changed — it is applied straight away."
            : `${state.data?.applied ?? 0} change${
                (state.data?.applied ?? 0) === 1 ? "" : "s"
              } applied`}
        </span>
        {turns.length > 0 && (
          <button
            onClick={() => clear.mutate()}
            disabled={busy}
            className="btn btn-ghost px-2 py-0.5 text-xs"
          >
            Clear chat
          </button>
        )}
      </div>

      {slugs.length > 1 && (
        <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
          <span>Workflow</span>
          <select
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            disabled={busy || awaiting}
            className="rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-xs text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
          >
            {slugs.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {awaiting && <span className="opacity-70">answering a question</span>}
        </label>
      )}

      {turns.length === 0 ? (
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 text-xs text-[var(--muted)]">
          <p className="text-[var(--ink)]">Try things like:</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            <li>&ldquo;add a refund step after the payment is confirmed&rdquo;</li>
            <li>&ldquo;the retry timeout should be 30 seconds&rdquo;</li>
            <li>&ldquo;warehouse is a team, not a system&rdquo;</li>
          </ul>
          <p className="mt-2">
            Every change re-arms the gate, so validation runs again before
            approval.
          </p>
        </div>
      ) : (
        <div className="flex max-h-[26rem] flex-col gap-2 overflow-y-auto pr-1">
          {turns.map((turn) => (
            <Turn key={turn.turn_id} turn={turn} />
          ))}
          {send.isPending && (
            <p className="text-xs italic text-[var(--muted)]">Working on it…</p>
          )}
          <div ref={tail} />
        </div>
      )}

      {error && <p className="text-xs tone-block rounded-md px-2.5 py-2">{error}</p>}

      {/* Only ever populated on a clarifying question — the same vague-answer
          moment where concrete choices help most in the guided panel. */}
      <SuggestedAnswers
        options={options}
        picked={picked}
        disabled={busy}
        hint="Some likely answers — pick one to edit and send, or just write your own."
        onPick={(option) => {
          setDraft(option.label);
          setPicked(option.label);
          box.current?.focus();
        }}
      />

      <textarea
        ref={box}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          if (picked !== null && e.target.value !== picked) setPicked(null);
        }}
        onKeyDown={(e) => {
          // Enter sends; Shift+Enter is a newline — same as the guided panel.
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        rows={3}
        disabled={busy}
        placeholder={
          awaiting ? "Answer the question above…" : "What should change?"
        }
        className="w-full resize-y rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
      />

      <div className="flex items-center gap-2">
        <button
          onClick={submit}
          disabled={busy || !draft.trim()}
          className="btn btn-primary px-3 py-1.5 text-sm"
        >
          {send.isPending ? "Applying…" : "Send"}
        </button>
        <span className="ml-auto text-xs text-[var(--faint)]">
          Enter to send · Shift+Enter for a new line
        </span>
      </div>
    </div>
  );
}

/** One turn of the transcript. */
function Turn({ turn }: { turn: SpecChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="self-end rounded-md border border-[var(--border-strong)] bg-[var(--surface-raised)] px-2.5 py-1.5 text-sm">
        {turn.text}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      <div
        className={`rounded-md border px-2.5 py-1.5 text-sm ${
          turn.status === "clarifying" ? "tone-gate" : "tone-info"
        }`}
      >
        <div className="flex items-center gap-2 text-xs">
          <span className="font-mono font-bold">{STATUS_TAG[turn.status ?? "no_change"]}</span>
          {turn.slug && <span className="opacity-70">{turn.slug}</span>}
        </div>
        <p className="mt-1 leading-snug">{turn.text}</p>
      </div>
      {turn.changes.length > 0 && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2.5 py-2 text-xs">
          <p className="font-medium text-[var(--pass)]">Applied to the spec</p>
          <ul className="mt-1 flex flex-col gap-0.5 text-[var(--muted)]">
            {turn.changes.map((c, i) => (
              <li key={i} className="font-mono">
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
      {turn.parked_as && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2.5 py-2 text-xs">
          <p className="font-medium">Recorded as an open question</p>
          <p className="mt-1 italic text-[var(--muted)]">{turn.parked_as}</p>
        </div>
      )}
      {turn.warnings.length > 0 && (
        <ul className="flex flex-col gap-0.5 px-2.5 text-xs text-[var(--gate)]">
          {turn.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

const STATUS_TAG: Record<string, string> = {
  applied: "APPLIED",
  clarifying: "QUESTION",
  parked: "PARKED",
  no_change: "NO CHANGE",
};

"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { SuggestedAnswers } from "@/components/SuggestedAnswers";
import { STEP_LABEL } from "@/components/ChangeStagePill";
import type {
  ChangeRequestResponse,
  ChangeStepKind,
  ChatTurn,
  Job,
  SuggestedOption,
  WizardStep,
} from "@/lib/types";

// Kept in sync with the backend (api/dependencies.py SELECTABLE_PROVIDERS) and
// with the knowledge page.
const PROVIDER_OPTIONS = [
  { value: "nemotron", label: "Nemotron (cloud)" },
  { value: "local-fallback", label: "Spark + cloud fallback" },
  { value: "local", label: "Spark (local only)" },
] as const;

/** Turn a failed call into the line shown under the controls. */
function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "A job is already running for this change request — wait for it to finish.";
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

/**
 * The conversation for one wizard step: the stored transcript, then whatever
 * the step needs from the user right now — start the wizard, answer a question,
 * ask for a draft, or send a revision. Every mutation hands the fresh
 * ChangeRequestResponse back to the page through `onResponse`.
 */
export function ChangeChat({
  crId,
  step,
  isCurrent,
  started,
  question,
  questionOptions,
  job,
  artifactStatus,
  defaultProvider,
  onResponse,
}: {
  crId: string;
  step: WizardStep;
  isCurrent: boolean;
  /** wizard.started_at is set. */
  started: boolean;
  question: string | null;
  questionOptions: SuggestedOption[];
  /** The running job for this change request, if any. */
  job: Job | undefined;
  artifactStatus: "empty" | "drafted" | "approved";
  defaultProvider: string | null;
  onResponse: (data: ChangeRequestResponse) => void;
}) {
  const [draft, setDraft] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [revision, setRevision] = useState("");
  const [provider, setProvider] = useState<string>(defaultProvider ?? "nemotron");
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const transcript = useRef<HTMLDivElement>(null);

  const running = job?.status === "running";
  const kind: ChangeStepKind = step.kind;

  // Keep the transcript scrolled to the newest turn.
  useEffect(() => {
    const el = transcript.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [step.turns.length, question, running]);

  // Reset the answer box when the question changes (derived during render, so
  // no cascading effect).
  const [lastQuestion, setLastQuestion] = useState(question);
  if (question !== lastQuestion) {
    setLastQuestion(question);
    setDraft("");
    setPicked(null);
  }

  const settle = (data: ChangeRequestResponse) => {
    setError(null);
    onResponse(data);
  };
  const fail = (err: unknown) => setError(describe(err));

  const start = useMutation({
    mutationFn: () => api.startChangeWizard(crId, { provider }),
    onSuccess: settle,
    onError: fail,
  });
  const answer = useMutation({
    mutationFn: (vars: { answer: string; option: string | null }) =>
      api.answerChangeWizard(crId, vars.answer, vars.option),
    onSuccess: (data) => {
      setDraft("");
      setPicked(null);
      settle(data);
    },
    onError: fail,
  });
  const skip = useMutation({
    mutationFn: () => api.skipChangeWizard(crId),
    onSuccess: settle,
    onError: fail,
  });
  const draftNow = useMutation({
    mutationFn: () => api.draftChangeWizard(crId, kind),
    onSuccess: settle,
    onError: fail,
  });
  const revise = useMutation({
    mutationFn: (message: string) => api.reviseChangeWizard(crId, kind, message),
    onSuccess: (data) => {
      setRevision("");
      settle(data);
    },
    onError: fail,
  });

  const busy =
    running ||
    start.isPending ||
    answer.isPending ||
    skip.isPending ||
    draftNow.isPending ||
    revise.isPending;

  const showQuestion = isCurrent && started && !!question && !running;
  const pendingNoQuestions =
    isCurrent && started && step.status === "pending" && step.questions.length === 0 && !running;
  const canDraft = (isCurrent || artifactStatus === "drafted") && artifactStatus !== "approved";
  const hasArtifact = artifactStatus !== "empty";

  const submitAnswer = () => {
    const text = draft.trim();
    if (!text || busy) return;
    answer.mutate({ answer: text, option: picked !== null && text === picked ? picked : null });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Transcript */}
      <div
        ref={transcript}
        className="flex max-h-[28rem] min-h-[8rem] flex-col gap-2 overflow-auto rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3"
        data-testid="change-transcript"
      >
        {step.turns.length === 0 && !showQuestion && (
          <p className="text-xs text-[var(--faint)]">
            {started
              ? isCurrent
                ? "Nothing yet for this step."
                : "This step has not been reached yet."
              : "Start the wizard to begin the conversation for this step."}
          </p>
        )}
        {step.turns.map((t, i) => (
          <Turn key={`${t.at}-${i}`} turn={t} />
        ))}
        {showQuestion && (
          <div className="rounded-md border px-2.5 py-2 tone-gate">
            <div className="flex items-center gap-2 text-xs">
              <span className="font-mono font-bold">QUESTION</span>
              <span className="opacity-70">{STEP_LABEL[kind]}</span>
            </div>
            <p className="mt-1 text-sm leading-snug">{question}</p>
            {currentWhy(step, question) && (
              <p className="mt-1 text-xs opacity-80">Why: {currentWhy(step, question)}</p>
            )}
          </div>
        )}
        {running && job && (
          <div className="rounded-md border px-2.5 py-2 text-xs tone-accent" role="status">
            <span className="font-mono font-bold">
              {job.kind === "cr_questions"
                ? "DRAFTING QUESTIONS"
                : job.kind === "cr_revise"
                  ? "REVISING"
                  : "DRAFTING"}
            </span>
            {job.progress?.message && <span className="ml-2">{job.progress.message}</span>}
            {job.progress?.total ? (
              <span className="ml-1 tabular-nums">
                ({job.progress.done}/{job.progress.total})
              </span>
            ) : null}
            <span className="ml-2 animate-pulse">…</span>
          </div>
        )}
      </div>

      {step.error && (
        <p className="tone-block rounded-md border px-2.5 py-2 text-xs">{step.error}</p>
      )}
      {step.notes.length > 0 && (
        <details className="rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs">
          <summary className="cursor-pointer text-[var(--muted)]">
            Decisions ({step.notes.length})
          </summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[var(--muted)]">
            {step.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </details>
      )}

      {error && <p className="tone-block rounded-md border px-2.5 py-2 text-xs">{error}</p>}

      {/* Live control */}
      {!started ? (
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={busy}
            aria-label="Provider"
            className="cursor-pointer rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-xs text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
          >
            {PROVIDER_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-primary px-3 py-1.5 text-sm"
            disabled={busy}
            onClick={() => start.mutate()}
          >
            {start.isPending ? "Starting…" : "Start wizard"}
          </button>
          <span className="text-xs text-[var(--faint)]">
            Drafts the impact questions from the BCR and the knowledge base.
          </span>
        </div>
      ) : (
        <>
          {showQuestion && (
            <>
              <SuggestedAnswers
                options={questionOptions}
                picked={picked}
                disabled={busy}
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
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submitAnswer();
                  }
                }}
                rows={3}
                disabled={busy}
                placeholder="Answer in your own words…"
                className="w-full resize-y rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
                data-testid="change-answer"
              />
            </>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {showQuestion && (
              <>
                <button
                  type="button"
                  onClick={submitAnswer}
                  disabled={busy || !draft.trim()}
                  className="btn btn-primary px-3 py-1.5 text-sm"
                >
                  {answer.isPending ? "Applying…" : "Answer"}
                </button>
                <button
                  type="button"
                  onClick={() => skip.mutate()}
                  disabled={busy}
                  className="btn btn-ghost px-3 py-1.5 text-sm"
                >
                  {skip.isPending ? "…" : "Skip"}
                </button>
              </>
            )}
            {pendingNoQuestions && (
              <button
                type="button"
                onClick={() => start.mutate()}
                disabled={busy}
                className="btn btn-ghost px-3 py-1.5 text-sm"
                title="Draft the questions for this step"
              >
                {start.isPending ? "…" : "Ask questions"}
              </button>
            )}
            {canDraft && (
              <button
                type="button"
                onClick={() => draftNow.mutate()}
                disabled={busy}
                className={`btn px-3 py-1.5 text-sm ${
                  showQuestion ? "btn-ghost" : "btn-primary"
                }`}
                title={
                  hasArtifact
                    ? "Draft this artifact again from the answers so far"
                    : "Skip the remaining questions and draft the artifact now"
                }
              >
                {draftNow.isPending ? "Starting…" : hasArtifact ? "Re-draft" : "Draft now"}
              </button>
            )}
            {answer.isPending && (
              <span className="text-xs text-[var(--faint)]">
                Interpreting the answer — usually 10–40 s…
              </span>
            )}
          </div>

          {hasArtifact && artifactStatus !== "approved" && (
            <form
              className="flex items-start gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (revision.trim() && !busy) revise.mutate(revision.trim());
              }}
            >
              <textarea
                value={revision}
                onChange={(e) => setRevision(e.target.value)}
                rows={2}
                disabled={busy}
                placeholder={`Revise the ${STEP_LABEL[kind]} draft — e.g. "add a rollback story"`}
                className="flex-1 resize-y rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
                data-testid="change-revision"
              />
              <button
                type="submit"
                disabled={busy || !revision.trim()}
                className="btn btn-ghost px-3 py-1.5 text-sm"
              >
                {revise.isPending ? "…" : "Revise"}
              </button>
            </form>
          )}
        </>
      )}
    </div>
  );
}

/** The `why` hint for whichever question is currently open, if we can find it. */
function currentWhy(step: WizardStep, question: string | null): string | null {
  if (!question) return null;
  const q = step.questions.find(
    (x) => x.status === "pending" && (x.text === question || x.followups.includes(question)),
  );
  return q?.why || null;
}

const KIND_TAG: Partial<Record<ChatTurn["kind"], string>> = {
  question: "QUESTION",
  followup: "FOLLOW-UP",
  draft: "DRAFT",
  revision: "REVISION",
  edit: "EDIT",
  approve: "APPROVED",
  note: "NOTE",
  status: "STATUS",
};

/** One turn of the transcript. */
function Turn({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="max-w-[90%] self-end rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 text-sm whitespace-pre-wrap">
        {turn.text}
      </div>
    );
  }
  if (turn.role === "system") {
    return (
      <div className="self-center text-center text-[11px] text-[var(--faint)]">
        {KIND_TAG[turn.kind] && <span className="font-mono">{KIND_TAG[turn.kind]} · </span>}
        {turn.text}
      </div>
    );
  }
  const isQuestion = turn.kind === "question" || turn.kind === "followup";
  const tone =
    isQuestion
      ? "tone-gate"
      : turn.kind === "draft" || turn.kind === "revision"
        ? "tone-accent"
        : turn.kind === "approve"
          ? "tone-pass"
          : "tone-info";
  return (
    <div className={`max-w-[95%] self-start rounded-md border px-2.5 py-1.5 text-sm ${tone}`}>
      {KIND_TAG[turn.kind] && (
        <div className="text-xs">
          <span className="font-mono font-bold">{KIND_TAG[turn.kind]}</span>
        </div>
      )}
      <p className="mt-0.5 leading-snug whitespace-pre-wrap">{turn.text}</p>
    </div>
  );
}

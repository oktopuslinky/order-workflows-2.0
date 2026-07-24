"use client";

// Structured affordances over the spec Markdown. Each widget renders from a
// light parse of the current Markdown and edits it back via lib/spec-grammar,
// so the Markdown stays the single source of truth.

import { useState } from "react";
import {
  deleteTrigger,
  parseCheckboxes,
  parseEvents,
  parseQuestions,
  parseTriggers,
  removedBulletLines,
  setCheckbox,
  setEventKind,
  setQuestionAnswer,
  setTriggerChecked,
} from "@/lib/spec-grammar";
import type { EventKind } from "@/lib/types";

function Panel({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="card p-3">
      <h3 className="eyebrow mb-2 flex items-center gap-2">
        {title}
        {count !== undefined && (
          <span className="rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-1.5 text-[10px] text-[var(--muted)]">
            {count}
          </span>
        )}
      </h3>
      {children}
    </section>
  );
}

export function OpenQuestions({
  markdown,
  onChange,
}: {
  markdown: string;
  onChange: (md: string) => void;
}) {
  const questions = parseQuestions(markdown);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  if (questions.length === 0) return null;

  return (
    <Panel title="Open questions" count={questions.length}>
      <ul className="flex flex-col gap-3">
        {questions.map((q) => {
          const draft = drafts[q.line] ?? q.answer;
          return (
            <li key={q.line} className="text-sm">
              <div className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={q.resolved}
                  onChange={(e) =>
                    onChange(
                      setQuestionAnswer(markdown, q.line, draft, e.target.checked),
                    )
                  }
                  className="mt-1"
                />
                <span className={q.resolved ? "text-[var(--faint)] line-through" : ""}>
                  {q.ref && (
                    <span className="mr-1 font-mono text-[10px] text-[var(--accent)]">
                      {q.ref}
                    </span>
                  )}
                  {q.text}
                </span>
              </div>
              <input
                value={draft}
                placeholder="Answer…"
                onChange={(e) =>
                  setDrafts((d) => ({ ...d, [q.line]: e.target.value }))
                }
                onBlur={(e) =>
                  onChange(
                    setQuestionAnswer(
                      markdown,
                      q.line,
                      e.target.value,
                      e.target.value.trim().length > 0 ? true : q.resolved,
                    ),
                  )
                }
                className="mt-1 ml-6 w-[calc(100%-1.5rem)] rounded-md border border-[var(--border-strong)] bg-transparent px-2 py-1 text-xs outline-none focus:border-[var(--accent)]"
              />
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

export function DependencyChecklist({
  markdown,
  onChange,
}: {
  markdown: string;
  onChange: (md: string) => void;
}) {
  const deps = parseCheckboxes(markdown, "Cross-Workflow Dependencies");
  if (deps.length === 0) return null;
  return (
    <Panel title="Cross-workflow dependencies" count={deps.length}>
      <ul className="flex flex-col gap-2 text-sm">
        {deps.map((d) => (
          <li key={d.line} className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={d.checked}
              onChange={(e) => onChange(setCheckbox(markdown, d.line, e.target.checked))}
              className="mt-1"
            />
            <span className={d.checked ? "" : "text-[var(--gate)]"}>
              {d.text}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-[var(--faint)]">
        Unconfirmed dependencies block approval unless overridden.
      </p>
    </Panel>
  );
}

export function TriggerCards({
  markdown,
  onChange,
}: {
  markdown: string;
  onChange: (md: string) => void;
}) {
  const triggers = parseTriggers(markdown);
  if (triggers.length === 0) return null;
  return (
    <Panel title="Triggers" count={triggers.length}>
      <ul className="flex flex-col gap-2">
        {triggers.map((t) => (
          <li
            key={t.line}
            className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2 text-sm"
          >
            <div className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={t.checked}
                  onChange={(e) =>
                    onChange(setTriggerChecked(markdown, t.line, e.target.checked))
                  }
                />
                <span>
                  triggers <span className="font-mono text-[var(--accent)]">{t.target}</span>{" "}
                  <span className="text-xs text-[var(--muted)]">({t.mode})</span>
                </span>
              </label>
              <button
                onClick={() => onChange(deleteTrigger(markdown, t.line, t.endLine))}
                className="cursor-pointer rounded px-1.5 py-0.5 text-xs text-[var(--block)] hover:bg-[var(--block-soft)]"
                title="Delete this trigger"
              >
                Delete
              </button>
            </div>
            {t.condition && (
              <p className="mt-1 pl-6 text-xs text-[var(--muted)]">
                when <span className="font-mono">{t.condition}</span>
              </p>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-[var(--faint)]">
        Delete a trigger that should not fire (e.g. a customer-initiated flow).
      </p>
    </Panel>
  );
}

const KIND_LABEL: Record<EventKind, string> = {
  trigger: "trigger (starts workflow)",
  signal_wait: "signal_wait (bounded pause)",
  output_emit: "output_emit (produces value)",
};

export function EventKindEditor({
  markdown,
  onChange,
}: {
  markdown: string;
  onChange: (md: string) => void;
}) {
  const events = parseEvents(markdown);
  if (events.length === 0) return null;
  return (
    <Panel title="Events" count={events.length}>
      <ul className="flex flex-col gap-2 text-sm">
        {events.map((ev) => (
          <li key={ev.line} className="flex items-center justify-between gap-2">
            <span>
              <span className="font-mono text-[10px] text-[var(--faint)]">{ev.id}</span>{" "}
              {ev.name}
            </span>
            <select
              value={ev.kind}
              onChange={(e) =>
                onChange(setEventKind(markdown, ev.line, e.target.value as EventKind))
              }
              className="cursor-pointer rounded-md border border-[var(--border-strong)] bg-transparent px-1 py-0.5 text-xs outline-none focus:border-[var(--accent)]"
            >
              {(Object.keys(KIND_LABEL) as EventKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-[var(--faint)]">
        <code>signal_wait</code> makes a wait a bounded condition instead of a hang.
      </p>
    </Panel>
  );
}

export function ValidateDiff({
  before,
  after,
  onReAdd,
}: {
  before: string;
  after: string;
  onReAdd: (line: string) => void;
}) {
  const removed = removedBulletLines(before, after);
  if (removed.length === 0) return null;
  return (
    <Panel title="Removed by validate" count={removed.length}>
      <p className="mb-2 text-[11px] text-[var(--faint)]">
        The validate pass removed these lines. If one was correct, re-add it — a
        re-added line is recorded as human-provided and sticks.
      </p>
      <ul className="flex flex-col gap-1.5">
        {removed.map((line, i) => (
          <li
            key={`${line}-${i}`}
            className="tone-block flex items-start justify-between gap-2 rounded-md border px-2 py-1 text-xs"
          >
            <code className="break-all">{line}</code>
            <button
              onClick={() => onReAdd(line)}
              className="shrink-0 cursor-pointer rounded px-1.5 py-0.5 text-[var(--accent)] hover:bg-[var(--accent-soft)]"
            >
              Re-add
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

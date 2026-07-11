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
    <section className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
        {count !== undefined && (
          <span className="rounded-full bg-slate-200 px-1.5 text-[10px] text-slate-600 dark:bg-slate-700 dark:text-slate-300">
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
                <span className={q.resolved ? "text-slate-400 line-through" : ""}>
                  {q.ref && (
                    <span className="mr-1 font-mono text-[10px] text-indigo-400">
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
                className="mt-1 ml-6 w-[calc(100%-1.5rem)] rounded border border-slate-300 bg-transparent px-2 py-1 text-xs outline-none focus:border-indigo-400 dark:border-slate-700"
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
            <span className={d.checked ? "" : "text-amber-600 dark:text-amber-400"}>
              {d.text}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-slate-400">
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
            className="rounded-md border border-slate-200 p-2 text-sm dark:border-slate-800"
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
                  triggers <span className="font-mono text-indigo-500">{t.target}</span>{" "}
                  <span className="text-xs text-slate-500">({t.mode})</span>
                </span>
              </label>
              <button
                onClick={() => onChange(deleteTrigger(markdown, t.line, t.endLine))}
                className="rounded px-1.5 py-0.5 text-xs text-red-500 hover:bg-red-500/10"
                title="Delete this trigger"
              >
                Delete
              </button>
            </div>
            {t.condition && (
              <p className="mt-1 pl-6 text-xs text-slate-500">
                when <span className="font-mono">{t.condition}</span>
              </p>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-slate-400">
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
              <span className="font-mono text-[10px] text-slate-400">{ev.id}</span>{" "}
              {ev.name}
            </span>
            <select
              value={ev.kind}
              onChange={(e) =>
                onChange(setEventKind(markdown, ev.line, e.target.value as EventKind))
              }
              className="rounded border border-slate-300 bg-transparent px-1 py-0.5 text-xs outline-none focus:border-indigo-400 dark:border-slate-700"
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
      <p className="mt-2 text-[11px] text-slate-400">
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
      <p className="mb-2 text-[11px] text-slate-400">
        The validate pass removed these lines. If one was correct, re-add it — a
        re-added line is recorded as human-provided and sticks.
      </p>
      <ul className="flex flex-col gap-1.5">
        {removed.map((line, i) => (
          <li
            key={`${line}-${i}`}
            className="flex items-start justify-between gap-2 rounded border border-red-500/30 bg-red-500/5 px-2 py-1 text-xs"
          >
            <code className="break-all text-red-600 dark:text-red-300">{line}</code>
            <button
              onClick={() => onReAdd(line)}
              className="shrink-0 rounded px-1.5 py-0.5 text-indigo-500 hover:bg-indigo-500/10"
            >
              Re-add
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

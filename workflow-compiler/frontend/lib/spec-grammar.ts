// Client-side parse/edit helpers for the spec Markdown grammar.
//
// The Markdown is the single source of truth in the editor. Structured widgets
// render from a light parse of the current Markdown and, on change, perform
// TARGETED line edits back into it — toggling `[ ]`<->`[x]`, rewriting a `kind:`
// tail, filling an `Answer:` line, or deleting a trigger block. This preserves
// the backend's deterministic round-trip (spec/renderer.py <-> spec/ingest.py).

import type { EventKind } from "./types";

const SECTION_RE = /^##\s+(.+?)\s*$/;

/** Line span [start, end) of a `## Section` body (excludes the heading line). */
function sectionBody(lines: string[], title: string): [number, number] | null {
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(SECTION_RE);
    if (m && m[1] === title) {
      start = i + 1;
      let end = lines.length;
      for (let j = start; j < lines.length; j++) {
        if (SECTION_RE.test(lines[j])) {
          end = j;
          break;
        }
      }
      return [start, end];
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Open Questions
// ---------------------------------------------------------------------------

export interface ParsedQuestion {
  line: number; // index of the `- [ ] ...` line
  answerLine: number | null; // index of the indented `Answer:` line
  resolved: boolean;
  ref: string | null;
  text: string;
  answer: string;
}

const QUESTION_RE = /^- \[([ xX])\]\s+(?:\(([^)]*)\)\s+)?(.*)$/;
const ANSWER_RE = /^\s+Answer:\s?(.*)$/;

export function parseQuestions(markdown: string): ParsedQuestion[] {
  const lines = markdown.split("\n");
  const span = sectionBody(lines, "Open Questions");
  if (!span) return [];
  const out: ParsedQuestion[] = [];
  for (let i = span[0]; i < span[1]; i++) {
    const m = lines[i].match(QUESTION_RE);
    if (!m) continue;
    let answerLine: number | null = null;
    let answer = "";
    const next = lines[i + 1]?.match(ANSWER_RE);
    if (next) {
      answerLine = i + 1;
      answer = next[1] ?? "";
    }
    out.push({
      line: i,
      answerLine,
      resolved: m[1].toLowerCase() === "x",
      ref: m[2] ?? null,
      text: m[3] ?? "",
      answer,
    });
  }
  return out;
}

/** Set a question's answer text and tick/untick it, returning new markdown. */
export function setQuestionAnswer(
  markdown: string,
  questionLine: number,
  answer: string,
  resolved: boolean,
): string {
  const lines = markdown.split("\n");
  const m = lines[questionLine]?.match(QUESTION_RE);
  if (!m) return markdown;
  const box = resolved ? "x" : " ";
  const ref = m[2] ? `(${m[2]}) ` : "";
  lines[questionLine] = `- [${box}] ${ref}${m[3] ?? ""}`;
  if (lines[questionLine + 1]?.match(ANSWER_RE)) {
    lines[questionLine + 1] = `  Answer: ${answer}`;
  } else {
    lines.splice(questionLine + 1, 0, `  Answer: ${answer}`);
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Checkbox lines (Cross-Workflow Dependencies)
// ---------------------------------------------------------------------------

export interface ParsedCheckbox {
  line: number;
  checked: boolean;
  text: string;
}

const CHECKBOX_RE = /^- \[([ xX])\]\s+(.*)$/;

export function parseCheckboxes(
  markdown: string,
  section: string,
): ParsedCheckbox[] {
  const lines = markdown.split("\n");
  const span = sectionBody(lines, section);
  if (!span) return [];
  const out: ParsedCheckbox[] = [];
  for (let i = span[0]; i < span[1]; i++) {
    const m = lines[i].match(CHECKBOX_RE);
    if (!m) continue;
    out.push({ line: i, checked: m[1].toLowerCase() === "x", text: m[2] });
  }
  return out;
}

/** Toggle the `[ ]`/`[x]` checkbox on a specific line. */
export function setCheckbox(
  markdown: string,
  line: number,
  checked: boolean,
): string {
  const lines = markdown.split("\n");
  const m = lines[line]?.match(CHECKBOX_RE);
  if (!m) return markdown;
  lines[line] = `- [${checked ? "x" : " "}] ${m[2]}`;
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Triggers (checkbox head line + indented result/input lines)
// ---------------------------------------------------------------------------

export interface ParsedTrigger {
  line: number; // head `- [ ] triggers ...` line
  endLine: number; // exclusive end of the trigger block
  checked: boolean;
  target: string;
  mode: string;
  condition: string | null;
  detailLines: string[];
}

const TRIGGER_RE =
  /^- \[([ xX])\]\s+triggers\s+`([^`]+)`\s+\(([^)]+)\)(?:\s+when\s+`([^`]*)`)?\s*$/;

export function parseTriggers(markdown: string): ParsedTrigger[] {
  const lines = markdown.split("\n");
  const span = sectionBody(lines, "Triggers");
  if (!span) return [];
  const out: ParsedTrigger[] = [];
  for (let i = span[0]; i < span[1]; i++) {
    const m = lines[i].match(TRIGGER_RE);
    if (!m) continue;
    let end = i + 1;
    const detail: string[] = [];
    while (end < span[1] && /^\s+\S/.test(lines[end]) && !TRIGGER_RE.test(lines[end])) {
      detail.push(lines[end].trim());
      end++;
    }
    out.push({
      line: i,
      endLine: end,
      checked: m[1].toLowerCase() === "x",
      target: m[2],
      mode: m[3],
      condition: m[4] ?? null,
      detailLines: detail,
    });
  }
  return out;
}

export function setTriggerChecked(
  markdown: string,
  line: number,
  checked: boolean,
): string {
  return setCheckbox(markdown, line, checked);
}

/** Delete an entire trigger block (head line plus its indented detail lines). */
export function deleteTrigger(
  markdown: string,
  line: number,
  endLine: number,
): string {
  const lines = markdown.split("\n");
  lines.splice(line, endLine - line);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Events (entity lines with a `kind:` tail)
// ---------------------------------------------------------------------------

export interface ParsedEvent {
  line: number;
  id: string;
  name: string;
  kind: EventKind;
  emittedBy: string | null;
}

const EVENT_RE = /^- \[([a-zA-Z0-9_]+)\]\s+(.+?)(?:\s+—\s+(.*))?$/;

function parseTail(tail: string | undefined): Record<string, string> {
  const pairs: Record<string, string> = {};
  if (!tail) return pairs;
  for (const part of tail.split(";")) {
    const idx = part.indexOf(":");
    if (idx === -1) continue;
    pairs[part.slice(0, idx).trim()] = part.slice(idx + 1).trim();
  }
  return pairs;
}

function normalizeKind(raw: string | undefined): EventKind {
  const v = (raw ?? "output_emit").replace(/-/g, "_").replace(/\s+/g, "_");
  if (v === "trigger" || v === "signal_wait" || v === "output_emit") return v;
  return "output_emit";
}

export function parseEvents(markdown: string): ParsedEvent[] {
  const lines = markdown.split("\n");
  const span = sectionBody(lines, "Events");
  if (!span) return [];
  const out: ParsedEvent[] = [];
  for (let i = span[0]; i < span[1]; i++) {
    const m = lines[i].match(EVENT_RE);
    if (!m) continue;
    // Strip a trailing provenance marker from the tail if present.
    const tail = (m[3] ?? "").replace(/\s*\[(human|inferred)\]\s*$/, "");
    const pairs = parseTail(tail);
    out.push({
      line: i,
      id: m[1],
      name: m[2].replace(/\s*\[(human|inferred)\]\s*$/, "").trim(),
      kind: normalizeKind(pairs["kind"]),
      emittedBy: pairs["emitted by"] ?? null,
    });
  }
  return out;
}

/** Rewrite the `kind:` value on an event line, preserving the rest of the tail. */
export function setEventKind(
  markdown: string,
  line: number,
  kind: EventKind,
): string {
  const lines = markdown.split("\n");
  const m = lines[line]?.match(EVENT_RE);
  if (!m) return markdown;
  const marker = (m[3] ?? "").match(/\s*(\[(?:human|inferred)\])\s*$/)?.[1] ?? "";
  const tail = (m[3] ?? "").replace(/\s*\[(human|inferred)\]\s*$/, "");
  const pairs = parseTail(tail);
  pairs["kind"] = kind;
  const rendered = Object.entries(pairs)
    .map(([k, v]) => `${k}: ${v}`)
    .join("; ");
  const suffix = marker ? ` ${marker}` : "";
  lines[line] = `- [${m[1]}] ${m[2].replace(/\s*\[(human|inferred)\]\s*$/, "").trim()} — ${rendered}${suffix}`;
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Section-line diff (validator removals) — used by the validate diff view.
// ---------------------------------------------------------------------------

/** Bullet lines present in `before` but missing from `after` (validator removals). */
export function removedBulletLines(before: string, after: string): string[] {
  const bullets = (s: string) =>
    s
      .split("\n")
      .map((l) => l.trimEnd())
      .filter((l) => /^-\s+/.test(l.trim()));
  const afterSet = new Set(bullets(after).map((l) => l.trim()));
  return bullets(before)
    .map((l) => l.trim())
    .filter((l) => !afterSet.has(l));
}

// Live syntax highlighting for changes.md — the change spec of a
// knowledge-graph-grounded project. Same colour vocabulary as the spec
// grammar (lib/specHighlight.ts): the component name → accent (id slot),
// `— kind, change` tail → gate, `[human]`/`[inferred]` → faint, `- path:` /
// `- requirements:` keys → ink, `#### Existing` / `#### Proposed` → heading.
//
// Grammar (what the backend parser relies on, see spec/change_renderer.py):
//   ### <name> — <kind>, <change_type> [marker]
//   - path: `…`            - requirements: A, B
//   #### Existing / #### Proposed   (free text until the next heading)
//   ## Assumptions  - <text> [marker]
//   ## Open Questions  - [ ] (<ref>) <question> [marker]  +  Answer:
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { type Extension, RangeSetBuilder } from "@codemirror/state";
import {
  Decoration,
  type DecorationSet,
  EditorView,
  ViewPlugin,
  type ViewUpdate,
} from "@codemirror/view";
import { tags as t } from "@lezer/highlight";

const markdownStyle = HighlightStyle.define([
  { tag: [t.heading1, t.heading2, t.heading3, t.heading4], class: "cm-spec-heading" },
  { tag: t.comment, class: "cm-spec-cmt" },
  { tag: t.monospace, class: "cm-spec-code" },
  { tag: t.strong, class: "cm-spec-strong" },
  { tag: t.processingInstruction, class: "cm-spec-punct" },
]);

const ID_MARK = Decoration.mark({ class: "cm-spec-id" });
const TAIL_MARK = Decoration.mark({ class: "cm-spec-tail" });
const KEY_MARK = Decoration.mark({ class: "cm-spec-key" });
const PROV_MARK = Decoration.mark({ class: "cm-spec-prov" });
const EXISTING_MARK = Decoration.mark({ class: "cm-changes-existing" });
const PROPOSED_MARK = Decoration.mark({ class: "cm-changes-proposed" });

/** `### name — kind, change [marker]` — the component heading. */
const COMPONENT_RE = /^(###\s+)(.+?)(\s+—\s+[a-z]+,\s+[a-z]+)?(\s+\[(?:human|inferred)\])?\s*$/;
/** `#### Existing` / `#### Proposed`. */
const PART_RE = /^####\s+(Existing|Proposed)\s*$/;
/** `- path:` / `- requirements:` / `- knowledge base:` … key bullets. */
const KEY_RE = /^\s*-\s+([a-z][a-z ]*:)(?=\s|$)/;
/** `- [ ] (ref) …` checkbox slot. */
const BOX_RE = /^\s*-\s+(\[(?:x| )\])/;
/** Trailing provenance marker on bullets. */
const PROV_RE = /\s(\[(?:human|inferred)\])\s*$/;
/** `  Answer:` continuation. */
const ANSWER_RE = /^\s{2,}(Answer:)(?=\s|$)/;

type Range = { from: number; to: number; deco: Decoration };

function collectLine(text: string, base: number, out: Range[]): void {
  const component = COMPONENT_RE.exec(text);
  if (component) {
    const nameStart = component[1].length;
    out.push({ from: base + nameStart, to: base + nameStart + component[2].length, deco: ID_MARK });
    if (component[3]) {
      const tailStart = nameStart + component[2].length;
      out.push({ from: base + tailStart, to: base + tailStart + component[3].length, deco: TAIL_MARK });
    }
    if (component[4]) {
      const provStart = text.lastIndexOf(component[4].trim());
      out.push({ from: base + provStart, to: base + provStart + component[4].trim().length, deco: PROV_MARK });
    }
    return;
  }
  const part = PART_RE.exec(text);
  if (part) {
    const start = text.indexOf(part[1]);
    out.push({
      from: base + start,
      to: base + start + part[1].length,
      deco: part[1] === "Existing" ? EXISTING_MARK : PROPOSED_MARK,
    });
    return;
  }
  const answer = ANSWER_RE.exec(text);
  if (answer) {
    const start = text.indexOf(answer[1]);
    out.push({ from: base + start, to: base + start + answer[1].length, deco: KEY_MARK });
    return;
  }
  const box = BOX_RE.exec(text);
  if (box) {
    const start = text.indexOf(box[1]);
    out.push({ from: base + start, to: base + start + box[1].length, deco: ID_MARK });
  } else {
    const key = KEY_RE.exec(text);
    if (key) {
      const start = text.indexOf(key[1]);
      out.push({ from: base + start, to: base + start + key[1].length, deco: KEY_MARK });
    }
  }
  const prov = PROV_RE.exec(text);
  if (prov) {
    const start = text.lastIndexOf(prov[1]);
    out.push({ from: base + start, to: base + start + prov[1].length, deco: PROV_MARK });
  }
}

function buildDecorations(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  for (const { from, to } of view.visibleRanges) {
    let pos = from;
    while (pos <= to) {
      const line = view.state.doc.lineAt(pos);
      const ranges: Range[] = [];
      collectLine(line.text, line.from, ranges);
      ranges.sort((a, b) => a.from - b.from || a.to - b.to);
      for (const r of ranges) builder.add(r.from, r.to, r.deco);
      pos = line.to + 1;
    }
  }
  return builder.finish();
}

const changesAnatomy = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = buildDecorations(view);
    }
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.decorations = buildDecorations(update.view);
      }
    }
  },
  { decorations: (v) => v.decorations },
);

export const changesHighlight: Extension = [syntaxHighlighting(markdownStyle), changesAnatomy];

// Live syntax highlighting for spec Markdown, using the "anatomy of a line"
// color scheme from the guide page: [id] → accent, label → ink,
// — tail → gate, comments/provenance → faint.
//
// Two layers:
//  1. The Markdown parse tree (headings, comments, inline code, bold) via
//     a HighlightStyle — handles multi-line constructs like the header comment.
//  2. A per-line regex pass for the spec grammar itself (ids, checkboxes,
//     em-dash tails, key: value pairs, provenance markers), which plain
//     Markdown has no notion of.
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
  { tag: [t.heading1, t.heading2], class: "cm-spec-heading" },
  { tag: t.comment, class: "cm-spec-cmt" },
  { tag: t.monospace, class: "cm-spec-code" },
  { tag: t.strong, class: "cm-spec-strong" },
  { tag: t.emphasis, class: "cm-spec-em" },
  // HeaderMark / ListMark / CodeMark — the punctuation, kept quiet.
  { tag: t.processingInstruction, class: "cm-spec-punct" },
]);

const ID_MARK = Decoration.mark({ class: "cm-spec-id" });
const TAIL_MARK = Decoration.mark({ class: "cm-spec-tail" });
const KEY_MARK = Decoration.mark({ class: "cm-spec-key" });
const PROV_MARK = Decoration.mark({ class: "cm-spec-prov" });

/** `- [a2] …`, `- [x] …`, `- [ ] …` — the id/checkbox slot after a bullet. */
const ID_RE = /^\s*-\s+(\[(?:[a-z]+\d*|x| )\])/;
/** Trailing provenance marker (rendered, never hand-written). */
const PROV_RE = /\s(\[(?:human|inferred)\])\s*$/;
/** `key:` pairs inside a tail — `parallel: g1; after: a1`. */
const TAIL_KEY_RE = /(^|[—;(]\s*)([A-Za-z][\w -]*?):(?=\s|$)/g;
/** Continuation lines — `  Answer: …`, `  result: …`, `  input x: …`. */
const CONT_KEY_RE = /^\s{2,}([A-Za-z][\w ]*?:)(?=\s|$)/;
/** Plain `- key: value` bullets (Metadata) — key up to the colon. */
const META_KEY_RE = /^\s*-\s+([a-z][\w -]*:)(?=\s)/;
/** Trigger mode annotations — `(blocking)` / `(fire-and-forget)`. */
const MODE_RE = /\((blocking|fire-and-forget)\)/;

type Range = { from: number; to: number; deco: Decoration };

function collectLine(text: string, base: number, out: Range[]): void {
  const isBullet = /^\s*-\s/.test(text);

  const cont = CONT_KEY_RE.exec(text);
  if (cont) {
    const start = text.indexOf(cont[1]);
    out.push({ from: base + start, to: base + start + cont[1].length, deco: KEY_MARK });
    return;
  }
  if (!isBullet) return;

  const id = ID_RE.exec(text);
  if (id) {
    const start = text.indexOf(id[1]);
    out.push({ from: base + start, to: base + start + id[1].length, deco: ID_MARK });
  }

  const prov = PROV_RE.exec(text);
  const provStart = prov ? text.lastIndexOf(prov[1]) : -1;
  if (prov) {
    out.push({ from: base + provStart, to: base + provStart + prov[1].length, deco: PROV_MARK });
  }

  const dash = text.indexOf("—");
  const bodyEnd = provStart >= 0 ? provStart : text.length;
  if (dash >= 0 && dash < bodyEnd) {
    out.push({ from: base + dash, to: base + bodyEnd, deco: TAIL_MARK });
    const tail = text.slice(dash, bodyEnd);
    for (const m of tail.matchAll(TAIL_KEY_RE)) {
      const keyStart = dash + (m.index ?? 0) + m[1].length;
      out.push({
        from: base + keyStart,
        to: base + keyStart + m[2].length + 1,
        deco: KEY_MARK,
      });
    }
  } else if (!id) {
    const meta = META_KEY_RE.exec(text);
    if (meta) {
      const start = text.indexOf(meta[1]);
      out.push({ from: base + start, to: base + start + meta[1].length, deco: KEY_MARK });
    }
  }

  const mode = MODE_RE.exec(text);
  if (mode && (dash < 0 || (mode.index ?? 0) < dash)) {
    out.push({ from: base + mode.index, to: base + mode.index + mode[0].length, deco: TAIL_MARK });
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

const specAnatomy = ViewPlugin.fromClass(
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

export const specHighlight: Extension = [syntaxHighlighting(markdownStyle), specAnatomy];

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const TOC = [
  ["what", "What an edit request is"],
  ["skeleton", "Document skeleton"],
  ["blocks", "Change blocks"],
  ["wiring", "Triggers & dependencies"],
  ["whole", "Add / remove workflows"],
  ["style", "Writing style"],
  ["safety", "Atomicity & errors"],
  ["checklist", "Checklist"],
] as const;

export default function EditGuidePage() {
  const [active, setActive] = useState<string>("what");

  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) setActive(e.target.id);
        }
      },
      { rootMargin: "-20% 0px -70% 0px" },
    );
    for (const [id] of TOC) {
      const el = document.getElementById(id);
      if (el) obs.observe(el);
    }
    return () => obs.disconnect();
  }, []);

  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-10 px-6 py-10 lg:grid-cols-[200px_1fr]">
      {/* TOC rail */}
      <nav className="hidden lg:block">
        <div className="sticky top-8">
          <p className="eyebrow mb-3">Contents</p>
          <ol className="flex flex-col gap-1">
            {TOC.map(([id, label], i) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  className="flex items-baseline gap-2 rounded px-2 py-1 text-sm transition"
                  style={{
                    color: active === id ? "var(--accent)" : "var(--muted)",
                    background:
                      active === id ? "var(--accent-soft)" : "transparent",
                  }}
                >
                  <span className="font-mono text-[10px] text-[var(--faint)]">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  {label}
                </a>
              </li>
            ))}
          </ol>
          <div className="mt-6 flex flex-col gap-1">
            <Link
              href="/guide"
              className="text-sm text-[var(--faint)] hover:text-[var(--accent)]"
            >
              ← Spec grammar guide
            </Link>
            <Link
              href="/"
              className="text-sm text-[var(--faint)] hover:text-[var(--accent)]"
            >
              ← Back to projects
            </Link>
          </div>
        </div>
      </nav>

      <div className="guide-prose">
        {/* Hero */}
        <header className="mb-10">
          <p className="eyebrow mb-3">Edit request format</p>
          <h1 className="text-4xl font-[650] leading-[1.05] tracking-[-0.02em]">
            Writing an edit request
          </h1>
          <p className="mt-3 max-w-xl text-[var(--muted)]">
            An edit request changes workflows that were already compiled. You
            describe the changes in plain language inside a small Markdown
            skeleton; the system interprets them into exact spec operations,
            applies them atomically, and sends the project back through Validate
            and Approve.
          </p>
          <div
            className="mt-5 rounded-[var(--radius-sm)] border-l-2 p-3 text-sm"
            style={{ borderColor: "var(--gate)", background: "var(--gate-soft)" }}
          >
            <strong>Two ways to change a spec:</strong> edit the Markdown
            directly in the Spec tab (best for quick wording fixes), or submit an
            edit request (best for described changes — it is interpreted for you
            and recorded in the audit log with human authority).
          </div>
        </header>

        <Section id="what" title="What an edit request is">
          <p>Your document is processed in three steps:</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <StepCard
              tone="ghost"
              step="1 · Parse"
              body="The section skeleton is checked deterministically. Structural problems (unknown slug, unknown block) fail immediately with an actionable error — before any model call."
            />
            <StepCard
              tone="gate"
              step="2 · Interpret"
              body="The bullet entries are translated by the model into minimal patch operations against the current spec."
            />
            <StepCard
              tone="pass"
              step="3 · Apply"
              body="A deterministic applier applies everything with human authority, bumps each edited workflow's version, and records the edit in the audit log."
            />
          </div>
          <Callout tone="accent" title="Human authority">
            Your additions need no support in the original document — they are
            marked <code>[human]</code> and never auto-deleted. Your removals are
            honored.
          </Callout>
        </Section>

        <Section id="skeleton" title="Document skeleton">
          <p>
            The headings are fixed; everything inside them is plain language.{" "}
            <code>&lt;slug&gt;</code> is the workflow&rsquo;s name shown in the
            left sidebar (use the chips in the edit dialog to insert one).
          </p>
          <pre className="snippet mt-3 text-[12px]">{`# Edit Request

## Workflow: <slug>

### Add
- ...

### Modify
- ...

### Remove
- ...

### Triggers            (optional)
### Dependencies        (optional)

## Add Workflow: <new-slug>     (optional)
## Remove Workflow: <slug>      (optional)

## Reason
<why — recorded in the audit log>`}</pre>
          <ul className="mt-3 flex flex-col gap-3">
            <Rule head="One section per workflow">
              A workflow may appear in only one <code>## Workflow:</code>{" "}
              section, and may not be both edited and removed in the same
              request.
            </Rule>
            <Rule head="Reserved">
              <code>## Split Workflow:</code> and{" "}
              <code>## Merge Workflows:</code> are recognized but rejected —
              reserved for a future release. Model a split/merge as Add + Remove
              plus explicit rewiring.
            </Rule>
          </ul>
        </Section>

        <Section id="blocks" title="Change blocks">
          <p>
            One change per bullet, naming the element kind (activity, rule,
            timer, retry, exception, compensation, event, input, output, actor,
            system).
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <KindCard
              tone="pass"
              label="### Add"
              items="New elements, written verbatim"
              note='"A business rule: refunds over $500 require manager approval."'
            />
            <KindCard
              tone="gate"
              label="### Modify"
              items="Identify exactly, then state the change"
              note={'"‘Deprovision service’ retry count changes from 3 to 5." Cite the [id] when you know it.'}
            />
            <KindCard
              tone="block"
              label="### Remove"
              items="State what goes away"
              note="Dangling references to a removed element are pruned automatically and reported as warnings."
            />
          </div>
        </Section>

        <Section id="wiring" title="Triggers & dependencies">
          <p>
            Cross-workflow wiring. Name both workflows by slug; for triggers
            state the mode (blocking / fire-and-forget) and condition when
            relevant. Wiring added by an edit request is marked user-confirmed —
            no checkbox round-trip needed.
          </p>
          <pre className="snippet mt-3 text-[12px]">{`### Triggers
- When the record is created, this workflow starts
  account-provisioning (fire-and-forget).
- Remove the trigger to legacy-billing.

### Dependencies
- account-provisioning also consumes this workflow's
  plan_code output as its plan_code input.`}</pre>
          <p className="mt-3">
            Project-wide wiring that belongs to no single workflow can live in a{" "}
            <code>## Project</code> section — wiring changes only; content edits
            must stay under a <code>## Workflow:</code> section.
          </p>
        </Section>

        <Section id="whole" title="Add / remove whole workflows">
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <KindCard
              tone="pass"
              label="## Add Workflow: <slug>"
              items="Body = a complete workflow description"
              note="Written like a source document (its own ## Purpose, ## Process, …). It runs through the same discovery + fact-extraction pipeline as an original document."
            />
            <KindCard
              tone="block"
              label="## Remove Workflow: <slug>"
              items="No body needed"
              note="The workflow's spec and segment are deleted, and every trigger or dependency touching it is dropped (each drop is listed in the edit summary)."
            />
          </div>
        </Section>

        <Section id="style" title="Writing style">
          <p>
            The interpreter maps your prose onto exact spec elements, so
            precision pays.
          </p>
          <div className="mt-4 flex flex-col gap-2">
            <DoDont
              good={'"‘Deprovision service’ retry count changes from 3 to 5"'}
              bad={'"retry more"'}
            />
            <DoDont
              good={'"Remove the manager-approval rule for orders above $1,000"'}
              bad={'"drop that approval thing"'}
            />
            <DoDont
              good="One change per bullet"
              bad="Bundling several changes in one bullet"
            />
            <DoDont
              good="Copy labels exactly as the spec shows them"
              bad="Paraphrasing from memory"
            />
            <DoDont
              good={'Describe the change ("X changes from A to B")'}
              bad="Describing only the desired end state"
            />
          </div>
        </Section>

        <Section id="safety" title="Atomicity & errors">
          <div className="mt-2 flex flex-col gap-2">
            <FindingChip
              tone="block"
              tag="ATOMIC"
              text="Nothing is applied unless everything applies. An entry the model cannot map — or an operation naming an unknown element — aborts the whole edit and reports the offending entries verbatim. Rephrase and re-submit."
            />
            <FindingChip
              tone="gate"
              tag="SKIP"
              text="An add whose value is already in the spec is treated as satisfied: it is skipped with a 'skipped (already present)' line instead of aborting."
            />
            <FindingChip
              tone="muted"
              tag="AUDIT"
              text="Every applied edit appends to the project's edit log (see Edit history in the sidebar) and bumps each edited workflow's version (0.1.0 → 0.1.1)."
            />
          </div>
          <p className="mt-4">
            After an edit applies, the project returns to the spec gate:{" "}
            <strong>Validate</strong>, review the findings and the diff, then{" "}
            <strong>Approve</strong> to regenerate code.
          </p>
        </Section>

        <Section id="checklist" title="Checklist">
          <ul className="mt-2 flex flex-col gap-1.5 text-[14px] text-[var(--muted)]">
            {[
              "H1 is exactly '# Edit Request'",
              "Every '## Workflow:' slug matches a workflow in the sidebar",
              "One change per bullet, each naming its element kind",
              "Modify/Remove entries quote the element as the spec renders it",
              "New workflows have a full document-format body",
              "No workflow is both edited and removed",
              "'## Reason' says why (it goes in the audit log)",
              "After applying: review the diff, then Validate → Approve",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-0.5 text-[var(--pass)]">✓</span>
                {item}
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </div>
  );
}

/* ---------------- pieces (mirrors /guide) ---------------- */

const TONE_BG: Record<string, string> = {
  ghost: "var(--surface)",
  gate: "var(--gate-soft)",
  pass: "var(--pass-soft)",
  accent: "var(--accent-soft)",
  block: "var(--block-soft)",
  muted: "var(--surface-2)",
};
const TONE_FG: Record<string, string> = {
  gate: "var(--gate)",
  pass: "var(--pass)",
  accent: "var(--accent)",
  block: "var(--block)",
  muted: "var(--muted)",
  ghost: "var(--muted)",
};

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="mb-14 scroll-mt-20">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function StepCard({
  step,
  body,
  tone,
}: {
  step: string;
  body: string;
  tone: string;
}) {
  return (
    <div
      className="rounded-[var(--radius-sm)] border p-3"
      style={{ borderColor: "var(--border)", background: TONE_BG[tone] }}
    >
      <p
        className="font-mono text-xs font-semibold uppercase tracking-wider"
        style={{ color: TONE_FG[tone] }}
      >
        {step}
      </p>
      <p className="mt-1.5 text-[13px] leading-snug text-[var(--muted)]">{body}</p>
    </div>
  );
}

function KindCard({
  label,
  items,
  note,
  tone,
}: {
  label: string;
  items: string;
  note: string;
  tone: string;
}) {
  return (
    <div className="card p-4">
      <p
        className="font-mono text-[11px] font-semibold uppercase tracking-wider"
        style={{ color: TONE_FG[tone] }}
      >
        {label}
      </p>
      <p className="mt-2 text-sm text-[var(--ink)]">{items}</p>
      <p className="mt-2 text-[13px] text-[var(--muted)]">{note}</p>
    </div>
  );
}

function Callout({
  tone,
  title,
  children,
}: {
  tone: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="mt-4 rounded-[var(--radius-sm)] border-l-2 p-3.5 text-sm text-[var(--muted)]"
      style={{ borderColor: TONE_FG[tone], background: TONE_BG[tone] }}
    >
      <p className="mb-1 font-semibold text-[var(--ink)]">{title}</p>
      {children}
    </div>
  );
}

function Rule({ head, children }: { head: string; children: React.ReactNode }) {
  return (
    <li className="card flex flex-col gap-1 p-3 sm:flex-row sm:gap-4">
      <span className="font-mono text-xs font-semibold text-[var(--accent)] sm:w-32 sm:shrink-0">
        {head}
      </span>
      <span className="text-[13px] leading-relaxed text-[var(--muted)]">
        {children}
      </span>
    </li>
  );
}

function DoDont({ good, bad }: { good: string; bad: string }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <div
        className="rounded-[var(--radius-sm)] border p-2.5 text-[13px]"
        style={{ borderColor: "var(--border)", background: "var(--pass-soft)" }}
      >
        <span className="mr-2 font-mono text-[10px] font-bold text-[var(--pass)]">
          DO
        </span>
        <span className="text-[var(--muted)]">{good}</span>
      </div>
      <div
        className="rounded-[var(--radius-sm)] border p-2.5 text-[13px]"
        style={{ borderColor: "var(--border)", background: "var(--block-soft)" }}
      >
        <span className="mr-2 font-mono text-[10px] font-bold text-[var(--block)]">
          AVOID
        </span>
        <span className="text-[var(--muted)]">{bad}</span>
      </div>
    </div>
  );
}

function FindingChip({
  tone,
  tag,
  text,
}: {
  tone: string;
  tag: string;
  text: string;
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-[var(--radius-sm)] border p-2.5"
      style={{ borderColor: "var(--border)", background: TONE_BG[tone] }}
    >
      <span
        className="mt-0.5 rounded px-1.5 py-0.5 font-mono text-[10px] font-bold"
        style={{ color: TONE_FG[tone], border: `1px solid ${TONE_FG[tone]}` }}
      >
        {tag}
      </span>
      <span className="text-[13px] text-[var(--muted)]">{text}</span>
    </div>
  );
}

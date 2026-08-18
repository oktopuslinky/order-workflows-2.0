"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const TOC = [
  ["loop", "The loop"],
  ["anatomy", "Anatomy of a line"],
  ["kinds", "Two kinds of section"],
  ["grammar", "Grammar rules"],
  ["reference", "Section reference"],
  ["findings", "Findings"],
  ["changes", "changes.md"],
] as const;

export default function GuidePage() {
  const [active, setActive] = useState<string>("loop");

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
              href="/guide/edits"
              className="text-sm text-[var(--faint)] hover:text-[var(--accent)]"
            >
              Edit request format →
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
          <p className="eyebrow mb-3">Spec grammar</p>
          <h1 className="text-4xl font-[650] leading-[1.05] tracking-[-0.02em]">
            Filling out a spec
          </h1>
          <p className="mt-3 max-w-xl text-[var(--muted)]">
            A spec is the human gate between your document and runnable Temporal
            code. You edit it until it&rsquo;s right, then approve it. Here is what
            every part means and the small grammar that keeps your edits intact.
          </p>
          <div
            className="mt-5 rounded-[var(--radius-sm)] border-l-2 p-3 text-sm"
            style={{
              borderColor: "var(--gate)",
              background: "var(--gate-soft)",
            }}
          >
            <strong>The one rule:</strong> after any edit, run{" "}
            <strong>Validate</strong> before <strong>Approve</strong>. Approve
            checks the last validate, so the button stays disabled until you do.
          </div>
        </header>

        {/* Loop */}
        <Section id="loop" title="The loop">
          <p>
            Three actions move a spec forward. Save is instant; Validate and
            Approve call the model.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <StepCard
              tone="ghost"
              step="Save"
              body="Writes your Markdown back onto the spec. Deterministic, no model. A checkpoint — it does not clear the need to validate."
            />
            <StepCard
              tone="gate"
              step="Validate"
              body="Folds edits in, runs review passes + integrity checks, and returns findings. The editor reloads with the re-rendered spec."
            />
            <StepCard
              tone="pass"
              step="Approve"
              body="Compiles every workflow to code. Blocked while a BLOCK finding or unconfirmed dependency remains, unless you override."
            />
          </div>
        </Section>

        {/* Anatomy — the signature */}
        <Section id="anatomy" title="Anatomy of a line">
          <p>
            Structural entries are code-like. Keep the three parts intact and your
            edits round-trip perfectly.
          </p>
          <LineAnatomy />
        </Section>

        {/* Two kinds */}
        <Section id="kinds" title="Two kinds of section">
          <p>
            Every section is either <strong>structural</strong> (becomes code) or{" "}
            <strong>descriptive</strong> (documentation the code never reads).
            Knowing which is which is the whole game.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <KindCard
              tone="accent"
              label="Structural — executable"
              items="Activities · Decisions · Exceptions · Compensations · Events · Triggers"
              note="Carry [id] markers. Their order is the runtime order."
            />
            <KindCard
              tone="muted"
              label="Descriptive — reference"
              items="Purpose · Metadata · Inputs · Outputs · Business Rules · API Interfaces · Systems · Timers · Retries"
              note="Context only. Never wired to a call site."
            />
          </div>
          <Callout tone="gate" title="Where do API calls happen?">
            Inside <strong>Activities</strong> — not in the &ldquo;API
            Interfaces&rdquo; list. API Interfaces documents <em>which</em> systems
            the workflow touches; an Activity is <em>where and when</em> a call
            runs (its generated stub is where the real call goes). If an API must
            fire at a point in the flow, model it as an activity like{" "}
            <code>- Charge card via Payments API — after: a2</code>, not only as an
            API-Interfaces line.
          </Callout>
        </Section>

        {/* Grammar */}
        <Section id="grammar" title="Grammar rules">
          <ul className="mt-3 flex flex-col gap-3">
            <Rule head="[id] markers">
              <code>- [a3] Ship order</code>. The id ties your edit to an existing
              element. A line <strong>without</strong> an id becomes a new,
              human-provided element. Never renumber ids by hand.
            </Rule>
            <Rule head="Tail syntax">
              <code>— key: value; key: value</code> after the label (an em-dash).
              Each section allows specific keys — see the reference below.
            </Rule>
            <Rule head="Provenance">
              A trailing <code>[human]</code> or <code>[inferred]</code>; none means
              document-grounded. You don&rsquo;t write these. Lines you add become{" "}
              <code>[human]</code> and are <strong>never auto-deleted</strong>.
            </Rule>
            <Rule head="Delete = remove">
              Delete a line to drop the element. Empty sections render{" "}
              <code>&lt;!-- none --&gt;</code>.
            </Rule>
          </ul>
        </Section>

        {/* Section reference */}
        <Section id="reference" title="Section reference">
          <p>Grouped by role. Structural sections show their tail keys.</p>
          {GROUPS.map((g) => (
            <div key={g.title} className="mt-6">
              <p className="eyebrow mb-3">{g.title}</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {g.sections.map((s) => (
                  <SectionRef key={s.name} {...s} />
                ))}
              </div>
            </div>
          ))}
        </Section>

        {/* Findings */}
        <Section id="findings" title="Findings">
          <p>Validate returns findings in three tiers.</p>
          <div className="mt-4 flex flex-col gap-2">
            <FindingChip
              tone="block"
              tag="BLOCK"
              text="Structural breakage — a trigger to an unknown workflow, an input naming a field the target doesn't declare, an unmet required question. Blocks Approve."
            />
            <FindingChip
              tone="gate"
              tag="WARN"
              text="Should be confirmed but doesn't block — a type mismatch on a hand-off, an unconfirmed trigger predicate, a blocking trigger with no result."
            />
            <FindingChip
              tone="muted"
              tag="INFO"
              text="Informational — e.g. an edit that was folded in."
            />
          </div>
          <p className="mt-5">
            When BLOCK is 0 (or overrides are ticked),{" "}
            <strong>Approve</strong> opens the Results tab: per-workflow diagram,
            CVPA table, generated files, and Download&nbsp;.zip.
          </p>
        </Section>

        {/* changes.md */}
        <Section id="changes" title="changes.md — the change spec">
          <p>
            A project compiled <strong>with a knowledge base</strong> (home page →{" "}
            <em>Ground with knowledge base</em>, or a change request&apos;s{" "}
            <em>Send to workflow GUI</em>) gets a second kind of file next to the
            workflow specs: <code>changes.md</code>, one block per component of the
            existing code base that the design changes, each with what exists today
            and what is proposed. It goes through the same Save ⇄ Validate ⇄ Resolve
            ⇄ Approve gate.
          </p>
          <pre className="snippet mt-4">
            <code>{`### provision_order — activity, modify [inferred]
- path: \`fn:existing_Codebase/activities/order_activities.py:provision_order\`
- requirements: BCR-01-02, BCR-01-03

#### Existing
Provisions the whole order and returns one ProvisioningResult.

#### Proposed
Takes a shipment group and returns one result per group; …`}</code>
          </pre>
          <ul className="mt-4 list-disc space-y-1.5 pl-5">
            <li>
              Heading: <code>### name — kind, change_type</code> — kind is{" "}
              <code>module | activity | workflow | type | signal | query | test | diagram | doc</code>,
              change_type is <code>modify | add | remove | verify</code>. Keep the heading of an
              existing entry so your edit lands on the right component; a new heading is recorded
              as human-provided; a deleted heading removes the component.
            </li>
            <li>
              <code>- path:</code> a knowledge-graph node id or corpus path (empty for something
              new); <code>- requirements:</code> the change request&apos;s requirement ids.
            </li>
            <li>
              <code>#### Existing</code> / <code>#### Proposed</code> are free text.{" "}
              <strong>An empty Proposed is a BLOCK.</strong> A path the knowledge base does not
              know, or a requirement id the change request does not declare, is a WARN with
              suggestions.
            </li>
            <li>
              <em>Grounding</em> and <em>Sources</em> are read-only; Assumptions and Open
              Questions work exactly like a workflow spec&apos;s.
            </li>
          </ul>
        </Section>
      </div>
    </div>
  );
}

/* ---------------- pieces ---------------- */

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

function LineAnatomy() {
  return (
    <div className="reveal mt-5 card p-6">
      <div className="snippet !border-0 !bg-transparent !p-0 text-[15px] sm:text-lg">
        <span>- </span>
        <span className="id">[a2]</span>
        <span> Reserve inventory </span>
        <span className="tail">— parallel: g1</span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3 text-center text-[11px]">
        <Annot color="var(--accent)" label="id" note="ties the edit to this element" />
        <Annot color="var(--ink)" label="label" note="the imperative action" />
        <Annot color="var(--gate)" label="tail" note="key: value settings" />
      </div>
    </div>
  );
}

function Annot({
  color,
  label,
  note,
}: {
  color: string;
  label: string;
  note: string;
}) {
  return (
    <div>
      <div
        className="mx-auto mb-1.5 h-px w-full"
        style={{ background: color, opacity: 0.5 }}
      />
      <p className="font-mono font-semibold" style={{ color }}>
        {label}
      </p>
      <p className="mt-0.5 text-[var(--faint)]">{note}</p>
    </div>
  );
}

function SectionRef({
  name,
  meaning,
  keys,
  example,
}: {
  name: string;
  meaning: string;
  keys?: string[];
  example?: string;
}) {
  return (
    <div className="card p-3.5">
      <p className="font-mono text-[13px] font-semibold text-[var(--ink)]">
        {name}
      </p>
      <p className="mt-1 text-[13px] leading-snug text-[var(--muted)]">{meaning}</p>
      {keys && keys.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {keys.map((k) => (
            <span
              key={k}
              className="rounded px-1.5 py-0.5 font-mono text-[10px]"
              style={{ background: "var(--gate-soft)", color: "var(--gate)" }}
            >
              {k}
            </span>
          ))}
        </div>
      )}
      {example && (
        <pre className="snippet mt-2 !py-1.5 text-[11px]">{example}</pre>
      )}
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

/* ---------------- section reference data ---------------- */

const GROUPS: {
  title: string;
  sections: { name: string; meaning: string; keys?: string[]; example?: string }[];
}[] = [
  {
    title: "Structural — becomes code",
    sections: [
      {
        name: "Activities",
        meaning: "Units of work — and where API/system calls live.",
        keys: ["parallel"],
        example: "- [a2] Reserve inventory — parallel: g1",
      },
      {
        name: "Decisions",
        meaning:
          "Branch points. Always give the no: branch — a rejecting no: is what raises and fails the run.",
        keys: ["after", "yes", "no"],
        example: "- [d1] Order eligible? — after: a1; yes: a2; no: e1",
      },
      {
        name: "Exceptions",
        meaning: "Error conditions, attributed to the activity that raises them.",
        keys: ["raised by"],
        example: "- [e1] Order ineligible — raised by: a1",
      },
      {
        name: "Compensations",
        meaning: "Saga rollbacks that reverse an activity on failure.",
        keys: ["compensates"],
        example: "- [c1] Release inventory — compensates: a2",
      },
      {
        name: "Events",
        meaning:
          "kind is critical: signal_wait makes a wait a bounded condition, not a hang.",
        keys: ["kind", "emitted by"],
        example: "- [v2] PaymentConfirmed — kind: signal_wait",
      },
      {
        name: "Triggers",
        meaning:
          "One workflow starting another. Review the when predicate and tick to confirm; delete ones that shouldn't fire.",
        example: "- [x] triggers `provisioning` (blocking) when `approved`",
      },
    ],
  },
  {
    title: "Cross-workflow & review",
    sections: [
      {
        name: "Open Questions",
        meaning:
          "Answer and tick. Unanswered required questions block Approve unless overridden.",
      },
      {
        name: "Cross-Workflow Dependencies",
        meaning:
          "Output→input links between workflows. Tick to confirm; unconfirmed links block Approve.",
      },
      {
        name: "Assumptions / Ambiguities / Suggested Edits",
        meaning:
          "Review notes flagging where extraction guessed. Read, edit, or delete freely.",
      },
    ],
  },
  {
    title: "Descriptive — documentation only",
    sections: [
      { name: "Purpose", meaning: "One line: what the workflow is for." },
      {
        name: "Metadata",
        meaning:
          "domain / owner / version / actors / systems / tags. Often blank from docs — fill in what you need.",
      },
      { name: "Inputs / Outputs", meaning: "What the workflow receives and produces." },
      {
        name: "API Interfaces / Systems Involved",
        meaning: "Which external systems are touched. Not call sites — see the callout above.",
      },
      {
        name: "Business Rules / Timers & SLAs / Retries",
        meaning: "Reference facts. Timers and retries are applied to activities during design.",
      },
      { name: "State Transitions", meaning: "Narrative state changes. Advisory, not control flow." },
    ],
  },
];

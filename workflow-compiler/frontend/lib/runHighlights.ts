// Map a run's event trail onto the workflow diagram's nodes.
//
// The mermaid source and the Temporal design name the same steps differently:
// the diagram says `activity_3["Authorise payment"]` while the run's events say
// `AuthorizePayment` — there is no stored link between the two. The bridge is
// token matching: split the PascalCase activity name and the node label into
// words, normalise British/American spelling, and score the overlap. That keeps
// this feature purely client-side — no backend or schema change — at the cost
// of a heuristic, which is why an unmatched activity simply highlights nothing
// rather than guessing.

import type { RunEvent, RunState } from "@/lib/types";

export type NodeRunStatus = "done" | "active" | "waiting" | "failed";

export interface DiagramNode {
  id: string;
  label: string;
}

/** Words too generic to carry a match on their own. */
const STOPWORDS = new Set(["the", "a", "an", "of", "to", "for", "and", "is"]);

/** British→American so "Authorise payment" matches `AuthorizePayment`. */
function normalizeToken(token: string): string {
  return token
    .toLowerCase()
    .replace(/isation$/, "ization")
    .replace(/ise$/, "ize")
    .replace(/ised$/, "ized")
    .replace(/fulfilment$/, "fulfillment")
    .replace(/fulfil$/, "fulfill");
}

/** Split PascalCase, snake_case, dotted, or prose text into normalised tokens. */
export function tokenize(text: string): string[] {
  return text
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[^A-Za-z0-9]+/)
    .map(normalizeToken)
    .filter((t) => t.length > 0 && !STOPWORDS.has(t));
}

/**
 * The diagram's nodes, straight out of the mermaid source.
 *
 * The renderer emits one declaration per line — `id["Label"]`, `id{"Label"}`,
 * or `id(["Label"])` — before any edges, so a line-wise regex is reliable and
 * avoids needing the graph model on the client at all.
 */
export function parseMermaidNodes(source: string): DiagramNode[] {
  const nodes: DiagramNode[] = [];
  for (const line of source.split("\n")) {
    const m = line.trim().match(/^([A-Za-z0-9_]+)[[({]+"([^"]+)"[\])}]+$/);
    if (m) nodes.push({ id: m[1], label: m[2] });
  }
  return nodes;
}

/** Best diagram node for one event detail, or null when nothing is close. */
function matchNode(
  detail: string,
  nodes: DiagramNode[],
  idPrefixes: string[],
): string | null {
  const wanted = tokenize(detail);
  if (wanted.length === 0) return null;
  let best: { id: string; score: number; extra: number } | null = null;
  for (const node of nodes) {
    if (!idPrefixes.some((p) => node.id.startsWith(p))) continue;
    const labelTokens = new Set(tokenize(node.label));
    const hit = wanted.filter((t) => labelTokens.has(t)).length;
    const score = hit / wanted.length;
    const extra = labelTokens.size - hit;
    if (score < 0.5) continue;
    if (!best || score > best.score || (score === best.score && extra < best.extra)) {
      best = { id: node.id, score, extra };
    }
  }
  return best?.id ?? null;
}

/**
 * Fold the event trail into a status per diagram node id.
 *
 * Precedence is last-write-wins in event order, which is exactly the story the
 * trail tells: scheduled → active, completed → done, failed → failed. While the
 * run is parked on a timer (`timer_started` with nothing after it), the event
 * nodes matching a declared signal pulse as "waiting" — that is the
 * signal-and-timer wait the generated workflows use for human/external steps.
 */
export function buildNodeStatus(
  source: string,
  events: RunEvent[],
  runState: RunState,
  signalNames: string[] = [],
): Record<string, NodeRunStatus> {
  const nodes = parseMermaidNodes(source);
  const status: Record<string, NodeRunStatus> = {};
  // Activities may also appear as trigger/compensation nodes; event nodes cover
  // signals. Decisions/exceptions are not in the trail, so they never match.
  const activityPrefixes = ["activity_", "trigger_", "compensation_"];

  for (const event of events) {
    switch (event.kind) {
      case "started":
        status["start"] = "done";
        break;
      case "activity_scheduled": {
        const id = matchNode(event.detail, nodes, activityPrefixes);
        if (id && status[id] !== "failed") status[id] = "active";
        break;
      }
      case "activity_completed": {
        const id = matchNode(event.detail, nodes, activityPrefixes);
        if (id) status[id] = "done";
        break;
      }
      case "activity_failed": {
        const id = matchNode(event.detail, nodes, activityPrefixes);
        if (id) status[id] = "failed";
        break;
      }
      case "signal_received": {
        const id = matchNode(event.detail, nodes, ["event_"]);
        if (id) status[id] = "done";
        break;
      }
      case "completed":
        status["end_node"] = "done";
        break;
      default:
        break;
    }
  }

  const last = events[events.length - 1];
  if (runState === "running" && last?.kind === "timer_started") {
    for (const name of signalNames) {
      const id = matchNode(name, nodes, ["event_"]);
      if (id && !status[id]) status[id] = "waiting";
    }
  }

  return status;
}

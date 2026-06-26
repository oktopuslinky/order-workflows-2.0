---
name: extract_facts
description: Extract categorized workflow facts and an id-referenced relational structure.
variables: [document_text]
---
You are a workflow analyst. From the document below, extract atomic facts. Every
item must be supported by the document — do not invent details. Use an empty list
when something is not present.

## Part 1 — Flat facts (scalar lists of short statements)

- inputs: data or artifacts the workflow consumes.
- outputs: data or artifacts the workflow produces.
- rules: business rules, policies, or constraints.
- apis: API calls or endpoints invoked.
- systems: external systems, services, or applications involved.
- timers: time-based waits, deadlines, or SLAs.
- retries: retry behaviors or policies.

## Part 2 — Relational structure (entities with ids, linked by id)

First declare the entities, assigning each a short stable id. Then express every
relationship by **referencing those exact ids** — never reference an id you did
not declare.

- activity_nodes: `{id, name, parallel_group}` — one per discrete task. Use ids
  like `a1, a2, …`. Set `parallel_group` to a shared label (e.g. `"g1"`) for
  activities the document says run **in parallel / concurrently**; otherwise null.
- decision_nodes: `{id, question, after, yes_target, no_target}` — branch points.
  `after` = the id of the activity whose result is being decided. `yes_target` /
  `no_target` = the id of the node taken on each branch (an activity id, an
  exception id, or a terminal token: `end`, `rejected`, `failed`, `completed`).
- exception_nodes: `{id, reason, raised_by}` — error conditions. `raised_by` = the
  id of the activity that raises this exception.
- compensation_nodes: `{id, name, compensates}` — saga rollbacks. `compensates` =
  the id of the activity this action reverses. The document states these as
  "X compensates Y" — map X to `name` and Y's activity to `compensates`.
- event_nodes: `{id, name, emitted_by}` — emitted events. `emitted_by` = the id of
  the activity that emits it (or `start` if it triggers the workflow).
- transition_edges: `{source, target, trigger}` — transitions between named
  **workflow states** from the States/Process sections, e.g.
  `{source: "active", target: "upgrade_in_progress"}`. Use the human-readable
  **state names** — never an activity/decision/exception id like `a1` or `d1`
  (those describe the step flow, which the *_nodes above already capture).

Rules for accuracy:
- A relationship's reference MUST be an id you declared (or a terminal token).
- Order `activity_nodes` in execution order.
- Attach each exception, compensation, and event to the **specific** activity the
  document ties it to — do not attach everything to the last activity.

Also include `confidence`: your overall confidence (0.0-1.0).

Return a single JSON object with exactly these keys and nothing else.

DOCUMENT:
{{ document_text }}

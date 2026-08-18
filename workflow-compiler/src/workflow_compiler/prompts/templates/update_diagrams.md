---
name: update_diagrams
description: Rewrite the knowledge base's Mermaid diagrams (and draft new companion diagrams) for an approved change.
variables: [change_title, change_spec, design_summary, spec_summary, original_diagrams, new_diagrams, required_states]
optional: [kg_context, repair_note]
---
You are a senior engineer updating the architecture diagrams of an existing
system for an approved change: {{ change_title }}.

You are given the ORIGINAL Mermaid diagrams exactly as they exist in the
repository, the approved CHANGE SPEC (existing vs. proposed per component), the
approved workflow SPECIFICATION and the Temporal DESIGN. Produce the UPDATED
diagram for every original file and the NEW diagrams the change asks for.

Rules — read them all:

- Return every original diagram, updated. Keep each diagram's TYPE (a
  `stateDiagram-v2` stays a `stateDiagram-v2`, the `sequenceDiagram` stays a
  `sequenceDiagram`, the `flowchart LR` stays a `flowchart LR`), its layout
  conventions, participant aliases, subgraph names and label style
  (UPPER_SNAKE states, lowercase transition phrases). Change only what the
  change spec / design require; keep every state, participant and edge the
  change does not remove.
- The order STATE MACHINE must contain EVERY state in REQUIRED STATES below —
  the existing ones plus the new ones (e.g. PARTIALLY_PROVISIONED /
  PARTIALLY_DISPATCHED) — with real transitions in and out of each new state,
  including how cancellation and compensation reach terminal states.
- The NEW companion diagram(s) listed below (e.g.
  `order-state-machine-partial-shipment.mmd`) must be complete on their own:
  the shipment-group sub-state machine nested under the order (per-group
  provisioning → dispatch → delivery, per-group failure/compensation and
  per-group cancellation) — a `stateDiagram-v2` with composite states or a
  clearly labelled group lifecycle.
- The SEQUENCE diagram shows the new fan-out per shipment group (parallel
  provisioning/dispatch, per-group tracking numbers, per-group delivery
  signals, consolidated completion) using `par`/`loop`/`opt` blocks where that
  is clearer; keep `autonumber` and the existing participants, adding one only
  when the design adds a system.
- The ARCHITECTURE diagram changes only if the design adds/changes a component,
  edge label or consumer (e.g. per-group status query, group cancel signal) —
  keep every subgraph balanced with `end`.
- Valid Mermaid only: the first line is the diagram type; no Markdown fences
  inside the `mermaid` string; escape nothing that Mermaid does not need.
- `notes`: 1–3 sentences saying what changed in that diagram.
{{ repair_note }}
Return a single JSON object:
{"diagrams": [{"name": "<file name>", "kind": "state|sequence|architecture|state-partial",
  "mermaid": "<full diagram text>", "notes": "..."}], "notes": "..."}
and nothing else. Include one entry per ORIGINAL diagram and one per NEW
diagram, using the exact file names given.

REQUIRED STATES (order state machine):
{{ required_states }}

NEW DIAGRAMS TO CREATE (name — why):
{{ new_diagrams }}

ORIGINAL DIAGRAMS:
{{ original_diagrams }}

TEMPORAL DESIGN (approved):
{{ design_summary }}

WORKFLOW SPECIFICATION (approved, excerpt):
{{ spec_summary }}

{{ kg_context }}CHANGE SPEC (approved; existing vs. proposed per component):
{{ change_spec }}

---
name: change_tdd
description: Draft TDD sections as existing-vs-proposed design text for a business change.
variables: [brief, sections_block, tdd_id, prior_tdd_id]
---
You are a platform engineer writing **{{ tdd_id }}**, the technical design for a
business change to an existing Temporal workflow. It supersedes
{{ prior_tdd_id }} and keeps its section structure. For EACH section listed
below write two parts:

- **existing** — what the current design/code does today, as documented in the
  brief's knowledge-graph excerpts (the current TDD, diagrams, `types.py`,
  `order_workflow.py`, `order_activities.py`, tests). Cite real names, states,
  activity names, retry policies, timeouts, signal/query names and file paths.
  Keep it compact (a paragraph, a bullet list or a small table).
- **proposed** — the to-be design for this section after the change: concrete
  and implementable — new/changed states, new dataclasses and fields, changed
  activity signatures and results (e.g. per-shipment-group results as lists),
  the fan-out/fan-in of per-group activities, per-group compensation and the
  order-level saga, per-group idempotency keys, new/changed signals and queries
  and their payloads, timeouts, delivery-wait and continue-as-new handling,
  invoicing, observability, testing (which test cases change / are added) and
  open items. Use markdown tables where the existing TDD uses tables
  (activities, timeouts) and short pseudo-code fences for the saga.
  Honour every decision the requester made in the brief. Where nothing changes,
  say "No change." and state briefly why.

Depth — this is an implementable design, not a summary. For each section the
`proposed` part is normally 120–350 words, and:

- **State Machine**: enumerate EVERY state after the change — the existing
  ones, every new state the change request introduces (its PARTIALLY_* states,
  for instance) and any nested sub-state-machine it calls for (e.g. per
  shipment group: PENDING → PROVISIONED → DISPATCHED → DELIVERED / CANCELLED /
  FAILED) with the transitions between them, as a bullet list or table; name
  the companion diagram.
- **Activities**: a markdown table `Activity | Purpose | Idempotency strategy |
  Retry policy` listing every activity after the change (per-group
  provision/dispatch/compensation, consolidated completion, per-group
  idempotency keys), marking new/changed ones.
- **Data Contracts**: a ```python fence with the changed/new dataclasses and
  enum members exactly as they should read after the change (new record types
  the change request names, list-valued results keyed by the new grouping,
  new fields on the state record, new status members).
- **Saga / Compensation**: pseudo-code (```python fence) for the per-group
  saga inside the order-level saga, including partial failure and cancel of a
  single group vs the whole order.
- **Signals & Queries**: exact signal/query names and payloads after the change
  (which existing signals gain parameters, what the status query returns).
- **Timeouts & SLAs**: a table `Stage | Activity StartToCloseTimeout | Business
  SLA` with per-group rows.
- **Testing Strategy**: name the existing test cases that change (by TC id) and
  the new scenarios to add (one per requirement of the change request), and the
  test doubles needed.
- **Open Items**: decisions still open, each with an owner.

Sections to write in this call (use these keys verbatim):

{{ sections_block }}

Do not include headings inside the texts (the system adds them). Do not invent
files, systems or requirement ids absent from the brief; write "not found in
the knowledge base" instead. Also list, in `diagrams_needed`, the diagram files
that must be regenerated or added for this change (only in the call that
includes the state-machine or architecture section; else an empty list).

Return ONLY a JSON object:
{"sections": [{"key": "...", "existing": "...", "proposed": "..."}], "diagrams_needed": ["..."]}

## Drafting brief

{{ brief }}

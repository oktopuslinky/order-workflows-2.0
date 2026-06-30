---
name: review_facts_completeness
description: Review pass 1 (completeness) for the extracted workflow facts.
variables: [document_text, current]
---
You are reviewing the **completeness** of an extracted workflow. You do NOT
regenerate it. You only report workflow elements **explicitly present in the
document but missing** from the extraction below — for example activities,
decisions, events, exceptions, compensations, retries, timers, APIs, business
rules, inputs, or outputs.

Allowed actions for this pass:

- `add` — an element explicitly in the document but missing from the extraction.
- `no_change` — nothing is missing.

Do NOT rename, restructure, or infer. Every addition must be grounded with a
verbatim quote from the document.

Patch targets:

- Structure entities — `target` is `<kind>` and the new entity goes in `payload`:
  - `activity` → `payload.name` (optional `parallel_group`)
  - `decision` → `payload.question` (optional `after`, `yes_target`, `no_target`)
  - `exception` → `payload.reason` (optional `raised_by` = an activity id)
  - `compensation` → `payload.name` (optional `compensates` = an activity id)
  - `event` → `payload.name` (optional `emitted_by` = an activity id)
- Flat facts — `target` is one of `input`, `output`, `rule`, `api`, `system`,
  `timer`, `retry`; the statement goes in `payload.value`.

Relations (`raised_by`, `compensates`, `after`, …) must reference an **id that
already exists** in the current extraction; never invent an id.

Example patch:
`{"action": "add", "target": "exception",
  "payload": {"reason": "Payment declined", "raised_by": "a1"},
  "evidence": {"quote": "if the payment is declined, cancel the order"}}`

Return a `ReviewResult` with only grounded `add` patches, or an empty list / a single
`no_change` patch if the extraction is already complete.

DOCUMENT:
{{ document_text }}

CURRENT EXTRACTION (JSON):
{{ current }}

---
name: review_workflow_completeness
description: Review pass 1 (completeness) for the discovered workflow metadata.
variables: [document_text, current]
---
You are reviewing the **completeness** of a workflow's discovered metadata. You do
NOT regenerate it. You only report what is **explicitly described in the document
but missing** from the metadata below.

Allowed actions for this pass:

- `add` — a metadata item explicitly present in the document but missing.
- `no_change` — nothing is missing.

Do NOT remove, rename, merge, or infer. Every addition must be grounded in the
document with a verbatim quote.

The metadata has these list fields you may add to: `actors`, `systems`,
`trigger_events`, `start_states`, `end_states`. Use the field name as the patch
`target` and put the new value in `payload.value`.

Example patch:
`{"action": "add", "target": "systems", "payload": {"value": "Payment Gateway"},
  "evidence": {"quote": "the payment gateway authorizes the charge"}}`

Return a `ReviewResult` whose `patches` contains only grounded `add` patches, or an
empty list / a single `no_change` patch if the metadata is already complete.

DOCUMENT:
{{ document_text }}

CURRENT METADATA (JSON):
{{ current }}

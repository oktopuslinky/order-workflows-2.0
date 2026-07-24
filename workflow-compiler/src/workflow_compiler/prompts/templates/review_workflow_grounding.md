---
name: review_workflow_grounding
description: Review pass 2 (grounding) for the discovered workflow metadata.
variables: [document_text, current]
---
You are reviewing the **grounding** of a workflow's discovered metadata. You do NOT
regenerate it. You verify that every metadata item is **explicitly supported by the
document**. Only explicit textual evidence counts — never implied business
knowledge.

Allowed actions for this pass:

- `remove` — a metadata item not supported by the document.
- `flag` — a metadata item that is doubtful but you are not certain is unsupported.
- `no_change` — every item is supported.

Do NOT add, rename, or merge. For `remove`/`flag`, set the patch `target` to the
list field (`actors`, `systems`, `trigger_events`, `start_states`, `end_states`)
and put the offending value in `payload.value`.

Example patch:
`{"action": "remove", "target": "actors", "payload": {"value": "Auditor"},
  "evidence": {"quote": "(no mention of an auditor anywhere in the document)"}}`

Return a `ReviewResult`, or an empty list / a single `no_change` patch if every item
is grounded.

DOCUMENT:
{{ document_text }}

CURRENT METADATA (JSON):
{{ current }}

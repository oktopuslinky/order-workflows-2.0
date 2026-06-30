---
name: review_workflow_consistency
description: Review pass 3 (consistency) for the discovered workflow metadata.
variables: [document_text, current]
---
You are reviewing the **internal consistency** of a workflow's discovered metadata.
You do NOT regenerate it. You look for:

- duplicate items within a field,
- semantically equivalent labels for the same thing (e.g. "OMS" and "Order
  Management System"),
- inconsistent naming.

Allowed actions for this pass:

- `merge` — collapse two or more equivalent items into one canonical label.
- `modify` — rename an item to a canonical label.
- `no_change` — the metadata is already consistent.

Do NOT add new items or remove grounded ones. For `merge`, set `target` to the list
field and use `payload.values` (the equivalent items) and `payload.into` (the
canonical label). For `modify`, set `target` to the field and use `payload.old` /
`payload.new`.

Example patch:
`{"action": "merge", "target": "systems",
  "payload": {"values": ["OMS", "Order Management System"], "into": "Order Management System"},
  "evidence": {"quote": "the OMS (Order Management System) records the order"}}`

Return a `ReviewResult`, or an empty list / a single `no_change` patch if the
metadata is already consistent.

DOCUMENT:
{{ document_text }}

CURRENT METADATA (JSON):
{{ current }}

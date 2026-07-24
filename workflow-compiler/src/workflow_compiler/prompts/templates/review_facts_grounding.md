---
name: review_facts_grounding
description: Review pass 2 (grounding) for the extracted workflow facts.
variables: [document_text, current]
---
You are reviewing the **grounding** of an extracted workflow. You do NOT regenerate
it. You verify that every workflow object is **explicitly supported by the
document**. Only explicit textual evidence counts. Never justify an object through
implied business knowledge, and never invent evidence.

Allowed actions for this pass:

- `remove` — an object not supported by the document.
- `flag` — an object that is doubtful but you are not certain is unsupported.
- `no_change` — every object is supported.

Do NOT add, rename, or merge.

Patch targets:

- Structure entities — `target` is `<kind>:<id>`, e.g. `activity:a3`,
  `decision:d1`, `exception:e2`, `compensation:c1`, `event:v1`.
- Flat facts — `target` is the category (`input`, `output`, `rule`, `api`,
  `system`, `timer`, `retry`) and `payload.value` is the statement to remove.

Example patch:
`{"action": "remove", "target": "activity:a5",
  "evidence": {"quote": "(no activity described for shipping insurance)"}}`

Return a `ReviewResult`, or an empty list / a single `no_change` patch if every
object is grounded.

DOCUMENT:
{{ document_text }}

CURRENT EXTRACTION (JSON):
{{ current }}

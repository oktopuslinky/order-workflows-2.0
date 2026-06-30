---
name: review_facts_consistency
description: Review pass 3 (consistency) for the extracted workflow facts.
variables: [document_text, current]
---
You are reviewing the **internal consistency** of an extracted workflow. You do NOT
regenerate it. You look for:

- duplicate activities, decisions, events, exceptions, compensations, business
  rules, or APIs;
- semantically equivalent labels for the same object;
- conflicting, impossible, or malformed relations (a decision branching to an
  unrelated step, a compensation tied to the wrong activity, a malformed parallel
  group);
- inconsistent ordering or naming.

Allowed actions for this pass:

- `merge` — collapse two equivalent objects into one.
- `modify` — rename to a canonical label, or fix a relation field.
- `no_change` — the extraction is already consistent.

Do NOT create new workflow objects.

Patch targets:

- `merge` — `target` is `<kind>:<keep_id>+<drop_id>` (the surviving id first), e.g.
  `activity:a2+a5` merges activity `a5` into `a2`. Only ids of the same kind may be
  merged; references to the dropped id are repointed to the kept id automatically.
- `modify` — `target` is `<kind>:<id>` and `payload` carries the fields to change
  (e.g. `{"raised_by": "a3"}` to fix an exception's owner, or `{"name": "Ship
  order"}` to rename). Relation fields must reference an existing id.

Example patches:
`{"action": "merge", "target": "activity:a2+a5",
  "evidence": {"quote": "ship the order ... shipping the package"}}`
`{"action": "modify", "target": "compensation:c1", "payload": {"compensates": "a2"},
  "evidence": {"quote": "release inventory reverses the order reservation"}}`

Return a `ReviewResult`, or an empty list / a single `no_change` patch if the
extraction is already consistent.

DOCUMENT:
{{ document_text }}

CURRENT EXTRACTION (JSON):
{{ current }}

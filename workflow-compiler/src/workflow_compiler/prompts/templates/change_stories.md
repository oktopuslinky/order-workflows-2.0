---
name: change_stories
description: Draft user stories (story, Given/When acceptance criteria, notes) for the epic's story map.
variables: [brief, stories_block, epic_ref]
---
You are a product owner writing **user stories** for the epic {{ epic_ref }},
in the same house style as the existing stories in the knowledge base (the
brief shows them: a three-line Story "As …, / I want …, / so that …", checkable
Acceptance Criteria written "Given …, when …, then …" / "Given …, the order
transitions to …", and Notes that cite the requirements implemented, the TDD
sections and the test cases). Ground everything in the DRAFTING BRIEF — the
change request, the approved impact analysis and epic, the knowledge-graph
excerpts and the requester's decisions.

Write exactly these stories, keeping the ids and titles as given (ids are
assigned by the system):

{{ stories_block }}

Rules per story:

- `as_a` starts with "As a …,", `i_want` with "I want …," and `so_that` with
  "so that ….". Name the real actor (fulfilment operator, customer, finance
  system, workflow…) rather than "user".
- `points` — Fibonacci sizing (1, 2, 3, 5, 8, 13) consistent with the existing
  stories' sizes.
- `acceptance` — 3 to 6 criteria, each starting with "Given"; use the real
  state names, activities, signals and queries from the brief (including the
  new states the change introduces), and cover the failure/compensation path
  where relevant.
- `implements` — the change-request requirement ids (e.g. BCR-01-02) this
  story implements; `notes` — one short paragraph like the existing stories'
  Notes: "Implements BCR-01-0N. See TDD-… §… and TC-…" plus one design remark,
  referring only to documents/ids in the brief (the new TDD id given in the
  brief may be cited).
- `epic` — "{{ epic_ref }}"; `status` — "Proposed".

Return ONLY a JSON object:
{"stories": [{"id": "US-0NN", "title": "...", "epic": "{{ epic_ref }}", "status": "Proposed", "points": 5, "as_a": "As a …,", "i_want": "I want …,", "so_that": "so that ….", "acceptance": ["Given …"], "notes": "...", "implements": ["BCR-01-01"]}]}

## Drafting brief

{{ brief }}

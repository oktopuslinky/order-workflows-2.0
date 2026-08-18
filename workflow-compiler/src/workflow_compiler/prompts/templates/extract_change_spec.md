---
name: extract_change_spec
description: Extract a change spec (existing vs. proposed per component) from a technical design document, grounded in the knowledge graph.
variables: [document_text, impact_table, seed_components, requirement_ids]
optional: [kg_context]
---
You are a senior engineer reading a technical design document (TDD) that
describes a change to an existing system. Produce a CHANGE SPEC: one entry per
component the change touches, each stating what exists today and what the
design proposes.

A component is a concrete engineering artifact — a module / source file, an
activity or function, a workflow class, a data type / enum / dataclass, a
signal, a query, a test (file or test-case id), a diagram file, or a business
document. It is NOT a chapter of the design document: "Data Contracts" is not a
component, `shared/types.py` and `OrderState` are.

For each component provide:

- name: the exact identifier used in the design / knowledge base
  (`provision_order`, `OrderState`, `workflows/order_workflow.py`,
  `tests/test_order_workflow.py`, `order-state-machine.mmd`, `TC-06`).
- kind: one of module | activity | workflow | type | signal | query | test |
  diagram | doc.
- path: where it lives, copied from the knowledge-graph context or the impact
  table when available — a node id like `mod:existing_Codebase/shared/types.py`
  or `fn:existing_Codebase/activities/order_activities.py:provision_order`, or a
  corpus-relative file path. Use "" for a component that does not exist yet.
- existing: what exists today, in 1–4 sentences (from the TDD's "Existing"
  parts and the knowledge-graph excerpts). "" if it is new.
- proposed: what the design proposes for it, concretely (new states, new
  fields/types, new parameters, fan-out per group, new tests, new diagram
  content). Never leave this empty — for a removal, say what is removed and what
  replaces it; for a verify-only entry, say what must be re-verified and why.
- change_type: modify | add | remove | verify.
- requirement_ids: the change-request requirement ids this change serves,
  taken ONLY from the list below (empty when none applies).

Rules:
- Cover every file the design says changes: the types/shared module, the
  activities module, the workflow module, the tests, and every diagram the
  design lists under "Diagrams Needed" — each as its own component. Also add
  entries for individual activities / types / signals / queries the design
  changes or adds when the design describes them individually.
- Prefer names and paths from the KNOWLEDGE-GRAPH CONTEXT and the IMPACT TABLE
  over paraphrases. Do not invent paths.
- The SEED COMPONENTS (from the approved impact analysis) are the starting
  point: keep every one that the design confirms (refine its texts), drop only
  those the design clearly does not touch, and add what the design adds.
- Also list "assumptions" (things you had to assume to fill a component) and
  "open_questions" (things the design leaves undecided that engineering must
  settle) — short sentences, empty lists when none.

Return a single JSON object:
{"components": [{"name": "...", "kind": "...", "path": "...", "existing": "...",
  "proposed": "...", "change_type": "...", "requirement_ids": ["..."]}],
 "assumptions": ["..."], "open_questions": ["..."]}
and nothing else.

CHANGE-REQUEST REQUIREMENT IDS (the only ids allowed in requirement_ids):
{{ requirement_ids }}

SEED COMPONENTS (from the approved impact analysis; kind | name | change | path | rationale):
{{ seed_components }}

IMPACT TABLE (deterministic knowledge-graph traversal; type | name | node id | path):
{{ impact_table }}

{{ kg_context }}DESIGN DOCUMENT:
{{ document_text }}

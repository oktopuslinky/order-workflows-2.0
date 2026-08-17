---
name: change_impact
description: Draft the impact analysis of a business change request against the existing system.
variables: [brief]
---
You are a senior engineer writing the **Impact Analysis** for a business change
request. The DRAFTING BRIEF below contains the change request, knowledge-graph
excerpts from the existing documentation and code (real names, paths, line
spans), a deterministic impact traversal over the knowledge graph, and the
decisions the requester made in the clarifying questions.

Write the analysis strictly from that material:

- **summary** — two or three paragraphs: what changes, why it is structural
  (or not), and the overall approach. Plain markdown, no headings.
- **requirements** — one row per requirement id in the change request, in
  order: `req_id`, the requirement text (may be shortened), and `impact` — which
  existing components/documents/tests it touches and how.
- **affected** — the affected-components table. One row per concrete artifact,
  naming it EXACTLY as it appears in the brief (file paths such as
  `existing_Codebase/shared/types.py`, activity/function names such as
  `complete_order`, document ids such as `US-004`, `TC-06`, `EPIC-001`, sections
  such as `TDD §4.3` / `TP §3.2`). Cover, where the brief supports it: source
  modules and the functions/classes/types inside them, the workflow's
  signals/queries, the state-machine and sequence diagrams, the existing epic
  (definition of done / story map), the user stories that change behaviour, the
  test plan scope and the individual test cases that must be updated or added,
  and the BRD scope line if any. `kind` is one of module | function | class |
  type | document | story | test_case | test_plan | epic | diagram | requirement
  | other; `change_type` is modify | add | remove | verify; `kg_ref` is the
  knowledge-graph node id when the brief shows one (else empty).
- **design_impacts** — bullets in the change request's §4 style,
  "Component: what must change", including anything the change request missed
  (validation of partially available orders, status query shape, worker
  registration, test doubles…).
- **risks** — risks and assumptions, one line each.
- **open_decisions** — decisions still needed from named owners (Finance,
  Product, Engineering) — one line each; include decisions the requester
  explicitly left open.

Be specific and grounded: prefer a real name from the brief over a generic
phrase, and say "not found in the knowledge base" rather than invent a file.

Return ONLY a JSON object:
{"summary": "...", "requirements": [{"req_id": "...", "requirement": "...", "impact": "..."}], "affected": [{"kind": "...", "ref": "...", "change_type": "...", "rationale": "...", "kg_ref": "..."}], "design_impacts": ["..."], "risks": ["..."], "open_decisions": ["..."]}

## Drafting brief

{{ brief }}

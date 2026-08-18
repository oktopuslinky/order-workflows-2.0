---
name: update_test_cases
description: Propose new test-case rows and updates to existing rows of the test-case matrix, plus a test-plan addendum, for an approved change.
variables: [change_title, change_request_id, change_spec, existing_matrix, test_plan_excerpt, tests_summary, design_summary, next_tc_id, tc_types]
optional: [kg_context]
---
You are the QA lead extending the test documentation of an existing system for
an approved change: {{ change_title }} ({{ change_request_id }}).

You are given the EXISTING TEST-CASE MATRIX (every row, all columns), an
excerpt of the EXISTING TEST PLAN, the approved CHANGE SPEC (existing vs.
proposed per component; its `test` rows name the test cases to update or add),
the Temporal DESIGN and a summary of the UPDATED AUTOMATED TESTS. Produce:

1. `new_cases` — one row per NEW scenario the change requires (at least: split
   into shipment groups at provisioning, independent per-group dispatch
   failure and compensation, cancel of one group while others continue, cancel
   of the whole order across groups, per-group status query, consolidated
   completion after all groups deliver — and whatever else the change spec's
   `add` test rows name). Do NOT put an id on them; ids are assigned by the
   system starting at {{ next_tc_id }}. Fields: title ("<Scenario> — <detail>"),
   preconditions, steps (numbered "1. … 2. …" in one cell), expected (the
   observable result incl. state names), type (one of: {{ tc_types }}), automated
   (Yes | Manual (…) | Planned), linked (US-/TDD §/BCR ids), notes.
2. `updated_cases` — one entry per EXISTING row whose expectation, steps or
   traceability changes (the change spec's `modify`/`verify` test rows such as
   TC-05/06/09/10 and any row whose expected state names change). Give the
   `tc_id` and ONLY the fields that change; put the reason in `notes` (it is
   appended to the original note). Rows you do not list stay as they are.
3. `addendum` — the test-plan changes as short bullet strings:
   `out_of_scope_removed` (the plan's out-of-scope line(s) this change now
   brings into scope, quoted), `in_scope_added`, `test_types_added` ("Type —
   description" like the plan's §4.2), `test_data_added` (helpers / doubles the
   new tests need), `deliverables_added`, `exit_criteria_added`, `risks_added`,
   `notes`.

Rules: use the design's real names (states, activities, signals, queries,
types); keep the matrix's vocabulary and style; never renumber or delete
existing rows; be concrete and testable; no Markdown tables inside cells.

Return a single JSON object:
{"new_cases": [{"title": "...", "preconditions": "...", "steps": "...", "expected": "...",
  "type": "...", "automated": "...", "linked": "...", "notes": "..."}],
 "updated_cases": [{"tc_id": "TC-06", "expected": "...", "notes": "..."}],
 "addendum": {"out_of_scope_removed": ["..."], "in_scope_added": ["..."],
  "test_types_added": ["..."], "test_data_added": ["..."], "deliverables_added": ["..."],
  "exit_criteria_added": ["..."], "risks_added": ["..."], "notes": ["..."]}}
and nothing else.

EXISTING TEST-CASE MATRIX (TC ID | Title | Preconditions | Steps | Expected Result | Type | Automated | Linked | Notes):
{{ existing_matrix }}

EXISTING TEST PLAN (excerpt):
{{ test_plan_excerpt }}

UPDATED AUTOMATED TESTS (summary of the rewritten test module):
{{ tests_summary }}

TEMPORAL DESIGN (approved):
{{ design_summary }}

{{ kg_context }}CHANGE SPEC (approved; existing vs. proposed per component):
{{ change_spec }}

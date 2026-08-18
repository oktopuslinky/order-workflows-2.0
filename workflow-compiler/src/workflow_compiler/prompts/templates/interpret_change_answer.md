---
name: interpret_change_answer
description: Translate a user's prose answer to a change-spec question into deterministic component updates.
variables: [question, answer, followup_context, current_changes]
---
A user was asked a question about the CHANGE SPEC below (existing vs. proposed
per component of a code change) and answered in their own words. Translate the
answer into minimal, deterministic updates to that change spec.

QUESTION ASKED:
{{ question }}

THE USER'S ANSWER:
{{ answer }}
{{ followup_context }}

The answer carries HUMAN AUTHORITY: never refuse or second-guess it, and never
invent a change it does not support. Emit an update ONLY for what actually
changes.

## Choosing a disposition

Pick exactly one:

1. **The answer maps to concrete updates** → return them in "updates", leave
   "needs_followup" false. Prefer this whenever the answer names a real
   component, path, requirement id, or describes what a component's proposed
   change is.
2. **The answer is on-topic but too vague to act on** → set "needs_followup"
   true and put ONE specific clarifying question in "followup_question", with
   two to four likely answers in "followup_options" (`{"label", "detail"}`),
   grounded in the change spec's real component names / paths. Only when a
   single short clarification would unlock a real update.
3. **The answer cannot become a change-spec update** — the user does not know,
   defers, or raises something outside this spec → leave "updates" empty,
   "needs_followup" false, and put a one-sentence restatement in "park_note".
   It is recorded as an open question. Never discard what they said.

If a clarifying follow-up was ALREADY asked (shown above), do NOT ask another —
map the answer or park it.

## Update operations (the "updates" list)

Each update: {"action": "modify" | "add" | "remove", "name": "<component name>",
"kind": "<module|activity|workflow|type|signal|query|test|diagram|doc or null>",
"path": <string or null>, "existing": <string or null>, "proposed": <string or null>,
"change_type": <"modify"|"add"|"remove"|"verify" or null>,
"requirement_ids": <list of ids or null>, "evidence": "<the part of the answer you act on>"}

- "modify": name (and kind, when the same name exists under several kinds) must
  match a `### name — kind, change` heading in the change spec; carry ONLY the
  fields that change (null = leave as is). To fill an empty "Proposed", set
  "proposed". To fix a path the user corrected, set "path". To drop a wrong
  requirement id, set "requirement_ids" to the full corrected list.
- "add": a component the spec does not list; carry name, kind, change_type and
  proposed at least.
- "remove": the user says the component is not affected after all.
- "resolve_questions": the exact texts of Open Questions in the change spec that
  this answer settles (empty when none).

## Worked examples

Q: "The change spec has no proposed change for tests/test_order_workflow.py — what should change there?"
A: "add tests for the split into groups, one group failing while the other ships, and cancelling a single group"
→ {"updates": [{"action": "modify", "name": "tests/test_order_workflow.py", "proposed": "Add tests for the split into shipment groups, for one group failing while the other ships, and for cancelling a single group.", "evidence": "add tests for the split into groups, one group failing while the other ships, and cancelling a single group"}], "needs_followup": false}

Q: "`OrderState` points at `shared/state.py`, which is not in the knowledge base — where does it live?"
A: "it's in shared/types.py"
→ {"updates": [{"action": "modify", "name": "OrderState", "path": "existing_Codebase/shared/types.py", "evidence": "it's in shared/types.py"}], "needs_followup": false}

Q: "Component provision_order cites BCR-01-09, which the change request does not declare — which requirement is it?"
A: "not sure, ask the product owner"
→ {"updates": [], "needs_followup": false, "park_note": "The requirement id behind the provision_order change is unknown; the product owner must confirm it."}

Return ONLY a JSON object:
{"updates": [...], "resolve_questions": [], "needs_followup": false, "followup_question": null, "followup_options": [], "park_note": null, "note": "..."}

CURRENT CHANGE SPEC:
{{ current_changes }}

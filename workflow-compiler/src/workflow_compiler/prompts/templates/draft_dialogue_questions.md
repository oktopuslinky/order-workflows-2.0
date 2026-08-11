---
name: draft_dialogue_questions
description: Turn spec findings and open questions into plain-language questions for the user.
variables: [workflow_slug, findings_block, questions_block, current_spec]
---
You are helping a business user resolve problems in the specification for the
workflow "{{ workflow_slug }}". Below are the unresolved items: validator
FINDINGS and the spec's own OPEN QUESTIONS. Turn them into questions a
non-technical person can answer in ordinary prose.

Rules:

- **Group aggressively.** Several items that are really the same gap must
  become ONE question. Two findings about the same missing output, or a finding
  and an open question describing the same hole, are one question. Prefer four
  good questions over eleven mechanical ones.
- **Never ask about the schema.** Ask about the business process. Say "what
  happens to the order when payment fails?", never "which value should the
  `on_failure` field of decision d2 take?".
- Ask about ONE decision per question, so the answer can be acted on.
- Give just enough context that the question stands alone — name the step,
  output, or actor concerned — but keep it to a sentence or two.
- Do not ask the user to confirm something the specification already states.
- Every item below must be covered by exactly one question. Copy the items a
  question covers VERBATIM into its "covers" list, so nothing is lost.
- Order the questions so the blocking ones come first.

Return ONLY a JSON object:
{"questions": [{"slug": "{{ workflow_slug }}", "question": "...", "section": "<spec section or null>", "covers": ["<verbatim item>", ...]}], "note": "..."}

## Worked example

Items:
  [BLOCK] Outputs > Payment Confirmed: produced but never consumed by any workflow.
  [BLOCK] Decisions > d2: the "payment declined" branch has no target.
  [WARN] Actors: "Billing" appears in a rule but is not listed as an actor.

→ {"questions": [
     {"slug": "{{ workflow_slug }}", "question": "When a payment is confirmed, what happens next — and what should happen instead when the payment is declined?", "section": "Decisions", "covers": ["Outputs > Payment Confirmed: produced but never consumed by any workflow.", "Decisions > d2: the \"payment declined\" branch has no target."]},
     {"slug": "{{ workflow_slug }}", "question": "Is Billing a team that takes part in this process, or just a system the process talks to?", "section": "Actors", "covers": ["Actors: \"Billing\" appears in a rule but is not listed as an actor."]}
   ], "note": "grouped the two payment-path items"}

FINDINGS:
{{ findings_block }}

OPEN QUESTIONS:
{{ questions_block }}

CURRENT SPECIFICATION:
{{ current_spec }}

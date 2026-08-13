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

## Suggested answers (the "options" list)

For each question, offer the answers you think are actually likely, so the user
can pick one instead of composing a sentence. They are a shortcut, never a
shortlist — the user always has a free-text box and may ignore every option.

- **Ground every option in the material you were given.** Prefer actors,
  systems, states, steps and downstream workflows that appear in the
  SPECIFICATION below, and paths the document implies. Do not invent a plausible
  business practice the material gives you no reason to believe.
- **Two to four options**, and fewer is better than padded. If you cannot think
  of a genuinely likely answer, return an empty list — a bad option is worse
  than none, because it invites the user to agree with something you made up.
- **Make them mutually exclusive**, so picking one is a real decision. Do not
  offer near-duplicates.
- **Phrase each as the user would say it**, in the first person and in business
  language: "It goes to the shipping team for manual review", not
  "SET decision.no_target = shipping-review". Each option is sent as if the user
  had typed it, so it must read as a complete answer to the question.
- Put any consequence worth knowing in "detail", one short clause. Leave it
  empty when the label already says everything.

Return ONLY a JSON object:
{"questions": [{"slug": "{{ workflow_slug }}", "question": "...", "section": "<spec section or null>", "covers": ["<verbatim item>", ...], "options": [{"label": "...", "detail": "..."}]}], "note": "..."}

## Worked example

Items:
  [BLOCK] Outputs > Payment Confirmed: produced but never consumed by any workflow.
  [BLOCK] Decisions > d2: the "payment declined" branch has no target.
  [WARN] Actors: "Billing" appears in a rule but is not listed as an actor.

(The specification lists the actors Warehouse and Support, and a cross-reference
to the workflow "order-fulfilment".)

→ {"questions": [
     {"slug": "{{ workflow_slug }}", "question": "When a payment is confirmed, what happens next — and what should happen instead when the payment is declined?", "section": "Decisions", "covers": ["Outputs > Payment Confirmed: produced but never consumed by any workflow.", "Decisions > d2: the \"payment declined\" branch has no target."], "options": [
       {"label": "A confirmed payment hands the order to order-fulfilment; a declined one is cancelled and the customer is told why.", "detail": "Ends the process on decline — no retry."},
       {"label": "A confirmed payment hands the order to order-fulfilment; a declined one is retried once before we cancel it.", "detail": "Adds a retry step before the cancellation path."},
       {"label": "A confirmed payment hands the order to order-fulfilment; a declined one goes to Support to sort out with the customer.", "detail": "Support already appears as an actor."}
     ]},
     {"slug": "{{ workflow_slug }}", "question": "Is Billing a team that takes part in this process, or just a system the process talks to?", "section": "Actors", "covers": ["Actors: \"Billing\" appears in a rule but is not listed as an actor."], "options": [
       {"label": "Billing is a team that takes part in this process.", "detail": "Adds Billing alongside Warehouse and Support."},
       {"label": "Billing is a system we call, not a team.", "detail": "Recorded as a system instead of an actor."}
     ]}
   ], "note": "grouped the two payment-path items"}

FINDINGS:
{{ findings_block }}

OPEN QUESTIONS:
{{ questions_block }}

CURRENT SPECIFICATION:
{{ current_spec }}

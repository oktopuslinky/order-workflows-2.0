---
name: change_answer
description: Turn a requester's answer to a wizard question into one brief line for the drafter.
variables: [step_label, question, answer, followup_context, brief_context]
---
A requester is answering clarifying questions before the **{{ step_label }}** of a
business change request is drafted. Read ONE answer and turn it into a single
declarative line the drafter can act on — a decision, constraint or scope
statement written in the third person, e.g. "Finance decided on one
consolidated invoice per order; itemized invoicing is out of scope."

Rules:

- The requester has authority. Never second-guess, soften or extend the answer.
- Keep concrete names from the answer and the context (states, activities,
  documents, requirement ids). Do not invent details.
- If the answer is too vague to act on ("whatever is best", "not sure"),
  set "resolved": false and ask ONE specific clarifying follow-up with two to
  four grounded options — unless a follow-up was already asked, in which case
  restate the answer as best you can and resolve.
- If the answer says the point is undecided or should be left open, resolve
  with a note that records it as an open decision ("Open decision: …").
{{ followup_context }}
Question asked:
{{ question }}

Requester's answer:
{{ answer }}

Context (excerpt of the drafting brief):
{{ brief_context }}

Return ONLY a JSON object:
{"note": "...", "resolved": true, "followup_question": null, "followup_options": []}

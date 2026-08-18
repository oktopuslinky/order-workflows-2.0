---
name: draft_change_questions
description: Turn change-spec findings and open questions into plain-language questions for the engineer reviewing changes.md.
variables: [findings_block, questions_block, current_changes]
---
You are helping an engineer resolve problems in a CHANGE SPEC — the file
`changes.md` that lists, per component of an existing code base (modules,
activities, workflows, types, signals, queries, tests, diagrams, documents),
what exists today and what a design document proposes to change. Below are the
unresolved items: validator FINDINGS and the change spec's own OPEN QUESTIONS.
Turn them into questions the engineer can answer in ordinary prose.

Rules:

- **Group aggressively.** Several items about the same component or the same
  gap must become ONE question. Prefer four good questions over eleven
  mechanical ones.
- Ask about the change, not the file format: "what should change in the test
  module for shipment groups?", never "fill the Proposed block of heading 3".
- Ask about ONE decision per question, so the answer can be acted on. Name the
  component (and its path when there is one) so the question stands alone.
- A finding that says a path is not in the knowledge base usually carries
  suggestions ("did you mean …") — offer those as the options.
- Do not ask the engineer to confirm something the change spec already states.
- Every item below must be covered by exactly one question. Copy the items a
  question covers VERBATIM into its "covers" list, so nothing is lost.
- Order the questions so the blocking ones (components with no proposed change)
  come first.

## Suggested answers (the "options" list)

For each question, offer the 2–4 answers you think are actually likely, grounded
in the change spec's real component names, paths and requirement ids (never
invented ones). Each option is `{"label": "<short answer the user could send
as-is>", "detail": "<one clause on what it implies, or empty>"}`. Leave the list
empty when there is no sensible short answer (e.g. free-text descriptions).

Return ONLY a JSON object:
{"questions": [{"slug": "__changes__", "question": "...", "covers": ["<verbatim item>", ...],
  "section": "Components" | "Open Questions" | null,
  "options": [{"label": "...", "detail": "..."}]}],
 "note": "..."}

FINDINGS:
{{ findings_block }}

OPEN QUESTIONS:
{{ questions_block }}

CURRENT CHANGE SPEC:
{{ current_changes }}

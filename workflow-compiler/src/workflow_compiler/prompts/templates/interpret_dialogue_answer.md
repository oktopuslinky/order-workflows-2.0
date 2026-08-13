---
name: interpret_dialogue_answer
description: Translate a user's prose answer to a spec question into deterministic patches.
variables: [workflow_slug, question, answer, followup_context, current_spec]
---
A user was asked a question about the specification for workflow
"{{ workflow_slug }}" and answered in their own words. Translate their answer
into minimal, deterministic operations against the specification below.

QUESTION ASKED:
{{ question }}

THE USER'S ANSWER:
{{ answer }}
{{ followup_context }}

The answer carries HUMAN AUTHORITY:
- Never refuse, soften, or second-guess what the user says. They know the
  business process; the specification is what is wrong.
- Never invent a change the answer does not support. Translate only what was
  actually said.
- Emit an operation ONLY for what actually changes. Before emitting an "add",
  check the CURRENT SPECIFICATION: if the value is already present, do not add
  it again.

## Choosing a disposition

Pick exactly one:

1. **The answer maps to concrete changes** → return them in "patches", leave
   "needs_followup" false. This is the normal case; prefer it whenever the
   answer names a real step, actor, system, rule, or path.
2. **The answer is on-topic but too vague to act on** → set
   "needs_followup": true and put ONE specific clarifying question in
   "followup_question". Ask for the missing specific, not a general re-ask:
   "which team picks it up?" rather than "can you clarify?". Use this only when
   a single short clarification would unlock a real patch.

   Offer two to four likely answers to it in "followup_options", each
   `{"label": ..., "detail": ...}`. This is where they matter most: the user was
   vague because the specifics were not to hand, so naming the plausible ones is
   the fastest way out. Ground them in the CURRENT SPECIFICATION — real actors,
   real states, real steps — and phrase each as a complete answer the user could
   have typed. Return an empty list rather than inventing a candidate.
3. **The answer cannot become a spec change at all** — the user does not know,
   defers to someone else, or raises something outside this specification →
   leave "patches" empty, "needs_followup" false, and put a one-sentence
   restatement of what they told you in "park_note". It is recorded as a new
   open question on the spec. Never discard what they said.

If the user has already been asked a clarifying follow-up (shown above), do NOT
ask another — either map the answer to patches or park it.

## Patch operations (the "patches" list)

Each patch: {"action": ..., "target": ..., "payload": {...}, "evidence": {"quote": "<the part of the user's answer you are acting on>"}}

Targets and payloads:

1. Structure entities — target "<kind>:<id>" using the [id] markers shown in
   the specification (e.g. "activity:a3"). Kinds: activity, decision,
   exception, compensation, event.
   - add: target is just the kind (e.g. "activity"); payload carries the
     fields: activities {"name", optional "parallel_group"}; decisions
     {"question", "after", "yes_target", "no_target"}; exceptions
     {"reason", "raised_by"}; compensations {"name", "compensates"};
     events {"name", "emitted_by", "kind"}. Reference other entities by id.
   - modify: target "<kind>:<id>"; payload has only the fields to change.
   - remove: target "<kind>:<id>".
2. Scalar facts — target is the category: input, output, rule, api, system,
   timer, retry.
   - add: payload {"value": "<statement>"}.
   - modify: payload {"old": "<exact current statement>", "new": "<new statement>"}.
   - remove: payload {"value": "<exact current statement>"}.
3. Metadata — target is the field name.
   - List fields (actors, systems, trigger_events, start_states, end_states,
     tags): add/remove use payload {"value": ...}; modify uses
     {"old": ..., "new": ...}.
   - Scalar fields (name, purpose, description, domain, owner): modify with
     payload {"value": "<new value>"}.

For "modify" on a scalar fact, copy the current statement char-for-char from
the specification as "old" — a paraphrased "old" will not match and the
operation is dropped.

## Cross-workflow dependencies (the "xref_ops" list)

A dependency between two workflows belongs to the project, not to either spec,
so it is NOT a patch. When the question asks whether a detected hand-off is
real, answer with "xref_ops" instead:

Each op: {"action": "modify" | "remove" | "add", "reference": {"source_workflow": "...", "output_field": "...", "output_type": "...", "target_workflow": "...", "input_field": "...", "input_type": "...", "description": "..."}}

- **The user confirms it is real** → "modify" carrying the dependency EXACTLY as
  the specification already states it. Applying it marks the dependency
  confirmed, which is what unblocks approval.
- **The user corrects it** (wrong field, wrong target) → "modify" carrying the
  corrected reference. Keep the source workflow the same.
- **The user says it is not real** → "remove" carrying the dependency as stated.
- Only use "add" when the user describes a hand-off the specification does not
  list at all.

Copy the field names and workflow slugs from the CURRENT SPECIFICATION's
Cross-Workflow Dependencies section — an operation naming a workflow that does
not exist is dropped.

## Worked examples

Q: "When a payment is confirmed, what happens next?"
A: "it goes to the shipping workflow, they pack it and send it out"
→ {"patches": [{"action": "add", "target": "activity", "payload": {"name": "Pack and ship order"}, "evidence": {"quote": "they pack it and send it out"}}], "needs_followup": false}

Q: "Is Billing a team or a system?"
A: "Billing is a team, they handle the invoices"
→ {"patches": [{"action": "add", "target": "actors", "payload": {"value": "Billing"}, "evidence": {"quote": "Billing is a team"}}], "needs_followup": false}

Q: "What happens when the payment is declined?"
A: "depends on the customer"
→ {"patches": [], "needs_followup": true, "followup_question": "Which customers get which treatment — for example, do repeat customers get a retry while new ones are cancelled?", "followup_options": [{"label": "Repeat customers get one retry; new customers are cancelled straight away.", "detail": "Two branches off the declined path."}, {"label": "Everyone gets one retry, and we only cancel if it fails twice.", "detail": "One retry step, no customer split."}, {"label": "Support decides case by case.", "detail": "Hands the declined path to Support."}]}

Q: "What happens when the payment is declined?"
A: "honestly not sure, ops owns that decision and they haven't told us yet"
→ {"patches": [], "needs_followup": false, "park_note": "The declined-payment path is owned by the ops team and has not been decided yet."}

Q: "Does customer-onboarding really hand customer_record_id to account-provisioning, or did we detect that wrongly?"
A: "yes that's right, provisioning can't start without the customer record"
→ {"patches": [], "xref_ops": [{"action": "modify", "reference": {"source_workflow": "customer-onboarding", "output_field": "customer_record_id", "output_type": "str", "target_workflow": "account-provisioning", "input_field": "customer_record_id", "input_type": "str", "description": "Account Provisioning consumes the customer_record_id produced by Customer Onboarding"}}], "needs_followup": false}

Q: "Does customer-onboarding really hand customer_record_id to account-provisioning?"
A: "no, provisioning looks that up from the CRM itself"
→ {"patches": [], "xref_ops": [{"action": "remove", "reference": {"source_workflow": "customer-onboarding", "output_field": "customer_record_id", "output_type": "str", "target_workflow": "account-provisioning", "input_field": "customer_record_id", "input_type": "str"}}], "needs_followup": false}

Return ONLY a JSON object:
{"patches": [...], "xref_ops": [], "needs_followup": false, "followup_question": null, "followup_options": [], "park_note": null, "note": "..."}

CURRENT SPECIFICATION:
{{ current_spec }}

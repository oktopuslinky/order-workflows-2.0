---
name: interpret_spec_instruction
description: Translate a user's free-form instruction into deterministic spec patches.
variables: [instruction, transcript_block, slug_block, target_slug, clarification_context, current_spec]
---
A user is editing a workflow specification by talking to you. They have just
told you what they want changed. Translate it into minimal, deterministic
operations against the specification below.

THE USER'S INSTRUCTION:
{{ instruction }}
{{ clarification_context }}

WORKFLOWS IN THIS PROJECT:
{{ slug_block }}

The specification shown below is for "{{ target_slug }}". Set "target_slug" to
the workflow the instruction actually concerns. If the instruction is plainly
about a different workflow than the one shown, say so in "target_slug" and set
"needs_clarification": true rather than patching the wrong specification.

RECENT CONVERSATION (oldest first, for context only — do not re-apply anything
already done here):
{{ transcript_block }}

The instruction carries HUMAN AUTHORITY:
- Never refuse, soften, or second-guess it. The user knows the business process;
  the specification is what is wrong.
- Never invent a change the instruction does not support. Translate only what
  was actually asked for.
- Emit an operation ONLY for what actually changes. Before emitting an "add",
  check the CURRENT SPECIFICATION: if the value is already there, do not add it
  again — use "already_satisfied" instead.

## Choosing a disposition

Pick exactly one:

1. **The instruction maps to concrete changes** → return them in "patches" and
   leave the other flags false. This is the normal case; prefer it whenever the
   instruction names a real step, actor, system, rule, timer, or path.
2. **The specification already says it** → set "already_satisfied": true, leave
   "patches" empty, and say so in "reply". Do not emit a duplicate add.
3. **On-topic but too vague to act on** → set "needs_clarification": true and
   put ONE specific question in "clarifying_question". Ask for the missing
   specific — "which step should the refund happen after?" rather than "can you
   clarify?". Use this only when a single short answer would unlock a real patch.

   Offer two to four likely replies in "clarifying_options", each
   `{"label": ..., "detail": ...}`. Ground them in the CURRENT SPECIFICATION —
   real steps, real actors, real states — and phrase each as a complete answer
   the user could have typed, in business language. Make them mutually
   exclusive. Return an empty list rather than inventing a candidate: a bad
   option invites the user to agree with something you made up.
4. **Cannot become a spec change at all** — a question about the process, a
   note for later, something outside this specification → leave "patches" empty,
   all flags false, and put a one-sentence restatement in "park_note". It is
   recorded as a new open question. Never discard what the user said.

Always fill "reply" with one or two plain sentences telling the user what you
did, in their language — not a restatement of the patch operations. For a
change: "Added a refund step after payment confirmation." For a question: ask
it. Never mention JSON, patches, or targets in "reply".

## Patch operations (the "patches" list)

Each patch: {"action": ..., "target": ..., "payload": {...}, "evidence": {"quote": "<the part of the instruction you are acting on>"}}

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

## Worked examples

"add a refund step after payment is confirmed"
→ {"target_slug": "{{ target_slug }}", "patches": [{"action": "add", "target": "activity", "payload": {"name": "Issue refund"}, "evidence": {"quote": "add a refund step"}}], "reply": "Added a refund step after payment confirmation."}

"the retry timeout should be 30 seconds, not 10"
→ {"target_slug": "{{ target_slug }}", "patches": [{"action": "modify", "target": "retry", "payload": {"old": "Retry the charge after 10 seconds", "new": "Retry the charge after 30 seconds"}, "evidence": {"quote": "should be 30 seconds"}}], "reply": "Changed the retry delay to 30 seconds."}

"warehouse should be listed as an actor" (Warehouse already in actors)
→ {"target_slug": "{{ target_slug }}", "patches": [], "already_satisfied": true, "reply": "Warehouse is already listed as an actor on this workflow."}

"make the cancellation path better"
→ {"target_slug": "{{ target_slug }}", "patches": [], "needs_clarification": true, "clarifying_question": "What should change about it — is a step missing, or is the order of the existing steps wrong?", "clarifying_options": [{"label": "A step is missing — we never tell the customer the order was cancelled.", "detail": "Adds a notification step to the cancellation path."}, {"label": "The order is wrong — we refund before we release the inventory.", "detail": "Reorders the two existing steps."}]}

"who owns this process anyway?"
→ {"target_slug": "{{ target_slug }}", "patches": [], "park_note": "The owner of this workflow needs to be confirmed.", "reply": "That is not something I can read off the specification, so I have recorded it as an open question."}

Return ONLY a JSON object:
{"target_slug": "...", "patches": [...], "reply": "...", "already_satisfied": false, "needs_clarification": false, "clarifying_question": null, "clarifying_options": [], "park_note": null, "note": "..."}

CURRENT SPECIFICATION:
{{ current_spec }}

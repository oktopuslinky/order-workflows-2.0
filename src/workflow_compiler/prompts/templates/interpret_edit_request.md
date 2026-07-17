---
name: interpret_edit_request
description: Translate a human edit-request section into deterministic patch operations.
variables: [workflow_slug, edit_section, current_spec, project_context]
---
You translate one section of a human-authored EDIT REQUEST into minimal,
deterministic operations against the current workflow specification shown
below. The request targets the workflow "{{ workflow_slug }}".

The edit request carries HUMAN AUTHORITY:
- Never refuse, soften, or second-guess a requested change.
- Never invent a change the request does not ask for.
- Translate every bullet entry into one or more operations. If an entry is too
  vague or does not match anything in the specification, copy it VERBATIM into
  the "unresolved" list instead of guessing.
- Emit an operation ONLY for what actually changes. Before emitting an "add",
  check the CURRENT SPECIFICATION: if the value (a system, actor, rule,
  activity, …) is already present there, do NOT emit the add — duplicate adds
  are treated as errors and abort the whole edit request.

## Patch operations (the "patches" list)

Each patch: {"action": ..., "target": ..., "payload": {...}, "evidence": {"quote": "<the edit-request bullet you are translating>"}}

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
   - merge: target "<keepId>+<dropId>" (e.g. "a2+a5").
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

## Wiring operations

Use "trigger_ops" for cross-workflow triggers (one workflow starting another)
and "xref_ops" for output→input data dependencies. The project context below
lists the existing wiring and all workflow slugs.

- trigger_ops entry: {"action": "add"|"remove"|"modify",
  "source_workflow": "<slug>", "target_workflow": "<slug>",
  "trigger": { "source_workflow": ..., "target_workflow": ...,
  "mode": "blocking"|"fire_and_forget", "condition": <string or null>,
  "input_map": [{"target_input": ..., "source": "workflow_input"|"step_output"|"constant",
  "source_ref": ..., "type": ...}], "result_binding": <string or null> }}.
  For "remove", omit "trigger".
- xref_ops entry: {"action": "add"|"remove"|"modify", "reference":
  {"source_workflow": ..., "output_field": ..., "target_workflow": ...,
  "input_field": ..., "output_type": ..., "input_type": ..., "description": ...}}.

## Worked examples

Entry: 'After "Release inventory", the system notifies the warehouse team via the Notification Service.'
→ {"action": "add", "target": "activity", "payload": {"name": "Notify warehouse team"}, "evidence": {"quote": "After \"Release inventory\", the system notifies the warehouse team via the Notification Service."}}
  (plus {"action": "add", "target": "system", "payload": {"value": "Notification Service"}} ONLY if "Notification Service" does not already appear in the specification's systems — check before adding; a duplicate add aborts the edit)

Entry: '"Deprovision service" retry count changes from 3 to 5.'
→ {"action": "modify", "target": "retry", "payload": {"old": "Deprovision service: retry up to 3 times with exponential backoff", "new": "Deprovision service: retry up to 5 times with exponential backoff"}, "evidence": {"quote": "\"Deprovision service\" retry count changes from 3 to 5."}}
  (use the EXACT current statement from the specification as "old")

Entry: 'Remove the manager-approval rule for orders above $1,000.'
→ {"action": "remove", "target": "rule", "payload": {"value": "Orders above $1,000 require manager approval"}, "evidence": {"quote": "Remove the manager-approval rule for orders above $1,000."}}

Entry: 'Rename the activity "Ship order" to "Dispatch order".'
→ {"action": "modify", "target": "activity:a3", "payload": {"name": "Dispatch order"}, "evidence": {"quote": "Rename the activity \"Ship order\" to \"Dispatch order\"."}}
  (a3 is the [id] the specification shows for "Ship order")

Entry: 'make it better'
→ goes into "unresolved" verbatim.

Return ONLY a JSON object:
{"patches": [...], "trigger_ops": [...], "xref_ops": [...], "unresolved": [...], "note": "..."}

EDIT REQUEST SECTION (workflow "{{ workflow_slug }}"):
{{ edit_section }}

CURRENT SPECIFICATION:
{{ current_spec }}

PROJECT CONTEXT (all workflows + existing wiring):
{{ project_context }}

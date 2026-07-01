---
name: design_temporal
description: Design a Temporal workflow blueprint (declarations + typed plan IR) from the graph, facts, and CVPA classification.
variables: [workflow_graph, workflow_facts, cvpa_classification]
---
You are a Temporal solutions architect. Using the canonical workflow graph, the
extracted facts, and the CVPA classification, design a Temporal workflow
blueprint as ARCHITECTURE SPECIFICATIONS ONLY. Do NOT write executable Temporal
code, SDK calls, or language-specific snippets — describe the design with names,
typed parameters, bindings, and parameters only.

Ground every detail in the FACTS below. Do not invent retry counts, timeouts,
compensations, or inputs that the facts do not support.

Produce two layers — DECLARATIONS and a PLAN.

DECLARATIONS:
- workflow_name, a recommended task_queue, and a one-line description.
- workflow_inputs: the typed top-level inputs (from INPUT facts), each with a
  name and a Python type (str/int/float/bool).
- activities: derive from Process/activity facts and any node performing external
  work. Give each: name, source_node_id, description, typed `params` (from the
  activity's inputs/API fields), `outputs`, a `timeout_seconds` (from TIMER/SLA
  facts), and a `retry_policy` (from RETRY facts, incl. non_retryable_error_types
  from EXCEPTION facts).
- signals: model human/external waits (approvals, callbacks, compliance holds).
- queries: expose useful in-flight state; set `state_field` to the state attr.
- child_workflows: model subprocess nodes or cohesive sub-flows.
- timers: model durable waits / SLAs / deadlines (name + duration_seconds).
- compensation_activities: for each side-effecting activity that the COMPENSATION
  facts say must be undone, add one and set `compensates` to the EXACT activity
  name it reverses. Give each typed `params` for the values it needs to undo the
  effect (e.g. the id returned by the activity it reverses), and `bindings` — one
  per param — sourcing each value from "workflow_input" (ref = WorkflowInput
  field) or "step_output" (ref = the compensated activity's step id). A
  compensation that releases/reverses something MUST receive the id it acts on.
- default_retry_policy: a sensible workflow-wide default.

PLAN (the ordered control-and-data flow; this is what becomes runnable code):
- An ordered list of steps. Each step has a unique `id` and a `kind`:
  - "activity"/"child_workflow": set `ref` to the declared name, `result_name`
    for its output, and `bindings` — one per input param — describing where the
    value comes from: source "workflow_input" (ref = WorkflowInput field),
    "step_output" (ref = an earlier step id), or "constant".
  - "signal_gate": set `signal` (the signal to await) and `condition`. Place it
    where the workflow must pause (e.g. a compliance approval before provisioning).
  - "timer": set `timer` to a declared timer name for a *deliberate mid-workflow*
    durable sleep (e.g. a grace period before retrying). Do NOT add a timer step
    for an overall workflow timeout / total SLA — that is enforced by Temporal's
    execution timeout, not an in-workflow `sleep`, and would just stall the run.
  - "parallel": set `lanes` (a list of step-lists) to run concurrently.
  - "branch": set `predicate` and `lanes` ([then_steps, else_steps]) for
    conditional paths (e.g. eligibility/payment rejection).
- Order steps by true data dependencies: a step that consumes another's output
  must come after it.

Return only the requested structured data.

WORKFLOW GRAPH:
{{ workflow_graph }}

FACTS:
{{ workflow_facts }}

CVPA CLASSIFICATION:
{{ cvpa_classification }}

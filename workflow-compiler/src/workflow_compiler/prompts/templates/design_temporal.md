---
name: design_temporal
description: Design a Temporal workflow blueprint (declarations + typed plan IR) from the graph, facts, and CVPA classification.
variables: [workflow_graph, workflow_facts, cvpa_classification]
optional: [kg_context]
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
  Model a signal ONLY for an event the workflow **receives and waits on** (a
  SIGNAL node / "waits for" edge in the graph). NEVER model a signal for a value
  the workflow **produces** (an output the graph shows an activity "emits") — that
  is just the activity's return, not something to wait for. Waiting on your own
  output blocks the workflow forever.
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
    where the workflow must pause for an **inbound** signal it receives (a SIGNAL
    node / "waits for" edge in the graph, e.g. a carrier pickup confirmation). Set
    `timer` to the matching deadline timer so the wait is bounded. Do NOT add a
    signal_gate for an event the workflow emits/returns (an output) — that never
    arrives as a signal and the workflow would hang.
  - "timer": set `timer` to a declared timer name for a *deliberate mid-workflow*
    durable sleep (e.g. a grace period before retrying). Do NOT add a timer step
    for an overall workflow timeout / total SLA — that is enforced by Temporal's
    execution timeout, not an in-workflow `sleep`, and would just stall the run.
  - "parallel": set `lanes` (a list of step-lists) to run concurrently.
  - "branch": set `predicate` and `lanes` ([then_steps, else_steps]) for
    conditional paths (e.g. eligibility/payment rejection).
    - The `predicate` MUST be either a bare `result_name` declared by an earlier
      step (e.g. `is_settleable`) or `<result_name> == <literal>` — never an
      attribute path (`x.status`), never free prose. If no step result carries
      the decision's outcome, give the deciding activity a `result_name` first.
    - Lane polarity is fixed: the FIRST lane (`then`) is always the
      success/"yes" path; the SECOND lane (`else`) is the "no" path. Never
      phrase a predicate negatively to put failure handling in the then-lane.
  - "raise": terminate the workflow with a named error. Set `ref` to the
    EXACT exception name from the EXCEPTION facts (e.g. `PaymentDeclined`).
    Raising fires the registered compensations and fails the run.
- Every decision whose "no" path leads to an exception in the graph MUST have
  that branch's else-lane contain a "raise" step (optionally preceded by
  cleanup activities the facts call for). A rejection must never fall through
  to a normal completion.
- Order steps by true data dependencies: a step that consumes another's output
  must come after it.

Return only the requested structured data.

{{ kg_context }}WORKFLOW GRAPH:
{{ workflow_graph }}

FACTS:
{{ workflow_facts }}

CVPA CLASSIFICATION:
{{ cvpa_classification }}

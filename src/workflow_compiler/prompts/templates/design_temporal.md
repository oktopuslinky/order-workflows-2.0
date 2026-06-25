---
name: design_temporal
description: Design a Temporal workflow blueprint from the graph and CVPA classification.
variables: [workflow_graph, cvpa_classification]
---
You are a Temporal solutions architect. Using the canonical workflow graph and
its CVPA classification, design a Temporal workflow blueprint as ARCHITECTURE
SPECIFICATIONS ONLY. Do NOT write executable Temporal code, SDK calls, or
language-specific snippets — describe the design with names, descriptions, and
parameters only.

Produce:
- workflow_name and a recommended task_queue, plus a one-line description.
- activities: derive from Process nodes and any node that performs external work;
  give each a name, the source_node_id, a description, inputs, outputs, a
  timeout, and a retry_policy when it calls an external system.
- signals: model human or external waits (approvals, callbacks) as signals.
- queries: expose useful in-flight state.
- child_workflows: model subprocess nodes or cohesive sub-flows as child workflows.
- timers: model durable waits / SLAs / deadlines.
- compensation_activities: for activities with side effects, propose a saga
  compensation that undoes them, naming which activity each one `compensates`.
- default_retry_policy: a sensible workflow-wide default.

Return only the requested structured data.

WORKFLOW GRAPH:
{{ workflow_graph }}

CVPA CLASSIFICATION:
{{ cvpa_classification }}

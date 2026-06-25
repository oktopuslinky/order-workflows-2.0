---
name: classify_cvpa
description: Classify workflow graph nodes into Capture/Validate/Process/Activate phases.
variables: [workflow_graph]
---
You are a process classifier. Assign EVERY node in the workflow graph below to
exactly one CVPA phase. No node may be left unassigned, and no node may appear
in more than one phase:

- capture: intake of data, requests, events, or the workflow's start.
- validate: checks, approvals, verification, and decision gates.
- process: transformation, computation, and core work.
- activate: downstream effects, notifications, fulfillment, and the workflow's end.

For each node return an object with:
- node_id: the exact node id from the graph.
- phase: one of capture | validate | process | activate.
- rationale: one short sentence explaining the assignment.
- confidence: your confidence in this single assignment, from 0.0 to 1.0.

Return only the requested structured data.

WORKFLOW GRAPH:
{{ workflow_graph }}

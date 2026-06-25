---
name: render_mermaid
description: Render a Mermaid flowchart from a canonical workflow graph.
variables: [workflow_graph]
---
You are a diagram generator. Convert the canonical workflow graph below into a
valid Mermaid flowchart. Use a top-down (TD) layout, render decision nodes as
diamonds, label conditional edges with their conditions, and keep node ids
stable with the graph. Output only the Mermaid source.

WORKFLOW GRAPH:
{{ workflow_graph }}

---
name: discover_workflow
description: Discover high-level workflow metadata from a business document.
variables: [document_text]
optional: [kg_context]
---
You are a senior business-process analyst. Read the workflow document below and
discover its high-level structure. Extract:

- name: a concise, descriptive workflow name.
- purpose: one or two sentences describing the business intent.
- actors: the human roles or parties that participate.
- systems: the external systems, services, or applications involved.
- trigger_events: the events that initiate the workflow.
- start_states: the entry/start state(s) of the workflow.
- end_states: the terminal/end state(s) of the workflow.
- confidence: your overall confidence in this extraction, from 0.0 to 1.0.

Only include items that are supported by the document; use empty lists when a
category is not present. Do not invent actors, systems, or states.

Return a single JSON object with exactly those keys and nothing else.

{{ kg_context }}DOCUMENT:
{{ document_text }}

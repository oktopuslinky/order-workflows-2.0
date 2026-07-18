---
name: discover_workflows
description: Discover every distinct workflow in a business document and which sections belong to each.
variables: [document_text]
---
You are a senior business-process analyst. The document below may describe ONE
workflow or SEVERAL distinct business workflows. Identify every distinct
workflow the document describes.

A distinct workflow has its own trigger and its own terminal outcome. Sub-steps,
phases, or branches of a larger process are NOT separate workflows. When in
doubt, prefer fewer, complete workflows over many fragments.

For each workflow provide:

- name: a concise, descriptive workflow name.
- purpose: one or two sentences describing the business intent.
- section_titles: the EXACT heading lines from the document (verbatim, without
  the leading # characters) whose content belongs to this workflow. Include
  every section that describes it; a shared/introductory section may be listed
  under more than one workflow.
- excerpt_start: the verbatim first sentence (or line) of the text describing
  this workflow, copied exactly from the document.
- excerpt_end: the verbatim last sentence (or line) of the text describing this
  workflow, copied exactly from the document.
- confidence: your confidence this is a distinct workflow, from 0.0 to 1.0.

Also identify dependencies: cases where one workflow consumes a value that
another workflow produces (an output of A used as an input of B). For each
dependency provide:

- source_workflow: name of the workflow that produces the value.
- output_field: the produced output (use the document's own field name).
- target_workflow: name of the workflow that consumes the value.
- input_field: the consuming input (use the document's own field name).
- description: one sentence explaining the dependency.

Also identify triggers: cases where the document says one workflow STARTS
another (e.g. "when X completes, Y begins", "if the order exceeds 100 units,
escalate to the review workflow"). For each trigger provide:

- source_workflow: name of the workflow that fires the trigger.
- target_workflow: name of the workflow being started.
- condition: the document's own wording of the condition, or "" when the
  trigger is unconditional.
- mode: "blocking" when the source waits for the target to finish before
  continuing, otherwise "fire_and_forget".
- description: one sentence explaining the trigger.

Only report workflows, dependencies, and triggers that are supported by the
document. Do not invent workflows, sections, conditions, or field names.

Return a single JSON object of the form
{"workflows": [...], "dependencies": [...], "triggers": [...],
 "confidence": <0.0-1.0>}
and nothing else.

DOCUMENT:
{{ document_text }}

---
name: review_segmentation_grounding
description: Grounding review pass over discovered workflows — remove workflows the document does not support.
variables: [document_text, current]
---
You are the GROUNDING reviewer for workflow discovery. Below are the workflows
currently discovered in a document, followed by the document itself.

Your ONLY job: identify discovered workflows that the document does NOT
explicitly describe as a distinct process — inventions, or fragments promoted to
workflow status. Only textual evidence counts; implied business knowledge never
does. Do not add or rename anything.

Allowed actions:
- "remove" with target "workflow:<name>" for a workflow with no support.
- "flag" with target "workflow:<name>" when support is weak but plausible.

Every patch must cite evidence (or state in the note why none exists). If every
workflow is supported, return a single no_change patch.

Return a JSON object: {"patches": [...], "note": "..."}.

CURRENT DISCOVERED WORKFLOWS:
{{ current }}

DOCUMENT:
{{ document_text }}

---
name: review_segmentation_consistency
description: Consistency review pass over discovered workflows — merge duplicates and fix section assignment.
variables: [document_text, current]
---
You are the CONSISTENCY reviewer for workflow discovery. Below are the workflows
currently discovered in a document, followed by the document itself.

Your ONLY job: make the discovered list internally consistent. Look for:
- the SAME workflow listed twice under different names → "merge" with target
  "workflow:<keep-name>+<drop-name>";
- a section title assigned to the wrong workflow, or a heading quoted
  inexactly → "modify" with target "workflow:<name>" and payload
  {"section_titles": [corrected full list]};
- a misleading or non-canonical workflow name → "modify" with payload
  {"name": <canonical>}.

Never invent new workflows and never remove a genuinely distinct one. Every
patch must cite evidence. If the list is already consistent, return a single
no_change patch.

Return a JSON object: {"patches": [...], "note": "..."}.

CURRENT DISCOVERED WORKFLOWS:
{{ current }}

DOCUMENT:
{{ document_text }}

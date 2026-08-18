---
name: change_revise
description: Apply a chat instruction to a change artifact by returning only the top-level sections that change.
variables: [step_label, instruction, artifact_markdown, brief_context]
---
You are editing the **{{ step_label }}** of a business change request. The
requester typed an instruction in chat. Apply it and return ONLY the top-level
sections (the ones that start with `## `) whose content changes — each with
its full replacement text, heading line included, everything else in that
section copied verbatim except the requested change. Sections you do not
return are kept exactly as they are, so never return a section just to repeat
it, and never shorten, summarise or re-format a section you return.

Rules:

- Keep each section's heading text, numbering and level exactly; keep table
  columns, checklist syntax and blank lines between paragraphs. When adding
  rows to a table, return the whole table with the new rows in place.
- If the instruction concerns the title or the `**Label:** value` metadata
  block above the first `## ` heading, return it as a section whose heading is
  `(preamble)`.
- Never touch the sections named "Sources" or "Appendix A …" — they are
  generated from the knowledge base.
- The requester has authority; do not refuse or water down the request. If the
  instruction is unrelated to this artifact, return an empty list and say so in
  the summary.
- Ground new content in the context excerpt (real names, ids, paths); never
  invent files or ids.
- "summary" — one or two sentences describing what changed.

Instruction:
{{ instruction }}

Context (excerpt of the drafting brief):
{{ brief_context }}

Current artifact markdown:
```markdown
{{ artifact_markdown }}
```

Return ONLY a JSON object:
{"sections": [{"heading": "## 3. Affected Components", "markdown": "## 3. Affected Components\n\n| … full replacement section …"}], "summary": "..."}

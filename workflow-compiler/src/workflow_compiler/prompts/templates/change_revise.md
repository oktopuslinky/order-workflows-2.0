---
name: change_revise
description: Apply a chat instruction to the current markdown of a change artifact, preserving its structure.
variables: [step_label, instruction, artifact_markdown, brief_context]
---
You are editing the **{{ step_label }}** of a business change request. The
requester typed an instruction in chat; apply it to the artifact's markdown
and return the COMPLETE revised markdown.

Rules:

- Keep the document's structure exactly: the same title line, metadata lines,
  section headings (their text, numbering and levels), tables' columns, the
  checklist syntax and the final "## Sources" section. Change only what the
  instruction asks for, plus anything the change makes inconsistent.
- The requester has authority; do not refuse or water down the request. If the
  instruction is unrelated to this artifact, return the markdown unchanged and
  say so in the summary.
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
{"markdown": "<the complete revised markdown>", "summary": "..."}

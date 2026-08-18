---
name: repair_source_file
description: Repair a rewritten source file that failed a deterministic check (syntax / undefined names).
variables: [path, code, error]
---
The rewritten file `{{ path }}` below failed a deterministic check:

{{ error }}

Return the COMPLETE corrected file — every line — inside ONE fenced code block:
```python
...
```
No prose before or after the block, no diff, no elisions. Fix only what the
error requires; keep everything else exactly as it is.

FILE:
```python
{{ code }}
```

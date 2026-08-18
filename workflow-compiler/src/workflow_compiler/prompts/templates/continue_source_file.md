---
name: continue_source_file
description: Ask the model to continue a source-file answer that was cut off before the closing fence.
variables: [path, tail]
---
Your previous answer for `{{ path }}` was cut off before the closing fence.
Continue the file from EXACTLY where it stopped. The last lines received were:

```python
{{ tail }}
```

Return ONLY the remaining lines of the file (start with the line that follows
the last line above; do not repeat earlier lines), inside ONE fenced code
block that ends with a closing fence:
```python
...
```

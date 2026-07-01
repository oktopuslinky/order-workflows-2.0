---
name: polish_activities
description: Rewrite each activity into one natural, grounded sentence.
variables: [activities, document_text]
---
You are a precise technical writer. Below is a list of activity names from a single
workflow and the source document they came from. For EACH activity, write ONE short,
natural sentence describing what that activity does — the kind of sentence a human
would write in a specification (e.g. "The Settlement Service validates the order using
`order_id` and returns whether it is settleable.").

Rules:
- Use ONLY information stated in the document. Do NOT invent systems, fields, or
  behavior that the document does not support.
- Do not add steps, decisions, or error handling — describe the single activity only.
- Keep it to one sentence. Do not restate the activity name as a heading.
- If the document says little about an activity, write a minimal faithful sentence.

Return a single JSON object of the form:
{"activities": [{"name": "<exact activity name>", "description": "<one sentence>"}, ...]}

ACTIVITIES:
{{ activities }}

DOCUMENT:
{{ document_text }}

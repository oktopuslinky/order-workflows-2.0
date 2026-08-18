---
name: change_impact_coverage
description: Second pass of the impact analysis — classify traversal candidates the first draft did not mention.
variables: [brief, affected_block, candidates_block]
---
You are completing the **Affected Components** table of an impact analysis. A
first pass already produced the rows listed under CURRENT ROWS. The
deterministic knowledge-graph traversal also reached the CANDIDATES below,
which the first pass did not mention. For EACH candidate decide, from the
DRAFTING BRIEF (the change request, the excerpts of the existing documents,
code and tests, and the requester's decisions), whether the change request
affects it:

- `modify` — its content/behaviour/steps/expected result must change (e.g. a
  test case whose expected order status becomes PARTIALLY_DISPATCHED, a user
  story whose acceptance criteria change, a diagram, the test plan's
  out-of-scope line, the existing epic's definition-of-done item);
- `verify` — it must be re-run or re-read to confirm it still holds (e.g. a
  regression test case around the changed stages, a story adjacent to them);
- `add` — a new companion artifact is needed next to it;
- omit the candidate entirely when the change does not touch it.

Give a concrete one-line `rationale` per included candidate that names what
changes (state, activity, section, expected result). Use each candidate's `ref`
and `kg_ref` verbatim; `kind` is one of module | function | class | type |
document | story | test_case | test_plan | epic | diagram | requirement | other.
Include every test case and user story that the change request's requirements
touch (splitting at provisioning, per-group dispatch, PARTIALLY_* statuses,
per-group cancellation/compensation, consolidated completion, per-group status
query). Do not repeat CURRENT ROWS.

Return ONLY a JSON object:
{"affected": [{"kind": "...", "ref": "...", "change_type": "modify|verify|add", "rationale": "...", "kg_ref": "..."}]}

## Current rows

{{ affected_block }}

## Candidates

{{ candidates_block }}

## Drafting brief

{{ brief }}

# Workflow Edit Request Format Guide

This guide defines the structure and writing style for **edit request documents** —
the input to `workflow-compiler edit` (and `POST /projects/{id}/edit`). An edit
request changes workflows that were already compiled into a project: the edits are
applied to the structured `WorkflowSpec`s (the source of truth), the project
returns to the spec gate, and the normal `validate` → `approve-spec` flow
regenerates the graph, CVPA, Temporal design, and code.

How it is processed:

1. The **section skeleton** below is parsed deterministically. Structural problems
   (unknown slug, unknown block, duplicate sections, …) fail immediately — before
   any model call — with an actionable error.
2. The natural-language **bullet entries** inside each block are translated by an
   LLM into minimal deterministic patch operations against the current spec.
3. A deterministic applier applies them with **human authority**: your additions
   need no support in the original document (they are marked `[human]`), and your
   removals are honored. An entry the model cannot map aborts the whole edit —
   **edit requests are atomic**; nothing is applied unless everything applies.
4. Every applied edit is recorded in the project's append-only **edit log**, and
   each edited workflow's `Version` is bumped (`0.1.0` → `0.1.1`).

---

## Quick reference: section → what it drives

| Section | Effect |
|---|---|
| `# Edit Request` (H1) | Required document marker |
| `## Workflow: <slug>` | Per-workflow changes (one section per workflow) |
| `### Add` / `### Modify` / `### Remove` | Content changes to that workflow's spec |
| `### Triggers` | Cross-workflow triggers this edit adds/changes/removes |
| `### Dependencies` | Output→input links between workflows |
| `## Add Workflow: <slug>` | Create a whole new workflow from the section body |
| `## Remove Workflow: <slug>` | Delete a workflow (and every wire touching it) |
| `## Project` | Project-level wiring changes (triggers/dependencies only) |
| `## Reason` | Recorded verbatim in the edit log (recommended) |

`<slug>` is the workflow's file name from your spec directory (e.g.
`order-fulfillment-workflow` for `order-fulfillment-workflow.md`). Unknown slugs
are rejected with the list of valid ones.

---

## Document template

```
# Edit Request

## Workflow: <slug>

### Add
- ...

### Modify
- ...

### Remove
- ...

### Triggers            [optional]
- ...

### Dependencies        [optional]
- ...

## Add Workflow: <new-slug>          [optional]

<a full workflow description — use docs/DOCUMENT_FORMAT_GUIDE.md's format,
including its own ## Purpose / ## Process sections>

## Remove Workflow: <slug>           [optional]

## Reason

<why this change is being made>
```

A workflow may not be both edited (`## Workflow:`) and removed
(`## Remove Workflow:`) in the same request. A request with no actionable
entries is rejected.

---

## Section-by-section guidance

### `### Add`

One change per bullet. Name the element kind (activity, rule, timer, retry,
exception, compensation, event, input, output, actor, system) and be specific —
the entry becomes a real spec element verbatim.

```markdown
### Add

- After "Release inventory", the system **notifies the warehouse team** via the
  Notification Service.
- A business rule: refunds over $500 require manager approval.
- A timer: fraud screening must complete within 30 seconds.
```

### `### Modify`

Identify the element exactly as the spec renders it (copy the label or statement
from the spec file — or cite its `[id]`, e.g. `[a3]`), then state the change.

```markdown
### Modify

- "Deprovision service" retry count changes from 3 to 5.
- Rename the activity "Ship order" [a3] to "Dispatch order".
- The workflow owner is the Fulfillment Operations Team.
```

### `### Remove`

State what goes away and, when helpful, why. Removing an element other elements
reference (a decision branch target, a compensated activity) is allowed — the
dangling references are pruned automatically and reported as a warning.

```markdown
### Remove

- The manager-approval rule for orders above $1,000 (policy retired).
- The exception OrderInvalid.
```

### `### Triggers` and `### Dependencies`

Cross-workflow wiring. Name both workflows by slug; for triggers state the mode
(blocking / fire-and-forget) and condition when relevant. Wiring added by an edit
request is marked user-confirmed — no checkbox round-trip needed.

```markdown
### Triggers

- When the record is created, this workflow starts account-provisioning
  (fire-and-forget).
- Remove the trigger to legacy-billing.

### Dependencies

- account-provisioning also consumes this workflow's plan_code output as its
  plan_code input.
```

### `## Add Workflow: <slug>`

The body is a complete workflow description — write it exactly like a source
document (`docs/DOCUMENT_FORMAT_GUIDE.md`), with its own `## Purpose`,
`## Process`, etc. It runs through the same discovery + fact-extraction pipeline
as an original document section.

### `## Remove Workflow: <slug>`

No body needed. The workflow's spec and segment are deleted, and every trigger or
dependency touching it is dropped (each drop is listed in the edit summary).

---

## Writing style rules

The interpreter maps your prose onto exact spec elements, so precision pays.

| Do | Avoid |
|---|---|
| "'Deprovision service' retry count changes from 3 to 5" | "retry more" |
| "Remove the manager-approval rule for orders above $1,000" | "drop that approval thing" |
| "Rename the activity 'Ship order' [a3] to 'Dispatch order'" | "fix the shipping step name" |
| One change per bullet | Bundling several changes in one bullet |
| Copy labels/statements exactly as the spec file shows them | Paraphrasing from memory |
| Describe the **change** ("X changes from A to B") | Describing only the desired end state |

An entry the interpreter cannot map is reported back verbatim and the whole edit
is rejected — rephrase it and re-run; nothing was applied.

---

## Reserved syntax (not yet supported)

The following headings are recognized and **rejected with an explicit error**;
they are reserved for a future release so edit documents keep their shape:

```
## Split Workflow: <slug>
## Merge Workflows: <slug-a> + <slug-b>
```

Until then, model a split/merge as `## Add Workflow:` + `## Remove Workflow:`
sections plus explicit `### Triggers` / `### Dependencies` rewiring.

---

## Minimal valid example

```markdown
# Edit Request

## Workflow: order-fulfillment-workflow

### Modify

- Shipment creation retries change from 3 attempts to 5 attempts.

## Reason

Carrier API flakiness (OPS-142).
```

A fuller working example lives at `examples/order_edit_request.md`.

---

## Checklist before submitting an edit request

- [ ] H1 is exactly `# Edit Request`
- [ ] Every `## Workflow:` slug matches a spec file in your spec directory
- [ ] One change per bullet, each naming its element kind
- [ ] Modify/Remove entries quote the element as the spec renders it
- [ ] New workflows have a full document-format body
- [ ] No workflow is both edited and removed
- [ ] `## Reason` says why (it goes in the audit log)
- [ ] After applying: review the re-written spec files, then `validate` → `approve-spec`

# Workflow Specification Project

- project id: `3a760d6c-8132-4109-98ba-0ff679aadc02`
- stage: needs_attention
- spec approval: approved

## Workflows
- `order-settlement-workflow.md` — Order Settlement Workflow

## Cross-Workflow Dependencies
- none

## Latest Validation Findings
### order-settlement-workflow
- [INFO] Ingest: modified activity a4
- [INFO] Ingest: modified exception e1
- [INFO] Ingest: modified event ev1
- [INFO] Ingest: modified event ev2
- [WARN] Ingest: activity a4 is gated by a decision — removed from parallel group.
- [BLOCK] Graph review: graph health 0.85 below threshold 0.90 — left pending for manual review (review and approve the graph manually)

## How to proceed

1. Review and edit each workflow's `<slug>.md` file.
2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).
3. Confirm the cross-workflow dependencies (tick their boxes).
4. Run `workflow-compiler validate <project-id>` to check your edits.
5. Run `workflow-compiler approve-spec <project-id>` to generate the graphs, Temporal designs, and code.

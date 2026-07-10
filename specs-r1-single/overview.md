# Workflow Specification Project

- project id: `7be58732-6bc7-40a6-8cef-c758f65d14bc`
- stage: completed
- spec approval: approved

## Workflows
- `order-settlement-workflow.md` — Order Settlement Workflow

## Cross-Workflow Dependencies
- none

## Latest Validation Findings
### order-settlement-workflow
- [INFO] Ingest: modified decision d1
- [INFO] Ingest: modified decision d2
- [INFO] Ingest: modified exception e1
- [INFO] Ingest: modified exception e2
- [INFO] Ingest: answered open question 'For each flagged decision, what happens on the 'no' branch (name the exception or next step)?'

## How to proceed

1. Review and edit each workflow's `<slug>.md` file.
2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).
3. Confirm the cross-workflow dependencies (tick their boxes).
4. Run `workflow-compiler validate <project-id>` to check your edits.
5. Run `workflow-compiler approve-spec <project-id>` to generate the graphs, Temporal designs, and code.

# Workflow Specification Project

- project id: `fe24cff8-619f-4978-a4f7-73d237e5a730`
- stage: completed
- spec approval: approved

## Workflows
- `order-placement.md` — Order Placement Workflow
- `order-fulfilment.md` — Order Fulfilment
- `order-return.md` — Order Return Workflow

## Cross-Workflow Dependencies
- order-placement.`order_id` → order-fulfilment.`order_id` (confirmed)
- order-placement.`order_id` → order-return.`order_id` (confirmed)
- order-fulfilment.`shipment_id` → order-return.`shipment_id` (confirmed)

## Latest Validation Findings
### order-placement
- [INFO] Ingest: modified decision d1
- [INFO] Ingest: modified decision d2
### order-fulfilment
- none
### order-return
- none

## How to proceed

1. Review and edit each workflow's `<slug>.md` file.
2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).
3. Confirm the cross-workflow dependencies (tick their boxes).
4. Run `workflow-compiler validate <project-id>` to check your edits.
5. Run `workflow-compiler approve-spec <project-id>` to generate the graphs, Temporal designs, and code.

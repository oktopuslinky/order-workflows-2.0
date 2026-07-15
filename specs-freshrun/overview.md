# Workflow Specification Project

- project id: `12ef7be1-db95-43ed-a7f2-d3bf74003bbe`
- stage: spec_drafted
- spec approval: pending

## Workflows
- `order-placement.md` — Order Placement Workflow
- `order-fulfilment.md` — Order Fulfilment — 1 open question(s)
- `order-return.md` — Order Return Workflow

## Cross-Workflow Dependencies
- order-placement.`order_id` → order-fulfilment.`order_id` (UNCONFIRMED)
- order-placement.`order_id` → order-return.`order_id` (UNCONFIRMED)
- order-fulfilment.`shipment_id` → order-return.`shipment_id` (UNCONFIRMED)

## How to proceed

1. Review and edit each workflow's `<slug>.md` file.
2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).
3. Confirm the cross-workflow dependencies (tick their boxes).
4. Run `workflow-compiler validate <project-id>` to check your edits.
5. Run `workflow-compiler approve-spec <project-id>` to generate the graphs, Temporal designs, and code.

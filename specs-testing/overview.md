# Workflow Specification Project

- project id: `b2a1637b-9006-40a9-96e7-e2fedd58df02`
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
- none
### order-fulfilment
- grounding: actors: Warehouse Operator is marked as [human] in the specification but not explicitly listed in the source document's Order Fulfilment Actors section
- grounding: systems: Carrier Service is mentioned in the specification but its explicit involvement in the Order Fulfilment workflow's process is only implied through API Interfaces, not directly stated in the source document's 'Order Fulfilment Process' section
### order-return
- none

## How to proceed

1. Review and edit each workflow's `<slug>.md` file.
2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).
3. Confirm the cross-workflow dependencies (tick their boxes).
4. Run `workflow-compiler validate <project-id>` to check your edits.
5. Run `workflow-compiler approve-spec <project-id>` to generate the graphs, Temporal designs, and code.

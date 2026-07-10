# Workflow Specification Project

- project id: `a7c40df8-7870-4988-ab20-1973c72e5bee`
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
- [INFO] Ingest: removed activity a5 'Release Inventory Reservation'
- [INFO] Ingest: modified decision d1
- [INFO] Ingest: modified decision d2
- [INFO] Ingest: modified exception e1
- [INFO] Ingest: modified exception e2
- [INFO] Ingest: removed event ev4 'placement_status'
- [INFO] Ingest: answered open question 'For each flagged decision, what happens on the 'no' branch (name the exception or next step)?'
- [INFO] Ingest: confirmed dependency order-placement.order_id -> order-fulfilment.order_id
- [INFO] Ingest: confirmed dependency order-placement.order_id -> order-return.order_id
- [INFO] Ingest: updated triggers for order-placement (1 trigger(s))
### order-fulfilment
- [INFO] Ingest: confirmed dependency order-fulfilment.shipment_id -> order-return.shipment_id
- [INFO] Ingest: updated triggers for order-fulfilment (0 trigger(s))
### order-return
- [INFO] Ingest: modified exception e1

## How to proceed

1. Review and edit each workflow's `<slug>.md` file.
2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).
3. Confirm the cross-workflow dependencies (tick their boxes).
4. Run `workflow-compiler validate <project-id>` to check your edits.
5. Run `workflow-compiler approve-spec <project-id>` to generate the graphs, Temporal designs, and code.

# Workflow Specification Project

- project id: `44a7f79a-4bf6-4c4a-9997-0c5ea5d0a55a`
- stage: needs_attention
- spec approval: approved

## Workflows
- `order-placement.md` — Order Management Operations
- `order-fulfilment.md` — Order Management Operations
- `order-return.md` — Order Return Workflow — 1 open question(s)

## Cross-Workflow Dependencies
- order-placement.`orderid` → order-fulfilment.`orderid` (confirmed)
- order-placement.`orderid` → order-return.`orderid` (confirmed)
- order-fulfilment.`shipmentid` → order-return.`shipmentid` (confirmed)

## Warnings
- Could not locate document sections for workflow 'Order Placement' — using the full document as its segment.
- Could not locate document sections for workflow 'Order Fulfilment' — using the full document as its segment.

## Latest Validation Findings
### order-placement
- ingest: added event v1 '[ev1] checkout.submitted' (document_grounded)
- ingest: added event v2 '[ev2] order.fulfil' (document_grounded)
- ingest: added event v3 '[ev3] return.requested' (document_grounded)
- ingest: added event v4 '[ev4] carrier.picked_up' (document_grounded)
- ingest: removed event ev1 'checkout.submitted'
- ingest: removed event ev2 'order.fulfil'
- ingest: removed event ev3 'return.requested'
- ingest: removed event ev4 'carrier.picked_up'
### order-fulfilment
- ingest: added event v1 '[ev1] checkout.submitted' (document_grounded)
- ingest: added event v2 '[ev2] order.fulfil' (document_grounded)
- ingest: added event v3 '[ev3] return.requested' (document_grounded)
- ingest: added event v4 '[ev4] carrier.picked_up' (document_grounded)
- ingest: removed event ev1 'checkout.submitted'
- ingest: removed event ev2 'order.fulfil'
- ingest: removed event ev3 'return.requested'
- ingest: removed event ev4 'carrier.picked_up'
- grounding: actors: The source document lists 'Shopper', 'Order Operations', 'Warehouse Operator', 'Fulfillment Operations', 'Returns Operations', and 'Customer' as actors across the three workflows, but the specification aggregates them without explicit source backing for the combined list
- grounding: systems: Similar to actors, the systems are aggregated from the three workflows without a single source section explicitly listing all together
### order-return
- ingest: added event v1 '[ev1] return.requested' (document_grounded)
- ingest: removed event ev1 'return.requested'
- blocked: unmet required checklist items ['R5-compensations'] — answer the open questions in the spec file or approve with accept_incomplete

## How to proceed

1. Review and edit each workflow's `<slug>.md` file.
2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).
3. Confirm the cross-workflow dependencies (tick their boxes).
4. Run `workflow-compiler validate <project-id>` to check your edits.
5. Run `workflow-compiler approve-spec <project-id>` to generate the graphs, Temporal designs, and code.

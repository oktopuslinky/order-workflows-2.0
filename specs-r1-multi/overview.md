# Workflow Specification Project

- project id: `8aab0051-1a78-4829-973c-c230ad94b2fb`
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
- [INFO] Ingest: added activity a4 'Create Order' (document_grounded)
- [INFO] Ingest: modified decision d2
- [WARN] grounding: actors: Shopper is explicitly mentioned in the source document (Order Placement Actors), but 'Order Operations' lacks clear evidence of its role in the workflow beyond being listed
- [WARN] grounding: systems: Catalogue Service is listed but its integration or purpose in the Order Placement workflow is not described in the source document
- [WARN] grounding: 'activity:a4' is referenced by other elements — removal skipped; if it is truly unsupported, remove the referencing lines first
- [WARN] grounding: compensations: Release Inventory Reservation is correctly tied to compensating 'Reserve Inventory', but the trigger condition (exactly when it compensates) could be more clearly defined in the source document
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

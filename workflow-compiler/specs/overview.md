# Workflow Specification Project

- project id: `8356bd4b-cea9-49b8-bf55-a87999b9675e`
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
- [WARN] grounding: events:v1: Lack of explicit evidence in the source document for the 'checkout.submitted' event's emission by the start of the workflow
- [WARN] grounding: events:v3: The 'authorization_id' event is marked as [human] but lacks explicit support in the source document for its emission by 'a3
### order-fulfilment
- [WARN] grounding: events:v3: Human-provided event without explicit source document evidence
- [WARN] grounding: events:v4: Human-provided event without explicit source document evidence
### order-return
- none

## How to proceed

1. Review and edit each workflow's `<slug>.md` file.
2. Answer the Open Questions (fill the `Answer:` lines, tick the boxes).
3. Confirm the cross-workflow dependencies (tick their boxes).
4. Run `workflow-compiler validate <project-id>` to check your edits.
5. Run `workflow-compiler approve-spec <project-id>` to generate the graphs, Temporal designs, and code.

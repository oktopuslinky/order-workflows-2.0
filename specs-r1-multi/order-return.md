# Order Return Workflow

<!--
  workflow-compiler specification (v1) — slug: order-return
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
Processes a customer's return for a shipped order, including authorisation, receiving the item, and refunding the payment. Ensures failed refunds are escalated.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Customer, Returns Operations
- systems: Returns Service, Warehouse Service, Payment Gateway
- triggers: Customer requests a return and return.requested reaches Returns Service
- start states: shipped
- end states: Rejected (ReturnNotEligible), Refunded, Escalated (RefundFailed)
- tags: 

## Inputs
- order_id
- shipment_id
- reason_code

## Outputs
- return_id
- refund_id
- return_status

## Business Rules
- BR-1: A return may only be authorised for an order in the shipped state
- BR-2: The returned item must be received before the refund is issued
- BR-3: A refund may not exceed the captured payment amount

## API Interfaces
- Returns Service: POST /returns/authorize
- Warehouse Service: POST /warehouse/receive
- Payment Gateway: POST /payments/refund

## Systems Involved
- Returns Service
- Warehouse Service
- Payment Gateway

## Timers and SLAs
- Authorise the return must complete within 10 seconds
- Issue the refund must complete within 30 seconds

## Retries
- Receive the returned item: retry up to 3 times with exponential backoff starting at 2 seconds
- Issue the refund: retry up to 5 times with exponential backoff starting at 1 second

## Activities
- [a1] Authorise return
- [a2] Receive returned item
- [a3] Issue refund

## Decisions
- [d1] Is return eligible? — after: a1; yes: a2; no: e1

## Exceptions
- [e1] ReturnNotEligible
- [e2] RefundFailed — raised by: a3

## Compensations
<!-- none -->

## Events
- [ev1] return.requested — kind: trigger; emitted by: start
- [ev2] return_id — kind: output_emit; emitted by: a2
- [ev3] refund_id — kind: output_emit; emitted by: a3

## State Transitions
<!-- none -->

## Assumptions
<!-- none -->

## Ambiguities
<!-- none -->

## Suggested Edits
<!-- none -->

## Open Questions
<!-- none -->

## Cross-Workflow Dependencies
- [x] uses output `order_id` of `order-placement` as input `order_id` — Order Return requires the order_id from Order Placement to process the return
- [x] uses output `shipment_id` of `order-fulfilment` as input `shipment_id` — Order Return requires the shipment_id from Order Fulfilment to complete the return process

## Triggers
<!-- none -->

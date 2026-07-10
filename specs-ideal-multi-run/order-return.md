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
- triggers: Customer requests a return and a return.requested request reaches the Returns Service
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
- BR-1: Return authorised only for shipped orders
- BR-2: Item received before refund issued
- BR-3: Refund not exceeding captured payment

## API Interfaces
- Returns Service /returns/authorize
- Warehouse Service /warehouse/receive
- Payment Gateway /payments/refund

## Systems Involved
- Returns Service
- Warehouse Service
- Payment Gateway

## Timers and SLAs
- Authorise return: 10 seconds
- Issue refund: 30 seconds

## Retries
- Receive returned item: up to 3 times with exponential backoff (2s start)
- Issue refund: up to 5 times with exponential backoff (1s start)

## Activities
- [a1] Authorise Return
- [a2] Receive Returned Item
- [a3] Issue Refund

## Decisions
- [d1] Is Return Eligible? — after: a1; yes: a2; no: e1

## Exceptions
- [e1] ReturnNotEligible — raised by: a1
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

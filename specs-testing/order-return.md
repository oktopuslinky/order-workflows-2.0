# Order Return Workflow

<!--
  workflow-compiler specification (v1) — slug: order-return
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
Processes a customer's return for a shipped order, including authorisation, receiving the item, and refunding the customer.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Customer, Returns Operations
- systems: Returns Service, Warehouse Service, Payment Gateway
- triggers: customer requests a return (return.requested)
- start states: shipped
- end states: return_status: refunded, return_status: rejected
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
- BR-2: Item received before refund
- BR-3: Refund ≤ captured payment

## API Interfaces
- Returns Service: POST /returns/authorize
- Warehouse Service: POST /warehouse/receive
- Payment Gateway: POST /payments/refund

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
- [a1] Authorise return
- [a2] Receive returned item
- [a3] Issue refund

## Decisions
- [d1] Is return eligible? — after: a1; yes: a2; no: e1

## Exceptions
- [e1] ReturnNotEligible
- [e2] RefundFailed — raised by: a3

## Compensations
- [c1] Cancel Return Process — compensates: a3

## Events
- [v1] [ev1] return.requested — emitted by: start

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
- [x] uses output `order_id` of `order-placement` as input `order_id` — Order Return consumes the order_id produced by Order Placement
- [x] uses output `shipment_id` of `order-fulfilment` as input `shipment_id` — Order Return consumes the shipment_id produced by Order Fulfilment

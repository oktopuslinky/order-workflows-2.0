# Order Return Workflow

<!--
  workflow-compiler specification (v1) — slug: order-return
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
The Order Return workflow processes a customer's return for a shipped order, authorising the return, receiving the item back into the warehouse, and refunding the customer.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Customer, Returns Operations
- systems: Returns Service, Warehouse Service, Payment Gateway
- triggers: customer requests a return and a return.requested request reaches the Returns Service
- start states: shipped
- end states: refund issued (refunded), return rejected (rejected), return escalated to Returns Operations (RefundFailed)
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
- BR-3: Refund not exceeding captured payment

## API Interfaces
- Returns Service /returns/authorize (POST)
- Warehouse Service /warehouse/receive (POST)
- Payment Gateway /payments/refund (POST)

## Systems Involved
- Returns Service
- Warehouse Service
- Payment Gateway

## Timers and SLAs
- Authorise return: 10 seconds
- Issue refund: 30 seconds

## Retries
- Receive returned item: up to 3 times with exponential backoff (start 2s)
- Issue refund: up to 5 times with exponential backoff (start 1s)
- Authorise return: up to 2 times with linear backoff (start 5s)

## Activities
- [a1] Authorise return
- [a2] Receive returned item
- [a3] Issue refund

## Decisions
- [d1] Is return eligible? — after: a1; yes: a2; no: rejected

## Exceptions
- [e1] ReturnNotEligible — raised by: a1
- [e2] RefundFailed — raised by: a3

## Compensations
- [c1] Cancel Return Process

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
- [ ] (R5-compensations) Which activity does each flagged compensation reverse (use the exact activity name)?
  Answer: 

## Cross-Workflow Dependencies
- [ ] uses output `order_id` of `order-placement` as input `order_id` — Order Return consumes the order_id produced by Order Placement
- [ ] uses output `shipment_id` of `order-fulfilment` as input `shipment_id` — Order Return consumes the shipment_id produced by Order Fulfilment

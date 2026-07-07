# Order Return Workflow

<!--
  workflow-compiler specification (v1) — slug: order-return
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
Processes a customer's return for a shipped order, including authorisation, receiving the item back, and refunding the payment.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Customer, Returns Operations
- systems: Returns Service, Warehouse Service, Payment Gateway
- triggers: Customer requests a return (return.requested reaches Returns Service)
- start states: shipped
- end states: Refund issued (refunded), Return rejected (rejected), Return escalated to Returns Operations (RefundFailed)
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
- BR-1: Return authorised only for orders in shipped state
- BR-2: Returned item must be received before refund
- BR-3: Refund cannot exceed captured payment amount

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
- Receive Returned Item: retry up to 3 times with exponential backoff starting at 2 seconds
- Issue the refund: retry up to 5 times with exponential backoff starting at 1 second

## Activities
- [a1] Authorise Return
- [a2] Receive Returned Item
- [a3] Issue Refund
- [a4] Escalate to Returns Operations

## Decisions
- [d1] Is Return Eligible? — after: a1; yes: a2; no: e1
- [d2] Is Refund Successful? — after: a3; yes: end; no: e2

## Exceptions
- [e1] ReturnNotEligible
- [e2] RefundFailed

## Compensations
- [c1] Manual Handling by Returns Operations

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
- [x] (R8-retries) Which activities should retry, how many times, and with what backoff?
  Answer: i am not sure, please

## Cross-Workflow Dependencies
- [x] uses output `orderid` of `order-placement` as input `orderid` — Order Return consumes the order_id produced by Order Placement
- [x] uses output `shipmentid` of `order-fulfilment` as input `shipmentid` — Order Return consumes the shipment_id produced by Order Fulfilment

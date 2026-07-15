# Order Placement Workflow

<!--
  workflow-compiler specification (v1) — slug: order-placement
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
The Order Placement workflow turns a submitted shopping cart into a confirmed order by validating the cart, reserving inventory, authorizing payment, and creating the order record.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Shopper, Order Operations
- systems: Order Service, Catalogue Service, Inventory Service, Payment Gateway
- triggers: checkout.submitted request received by Order Service, cart submitted for checkout
- start states: cart in open state
- end states: order placed (placed), order rejected (rejected)
- tags: 

## Inputs
- cart_id
- customer_id
- amount
- currency

## Outputs
- order_id
- authorization_id
- placement_status

## Business Rules
<!-- none -->

## API Interfaces
- Order Service: POST /orders/validate-cart
- Inventory Service: POST /inventory/reserve
- Payment Gateway: POST /payments/authorize
- Order Service: POST /orders/create

## Systems Involved
- Order Service
- Catalogue Service
- Inventory Service
- Payment Gateway

## Timers and SLAs
- Validate cart must complete within 5 seconds
- Authorise payment must complete within 30 seconds

## Retries
- Reserve inventory: retry up to 3 times with exponential backoff starting at 2 seconds
- Authorise payment: retry up to 2 times with a fixed 5-second delay; do not retry on a PaymentDeclined error

## Activities
- [a1] Validate cart
- [a2] Reserve inventory
- [a3] Authorise payment
- [a4] Create the order

## Decisions
- [d1] Is cart eligible? — after: a1; yes: a2; no: e1
- [d2] Is payment authorised? — after: a3; yes: a4; no: e2

## Exceptions
- [e1] CartNotEligible
- [e2] PaymentDeclined

## Compensations
- [c1] Release inventory — compensates: a2

## Events
- [ev1] checkout.submitted — kind: trigger; emitted by: start

## State Transitions
<!-- none -->

## Assumptions
<!-- none -->

## Ambiguities
<!-- none -->

## Suggested Edits
<!-- none -->

## Open Questions
- [x] (R4-decisions) For each flagged decision, what happens on the 'no' branch (name the exception or next step)?
  Answer: On decline, raise PaymentDeclined and cancel the order

## Cross-Workflow Dependencies
- [x] provides output `order_id` to `order-fulfilment` input `order_id` — Order Fulfilment consumes the order_id produced by Order Placement
- [x] provides output `order_id` to `order-return` input `order_id` — Order Return consumes the order_id produced by Order Placement

## Triggers
- [x] triggers `order-fulfilment` (fire-and-forget) when `when an order is placed`
  input order_id: step output `order_id` (str)
- [x] triggers `order-return` (fire-and-forget)
  input order_id: step output `order_id` (str)

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
- systems: Order Service, Inventory Service, Payment Gateway
- triggers: checkout.submitted request received by Order Service
- start states: cart submitted and checkout-eligible
- end states: order placed (placed), order rejected (rejected), inventory reservation released (payment declined)
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
- BR-1: Cart must be in open state for placement
- BR-2: Inventory must be reserved before payment authorisation
- BR-3: Payment must be authorised before order creation

## API Interfaces
- Order Service /orders/validate-cart
- Inventory Service /inventory/reserve
- Payment Gateway /payments/authorize
- Order Service /orders/create

## Systems Involved
- Order Service
- Catalogue Service
- Inventory Service
- Payment Gateway

## Timers and SLAs
- Validate cart: < 5 seconds
- Authorise payment: < 30 seconds

## Retries
- Reserve inventory: up to 3 times with exponential backoff (start 2 seconds)
- Authorise payment: up to 2 times with 5-second delay (exclude PaymentDeclined)

## Activities
- [a1] Validate Cart
- [a2] Reserve Inventory
- [a3] Authorise Payment
- [a4] Create Order

## Decisions
- [d1] Is Cart Eligible? — after: a1; yes: a2; no: rejected
- [d2] Is Payment Authorised? — after: a3; yes: a4; no: e2

## Exceptions
- [e1] CartNotEligible
- [e2] PaymentDeclined — raised by: a3

## Compensations
- [c1] Release Inventory — compensates: a2

## Events
- [ev1] checkout.submitted — kind: trigger; emitted by: start
- [ev2] order_id — kind: output_emit; emitted by: a4
- [ev3] authorization_id — kind: output_emit; emitted by: a3

## State Transitions
- start -> validating (trigger: ev1)
- validating -> reserving (trigger: d1 yes)
- validating -> rejected (trigger: d1 no)
- reserving -> authorising (trigger: a2 complete)
- authorising -> creating (trigger: d2 yes)
- authorising -> rejected (trigger: d2 no)
- creating -> completed (trigger: a4 complete)

## Assumptions
<!-- none -->

## Ambiguities
<!-- none -->

## Suggested Edits
<!-- none -->

## Open Questions
- [ ] (R9-state-transitions) Confirm these state transitions are descriptive only (they will be ignored by code generation).
  Answer: 

## Cross-Workflow Dependencies
- [ ] provides output `order_id` to `order-fulfilment` input `order_id` — Order Fulfilment consumes the order_id produced by Order Placement
- [ ] provides output `order_id` to `order-return` input `order_id` — Order Return consumes the order_id produced by Order Placement

## Triggers
- [ ] triggers `order-fulfilment` (fire-and-forget) when `when an order is placed`
  input order_id: step output `order_id` (str)
- [ ] triggers `order-return` (fire-and-forget)
  input order_id: step output `order_id` (str)

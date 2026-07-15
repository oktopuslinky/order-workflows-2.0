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
- start states: Cart submitted for checkout
- end states: Order created (placed), Checkout rejected (CartNotEligible or PaymentDeclined), Inventory reservation released (PaymentDeclined)
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
- BR-1: A cart may only be placed when it is in the open state
- BR-2: Inventory must be reserved before payment is authorised
- BR-3: Payment must be authorised before the order is created

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
- Validate cart: 5 seconds
- Authorise payment: 30 seconds

## Retries
- Reserve inventory: up to 3 times with exponential backoff starting at 2 seconds
- Authorise payment: up to 2 times with a fixed 5-second delay (excluding PaymentDeclined)

## Activities
- [a1] Validate cart
- [a2] Reserve inventory
- [a3] Authorise payment
- [a4] Create order
- [a5] Release inventory

## Decisions
- [d1] Is the cart eligible? — after: a1; yes: a2; no: e1
- [d2] Is payment authorised? — after: a3; yes: a4; no: e2

## Exceptions
- [e1] CART_NOT_ELIGIBLE — raised by: a1
- [e2] PaymentDeclined — raised by: a3

## Compensations
- [c1] Release inventory — compensates: a2

## Events
- [ev1] checkout.submitted — kind: trigger; emitted by: start
- [ev2] order_id — kind: output_emit; emitted by: a4
- [ev3] authorization_id — kind: output_emit; emitted by: a3
- [ev4] placement_status — kind: output_emit

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
- [ ] provides output `order_id` to `order-fulfilment` input `order_id` — Order Fulfilment requires the order_id produced by Order Placement to initiate
- [ ] provides output `order_id` to `order-return` input `order_id` — Order Return requires the order_id from Order Placement to process a return

## Triggers
- [ ] triggers `order-fulfilment` (fire-and-forget) when `when an order is placed`
  input order_id: step output `order_id` (str)
- [ ] triggers `order-return` (fire-and-forget)
  input order_id: step output `order_id` (str)

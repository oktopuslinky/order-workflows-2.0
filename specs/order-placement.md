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
- BR-1: Cart must be in open state for placement
- BR-2: Inventory reserved before payment authorisation
- BR-3: Payment authorised before order creation

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
- Validate cart: < 5 seconds
- Authorise payment: < 30 seconds

## Retries
- Reserve inventory: up to 3 times with exponential backoff (start 2s)
- Authorise payment: up to 2 times with fixed 5s delay (exclude PaymentDeclined)

## Activities
- [a1] Validate Cart
- [a2] Reserve Inventory
- [a3] Authorise Payment
- [a4] Create Order

## Decisions
- [d1] Is Cart Eligible? — after: a1; yes: a2; no: e1
- [d2] Is Payment Authorised? — after: a3; yes: a4; no: e2

## Exceptions
- [e1] CartNotEligible
- [e2] PaymentDeclined — raised by: a3

## Compensations
- [c1] Release Inventory Reservation — compensates: a2

## Events
- [v1] checkout.submitted — emitted by: start
- [v2] order_id — emitted by: a4 [human]
- [v3] authorization_id — emitted by: a3 [human]

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
- [x] provides output `order_id` to `order-fulfilment` input `order_id` — Order Fulfilment consumes the order_id produced by Order Placement
- [x] provides output `order_id` to `order-return` input `order_id` — Order Return consumes the order_id produced by Order Placement

## Triggers
<!-- none -->

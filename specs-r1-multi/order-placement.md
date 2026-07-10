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
- triggers: checkout.submitted request received by Order Service, cart submitted for checkout
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
- BR-2: Inventory reserved before payment authorisation
- BR-3: Payment authorised before order creation

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
- Reserve inventory: up to 3 times with exponential backoff (start 2s)
- Authorise payment: up to 2 times with 5s delay (exclude PaymentDeclined)

## Activities
- [a1] Validate Cart
- [a2] Reserve Inventory
- [a3] Authorise Payment
- [a4] Create Order

## Decisions
- [d1] Is Cart Eligible? — after: a1; yes: a2; no: e1

## Exceptions
- [e1] CartNotEligible — raised by: a1
- [e2] PaymentDeclined — raised by: a3

## Compensations
- [c1] Release Inventory Reservation — compensates: a2

## Events
- [ev1] checkout.submitted — kind: trigger; emitted by: start
- [ev2] order_id — kind: output_emit
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
- [x] (R4-decisions) For each flagged decision, what happens on the 'no' branch (name the exception or next step)?
  Answer: d1 -> CartNotEligible; d2 -> PaymentDeclined

## Cross-Workflow Dependencies
- [x] provides output `order_id` to `order-fulfilment` input `order_id` — Order Fulfilment requires the order_id produced by Order Placement to initiate the fulfilment process
- [x] provides output `order_id` to `order-return` input `order_id` — Order Return requires the order_id from Order Placement to process the return

## Triggers
- [x] triggers `order-fulfilment` (fire-and-forget) when `an order is placed`
  input order_id: step output `order_id` (str)

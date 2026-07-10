# Order Placement Workflow

<!--
  workflow-compiler specification (v1) — slug: order-placement
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
Turns a submitted shopping cart into a confirmed order by validating the cart, reserving inventory, authorising payment, and creating the order record.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Shopper, Order Operations
- systems: Order Service, Catalogue Service, Inventory Service, Payment Gateway
- triggers: checkout.submitted request to Order Service
- start states: open
- end states: rejected, placed
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
- [v1] [ev1] order_id emitted — emitted by: a4 [human]

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
  Answer: d1 (Is cart eligible?) no -> e1 CartNotEligible: reject the checkout and end the workflow. d2 (Is payment authorised?) no -> e2 PaymentDeclined: run c1 Release inventory and end the workflow

## Cross-Workflow Dependencies
- [x] provides output `order_id` to `order-fulfilment` input `order_id` — Order Fulfilment consumes the order_id produced by Order Placement
- [x] provides output `order_id` to `order-return` input `order_id` — Order Return consumes the order_id produced by Order Placement

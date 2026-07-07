# Order Management Operations

<!--
  workflow-compiler specification (v1) — slug: order-fulfilment
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
Manages the lifecycle of an order from placement through fulfillment to potential return, ensuring inventory, payment, and shipping processes are executed correctly.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Shopper, Order Operations, Warehouse Operator, Fulfillment Operations, Returns Operations, Customer
- systems: Order Service, Catalogue Service, Inventory Service, Payment Gateway, Fulfillment Service, Warehouse Service, Carrier Service, Returns Service
- triggers: checkout.submitted, order.fulfil, return.requested
- start states: Cart submitted for checkout, Order placed, Return requested
- end states: Order placed or rejected, Order fulfilled or cancelled, Return processed or rejected
- tags: 

## Inputs
- cart_id
- customer_id
- amount
- currency
- order_id
- shipment_id
- reason_code

## Outputs
- order_id
- authorization_id
- placement_status
- shipment_id
- payment_id
- fulfilment_status
- return_id
- refund_id
- return_status

## Business Rules
- BR-2: Inventory must be reserved before payment is authorised
- BR-3: Payment must be authorised before the order is created
- BR-2: The shipment must be packed before it is dispatched
- BR-3: Payment is captured only after the carrier confirms pickup
- BR-2: The returned item must be received before the refund is issued
- BR-3: A refund may not exceed the captured payment amount

## API Interfaces
- /orders/validate-cart
- /inventory/reserve
- /payments/authorize
- /orders/create
- /warehouse/pick
- /warehouse/pack
- /carrier/dispatch
- /payments/capture
- /returns/authorize
- /warehouse/receive
- /payments/refund

## Systems Involved
- Order Service
- Catalogue Service
- Inventory Service
- Payment Gateway
- Fulfilment Service
- Warehouse Service
- Carrier Service
- Returns Service

## Timers and SLAs
- Validate the cart must complete within 5 seconds
- Authorise payment must complete within 30 seconds
- Dispatch the shipment must complete within 60 seconds
- Carrier pickup confirmation must arrive within 12 hours
- Authorise the return must complete within 10 seconds
- Issue the refund must complete within 30 seconds

## Retries
- Reserve inventory: retry up to 3 times with exponential backoff starting at 2 seconds
- Authorise payment: retry up to 2 times with a fixed 5-second delay
- Dispatch the shipment: retry up to 3 times with exponential backoff starting at 2 seconds
- Capture payment: retry up to 5 times with exponential backoff starting at 1 second
- Receive the returned item: retry up to 3 times with exponential backoff starting at 2 seconds
- Issue the refund: retry up to 5 times with exponential backoff starting at 1 second

## Activities
- [a1] Validate Cart
- [a2] Reserve Inventory
- [a3] Authorise Payment
- [a4] Create Order
- [a5] Pick Items
- [a6] Pack Shipment
- [a7] Dispatch Shipment
- [a8] Capture Payment
- [a9] Authorise Return
- [a10] Receive Returned Item
- [a11] Issue Refund

## Decisions
- [d1] Is Cart Eligible? — after: a1; yes: a2; no: e1
- [d2] Is Payment Authorised? — after: a3; yes: a4; no: e2
- [d3] Is Dispatch Accepted? — after: a7; yes: a8; no: e3
- [d4] Is Return Eligible? — after: a9; yes: a10; no: e4

## Exceptions
- [e1] CartNotEligible
- [e2] PaymentDeclined — raised by: a3
- [e3] CarrierRejected — raised by: a7
- [e4] ReturnNotEligible
- [e5] PickupTimeout — raised by: a7
- [e6] RefundFailed — raised by: a11

## Compensations
- [c1] Release Inventory — compensates: a2
- [c2] Unpack Shipment — compensates: a6

## Events
- [v1] [ev1] checkout.submitted — emitted by: start
- [v2] [ev2] order.fulfil — emitted by: a4
- [v3] [ev3] return.requested — emitted by: start
- [v4] [ev4] carrier.picked_up — emitted by: a7

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
- [x] uses output `orderid` of `order-placement` as input `orderid` — Order Fulfilment consumes the order_id produced by Order Placement
- [x] provides output `shipmentid` to `order-return` input `shipmentid` — Order Return consumes the shipment_id produced by Order Fulfilment

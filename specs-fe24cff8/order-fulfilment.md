# Order Fulfilment

<!--
  workflow-compiler specification (v1) — slug: order-fulfilment
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
The Order Fulfilment workflow ships a placed order and captures its payment by picking items, packing the shipment, dispatching it, and capturing the previously-authorised payment.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Warehouse Operator, Fulfilment Operations
- systems: Fulfilment Service, Warehouse Service, Carrier Service, Payment Gateway
- triggers: Order placed and order.fulfil request received by Fulfilment Service
- start states: Order in 'placed' state
- end states: fulfilment_status: shipped, fulfilment_status: cancelled
- tags: 

## Inputs
- order_id
- authorization_id

## Outputs
- shipment_id
- payment_id
- fulfilment_status

## Business Rules
- BR-1: Order must be in placed state for fulfilment
- BR-2: Shipment must be packed before dispatch
- BR-3: Payment captured only after carrier pickup confirmation

## API Interfaces
- Warehouse Service /warehouse/pick
- Warehouse Service /warehouse/pack
- Carrier Service /carrier/dispatch
- Payment Gateway /payments/capture

## Systems Involved
- Fulfilment Service
- Warehouse Service
- Carrier Service
- Payment Gateway

## Timers and SLAs
- Dispatch shipment within 60 seconds
- Carrier pickup confirmation within 12 hours

## Retries
- Dispatch shipment: up to 3 times with exponential backoff (start 2 seconds)
- Capture payment: up to 5 times with exponential backoff (start 1 second)

## Activities
- [a1] Pick items
- [a2] Pack shipment
- [a3] Dispatch shipment
- [a4] Capture payment
- [a5] Wait for carrier pickup confirmation

## Decisions
- [d1] Dispatch accepted? — after: a3; yes: a4; no: e1

## Exceptions
- [e1] CarrierRejected — raised by: a3
- [e2] PickupTimeout — raised by: a5

## Compensations
- [c1] Unpack shipment — compensates: a2

## Events
- [ev1] order.fulfil — kind: trigger; emitted by: start
- [ev2] carrier.picked_up — kind: signal_wait; emitted by: a5
- [ev3] shipment_id — kind: output_emit; emitted by: a3
- [ev4] payment_id — kind: output_emit; emitted by: a4
- [ev5] fulfilment_status — kind: output_emit

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
- [x] uses output `order_id` of `order-placement` as input `order_id` — Order Fulfilment consumes the order_id produced by Order Placement
- [x] provides output `shipment_id` to `order-return` input `shipment_id` — Order Return consumes the shipment_id produced by Order Fulfilment

## Triggers
- [x] triggers `order-return` (fire-and-forget) when `when a shipment is dispatched`
  input shipment_id: step output `shipment_id` (str)

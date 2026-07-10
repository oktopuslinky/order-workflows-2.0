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
- start states: placed
- end states: shipped, cancelled
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
- BR-3: Payment capture only after carrier pickup confirmation

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
- [a4] Wait for carrier pickup confirmation
- [a5] Capture payment

## Decisions
- [d1] Dispatch accepted? — after: a3; yes: a4; no: e1

## Exceptions
- [e1] CarrierRejected — raised by: a3
- [e2] PickupTimeout — raised by: a4

## Compensations
- [c1] Unpack shipment — compensates: a2

## Events
- [v1] order.fulfil request — emitted by: start
- [v3] shipment_id — emitted by: a3 [human]
- [v4] payment_id — emitted by: a5 [human]

## State Transitions
<!-- none -->

## Assumptions
<!-- none -->

## Ambiguities
<!-- none -->

## Suggested Edits
<!-- none -->

## Open Questions
- [x] (R9-state-transitions) Confirm these state transitions are descriptive only (they will be ignored by code generation).
  Answer: Yes — descriptive only. Removed from the spec; control flow is modelled by the Activities, Decisions, Exceptions, and Compensations sections

## Cross-Workflow Dependencies
- [x] uses output `order_id` of `order-placement` as input `order_id` — Order Fulfilment consumes the order_id produced by Order Placement
- [x] provides output `shipment_id` to `order-return` input `shipment_id` — Order Return consumes the shipment_id produced by Order Fulfilment

## Triggers
<!-- none -->

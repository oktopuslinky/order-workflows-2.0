# Order Settlement Workflow

<!--
  workflow-compiler specification (v1) — slug: order-settlement-workflow
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
This workflow settles a confirmed order by validating it, reserving inventory, charging the customer, awaiting shipping confirmation, and finalising the sale, with rollback capabilities for failed steps.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Customer, Warehouse Operator, Settlement Operations
- systems: Settlement Service, Inventory Service, Payment Gateway, Notification Service, Analytics Pipeline
- triggers: Order confirmed and order.settle request received by Settlement Service, shipping.confirmed signal received
- start states: confirmed
- end states: rejected, settled, rolled_back
- tags: 

## Inputs
- order_id
- customer_id
- amount
- currency

## Outputs
- settlement_id
- payment_id
- settlement_status

## Business Rules
- BR-1: An order may only be settled when it is in the confirmed state
- BR-2: Inventory must be reserved before payment is charged
- BR-3: Payment must be captured before shipping confirmation is awaited
- BR-4: If shipping is not confirmed before the deadline, the settlement is rolled back

## API Interfaces
- Settlement Service /settlement/validate
- Inventory Service /inventory/reserve
- Payment Gateway /payments/charge
- Notification Service /notify/customer
- Analytics Pipeline /analytics/event
- Settlement Service /settlement/finalise

## Systems Involved
- Settlement Service
- Inventory Service
- Payment Gateway
- Notification Service
- Analytics Pipeline
- Warehouse Operator

## Timers and SLAs
- Order validation: 5 seconds
- Charge payment: 30 seconds
- Shipping confirmation: 24 hours

## Retries
- Reserve inventory: up to 3 times with exponential backoff starting at 2 seconds
- Charge payment: up to 2 times with a fixed 5-second delay (excluding PaymentDeclined)
- Notify customer: up to 5 times with exponential backoff (non-fatal)

## Activities
- [a1] Validate Order
- [a2] Reserve Inventory
- [a3] Charge Payment
- [a4] Notify Customer — parallel: g1
- [a5] Record Settlement Event — parallel: g1
- [a6] Wait for Shipping Confirmation
- [a7] Finalise Settlement

## Decisions
- [d1] Is Order Settleable? — after: a1; yes: a2; no: e1
- [d2] Is Charge Successful? — after: a3; yes: a4; no: e2

## Exceptions
- [e1] ORDER_NOT_SETTLEABLE
- [e2] PAYMENT_DECLINED — raised by: a3
- [e3] SHIPPING_TIMEOUT — raised by: a6

## Compensations
- [c1] Release Inventory — compensates: a2
- [c2] Refund Payment — compensates: a3

## Events
- [ev1] order.settle — kind: trigger; emitted by: start
- [ev2] shipping.confirmed — kind: signal_wait; emitted by: a6
- [ev3] settlement_id — kind: output_emit; emitted by: a7
- [ev4] payment_id — kind: output_emit; emitted by: a3

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
<!-- none -->

## Triggers
<!-- none -->

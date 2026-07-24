# Edit Request

<!--
Canonical multi-workflow edit request, written against the project compiled
from examples/ideal_multi_workflow.md (slugs: order-placement,
order-fulfilment, order-return). It exercises every operation class in one
document: per-workflow add/modify/remove, cross-workflow trigger and
dependency wiring, and whole-workflow add/remove.
-->

## Workflow: order-placement

### Add

- After the order is created, the system **sends an order confirmation email**
  to the shopper via the Notification Service.
- A business rule: BR-4: Orders above $5,000 require a fraud review before
  payment authorisation.
- A timer: fraud review must complete within 2 minutes.

### Modify

- Rename the activity "Create order" [a4] to "Create order record".
- "Reserve inventory" retries change from 3 to 4 attempts.
- The workflow owner is the Order Operations Team.

### Remove

- The business rule BR-1: A cart may only be placed when it is in the open
  state (carts are now locked at checkout instead).
- The exception PaymentDeclined [e2] (declines are now handled as a normal
  decision outcome, not an exception).

### Triggers

- Modify the trigger from order-placement to order-fulfilment: it now fires
  when an order is placed and payment is authorised (still fire-and-forget),
  passing order_id from the order_id output.

### Dependencies

- Remove the dependency: order-placement's order_id output is no longer
  consumed directly as order-fulfilment's order_id input (the trigger's input
  mapping carries it instead).

## Workflow: order-fulfilment

### Add

- After payment is captured, the system **records a fulfilment ledger entry**
  in the Finance Service.
- A business rule: BR-4: Hazardous items must ship via ground carriers only.
- A compensation: Refund captured payment — compensates "Capture payment" [a4].

### Modify

- Rename the activity "Pick items" [a1] to "Pick order items".
- Carrier pickup confirmation window changes from 12 hours to 24 hours.
- The workflow owner is the Fulfilment Operations Team.

### Remove

- The business rule BR-3: Payment capture only after carrier pickup
  confirmation (capture now happens at dispatch).
- The activity "Wait for carrier pickup confirmation" [a5] (the carrier
  integration now confirms pickup synchronously at dispatch).

### Triggers

- When payment is captured, this workflow starts payment-reconciliation
  (fire-and-forget), passing payment_id from the payment_id output.

### Dependencies

- payment-reconciliation consumes this workflow's payment_id output as its
  payment_id input.

## Add Workflow: payment-reconciliation

## Payment Reconciliation Purpose

The Payment Reconciliation workflow verifies that every captured payment
matches the order total and the payment gateway settlement record, and files
a discrepancy report when they disagree.

## Payment Reconciliation Trigger

A payment.captured event received by the Finance Service starts the
reconciliation for that payment.

## Payment Reconciliation Actors

- Finance Analyst
- Finance Operations

## Payment Reconciliation Systems

- Finance Service
- Payment Gateway
- Order Service

## Payment Reconciliation Inputs and Outputs

Inputs:

- payment_id
- order_id

Outputs:

- reconciliation_status
- discrepancy_report_id

## Payment Reconciliation Process

1. Fetch the settlement record from the Payment Gateway.
2. Fetch the order total from the Order Service.
3. Compare the captured amount with the order total.
4. If the amounts match, mark the payment reconciled.
5. If the amounts differ, file a discrepancy report and notify Finance
   Operations.

## Payment Reconciliation Business Rules

- BR-1: A payment may only be reconciled once.
- BR-2: Discrepancies above $100 must be escalated to Finance Operations.

## Payment Reconciliation Retries

- Fetch settlement record: up to 3 times with exponential backoff starting at
  5 seconds.

## Remove Workflow: order-return

## Reason

Q3 2026 fulfilment re-architecture (FIN-88): returns move to the standalone
returns platform (order-return retires), payment reconciliation becomes a
first-class workflow, carriers now confirm pickup synchronously, and the
fraud-review policy lands in placement.

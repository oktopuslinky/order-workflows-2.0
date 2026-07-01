# Order Settlement Workflow

<!--
  IDEAL-CONDITIONS REFERENCE DOCUMENT
  ----------------------------------
  This document is deliberately written so that every pipeline stage
  (discovery → facts → structure → graph → CVPA → Temporal design → Temporal code)
  has exactly what it needs and nothing that confuses it. See the
  "Temporal-alignment notes" section at the bottom for where (and why) it
  intentionally deviates from docs/DOCUMENT_FORMAT_GUIDE.md.

  Design goals that map 1:1 onto a Temporal workflow:
    * ONE workflow, ONE start, ONE end  (no multi-workflow / multi-start confusion)
    * Activity names are stable PascalCase phrases, reused verbatim in the
      Process, API Interfaces, Retries, and Compensation sections.
    * Every decision states BOTH branches; the "yes" branch is the happy path and
      the "no" branch routes to a NAMED exception (never back to the same step).
    * "In parallel" is used ONLY for genuinely independent activities that share
      no data dependency and are not gated by a decision.
    * Saga compensations use the exact "<Comp> compensates <Activity>" phrasing.
    * The one human/external wait is modelled as a signal AND paired with a timer
      so the Temporal design can bound it (no wait-forever signal gate).
    * NO free-form "state transitions" ("X transitions to Y") are written in the
      Process — those create a disconnected state subgraph that the design LLM
      mis-reads. Lifecycle states live only in the Metadata/States section.
-->

## Metadata

| Field   | Value                                   |
|---------|-----------------------------------------|
| Domain  | Commerce / Order Management             |
| Owner   | Settlement Platform Team                |
| Version | 1.0                                     |
| Tags    | saga, compensation, payments, signal    |

## Purpose

This workflow settles a confirmed order: it validates the order, reserves
inventory, charges the customer, waits for warehouse shipping confirmation, and
finalises the sale. If any step after payment fails, it compensates the completed
steps in reverse so the customer is never charged for an order that cannot ship.

## Trigger

The workflow starts when an **order is confirmed** and an `order.settle` request
is received by the Settlement Service.

## Actors

- Customer
- Warehouse Operator
- Settlement Operations

## Systems

- Settlement Service
- Inventory Service
- Payment Gateway
- Notification Service
- Analytics Pipeline

## Inputs and Outputs

**Inputs (these become the workflow input fields)**
- `order_id` — identifier of the confirmed order to settle
- `customer_id` — identifier of the paying customer
- `amount` — order total to charge
- `currency` — ISO currency code for the charge

**Outputs**
- `settlement_id` — identifier of the completed settlement
- `payment_id` — identifier of the captured payment
- `settlement_status` — `settled`, `rejected`, or `rolled_back`

## Process

1. The Settlement Service **validates the order** using `order_id` and returns
   whether the order is settleable.
2. If the order is **not settleable**, the workflow raises `OrderNotSettleable`
   and rejects the settlement; if the order **is settleable**, the workflow
   continues.
3. The Inventory Service **reserves inventory** for `order_id` and returns a
   `reservation_id`.
4. The Payment Gateway **charges payment** for `customer_id` for `amount` in
   `currency` and returns a `payment_id`.
5. If the charge is **declined**, the workflow raises `PaymentDeclined`; if the
   charge **succeeds**, the workflow continues.
6. In parallel, the Notification Service **notifies the customer** of the pending
   shipment and the Analytics Pipeline **records a settlement event**. These two
   activities are independent and share no data.
7. The workflow **waits for shipping confirmation** — a `shipping.confirmed`
   signal sent by the Warehouse Operator — for up to the shipping-confirmation
   deadline.
8. The Settlement Service **finalises the settlement** for `order_id` and returns
   a `settlement_id`.

## Business Rules

- **BR-1:** An order may only be settled when it is in the `confirmed` state.
- **BR-2:** Inventory must be reserved before payment is charged.
- **BR-3:** Payment must be captured before shipping confirmation is awaited.
- **BR-4:** If shipping is not confirmed before the deadline, the settlement is
  rolled back.

## Timers and SLAs

- Order validation must complete within **5 seconds**.
- Charge payment must complete within **30 seconds**.
- Shipping confirmation must arrive within **24 hours**; otherwise the workflow
  rolls back the settlement.

## API Interfaces

| System               | Method | Endpoint / Action          | Purpose                                   |
|----------------------|--------|----------------------------|-------------------------------------------|
| Settlement Service   | POST   | `/settlement/validate`     | Validate the order (`order_id`)           |
| Inventory Service    | POST   | `/inventory/reserve`       | Reserve inventory (`order_id`)            |
| Payment Gateway      | POST   | `/payments/charge`         | Charge payment (`customer_id`, `amount`)  |
| Notification Service | POST   | `/notify/customer`         | Notify the customer of pending shipment   |
| Analytics Pipeline   | POST   | `/analytics/event`         | Record a settlement event                 |
| Settlement Service   | POST   | `/settlement/finalise`     | Finalise the settlement (`order_id`)      |

## Exceptions and Error Handling

- **OrderNotSettleable:** the order is not in a settleable state → reject the
  settlement with reason `ORDER_NOT_SETTLEABLE` and end the workflow.
- **PaymentDeclined:** the Payment Gateway declines the charge → roll back the
  settlement (release inventory) and end the workflow.
- **ShippingTimeout:** shipping confirmation does not arrive within 24 hours →
  roll back the settlement (refund payment, release inventory).

## Retries

- **Reserve inventory:** retry up to **3 times** with **exponential backoff**
  starting at 2 seconds.
- **Charge payment:** retry up to **2 times** with a fixed **5-second** delay;
  do not retry on a `PaymentDeclined` error.
- **Notify customer:** retry up to **5 times** with exponential backoff; failure
  is non-fatal.

## Compensation and Rollback

- **Release inventory** compensates **Reserve inventory** — return the reserved
  stock if the settlement is rolled back after reservation.
- **Refund payment** compensates **Charge payment** — reverse the captured charge
  if the settlement is rolled back after payment.

---

## Temporal-alignment notes (deviations from DOCUMENT_FORMAT_GUIDE.md and why)

These are written for the human author, not the pipeline. They explain the
choices that make this document produce clean Temporal code:

1. **No `## States` "transition" sentences in the Process.** The format guide
   encourages "The order transitions from `received` to `cancelled`." Those
   become `STATE_TRANSITION` facts and the graph builder turns each into a
   separate `state_*` node, producing a **disconnected state subgraph** (with its
   own "Start"-labelled node) alongside the real flow. The Temporal design LLM
   then sees two parallel structures and can mis-wire the plan. **Deviation:**
   lifecycle states are mentioned only as prose in BR-1; no `X -> Y` transition
   lines are written. (We also omit the `## States` start/end-state list, which
   only feeds discovery metadata and is not needed for the code.)

2. **Every decision's "no" branch points at a distinct named exception**, never
   back at the same activity. A decision whose yes/no targets are identical is a
   degenerate decision the pipeline now repairs, but writing it correctly avoids
   the repair entirely.

3. **"In parallel" is reserved for truly independent work** (NotifyCustomer +
   RecordSettlementEvent). Activities with data dependencies (Reserve → Charge →
   Finalise) are written as sequential numbered steps so they are never folded
   into a fork.

4. **The single human/external wait is BOTH a signal and a timer.** Step 7 names
   a `shipping.confirmed` signal and the Timers section gives it a 24-hour
   deadline, so the design can model a bounded `wait_condition(..., timeout=...)`
   instead of a signal gate that blocks forever.

5. **Activity names are reused verbatim** across Process / API Interfaces /
   Retries / Compensation. This is what lets the design bind retries, timeouts,
   and compensations to the right activity by name (the code generator matches by
   normalised name).

6. **Inputs are named as snake_case fields** (`order_id`, `customer_id`, …) so
   they map directly onto `WorkflowInput` dataclass fields and onto activity
   input bindings.

# Order Management Operations

<!--
  IDEAL-CONDITIONS MULTI-WORKFLOW REFERENCE DOCUMENT
  --------------------------------------------------
  This is the multi-flow companion to examples/ideal_temporal_workflow.md.
  Where that document is deliberately written so ONE workflow compiles cleanly
  end-to-end, this document is written so the spec-centric front-end
  (segmentation -> per-workflow facts -> spec gate -> per-workflow graph/CVPA/
  Temporal design/code) segments THREE distinct workflows cleanly and links them
  by typed output->input dependencies.

  Design goals that map 1:1 onto clean segmentation + three clean Temporal designs:
    * THREE workflows, each with ONE start and ONE end. No workflow shares a
      Process section with another.
    * Every section heading is PREFIXED with its workflow's short name
      ("Order Placement ...", "Order Fulfilment ...", "Order Return ...") so the
      deterministic section-title matcher slices each workflow's text with no
      overlap. The bare keyword the facts stage keys on (Process, Trigger,
      Inputs and Outputs, Retries, Compensation, ...) is preserved after the
      prefix.
    * Cross-workflow links are stated explicitly, in both prose (this Overview)
      and via matching field names: an OUTPUT field of one workflow is reused
      verbatim as an INPUT field of the next (order_id, shipment_id). This is
      what the segmentation dependency detector keys on.
    * Within each workflow the same per-flow ideal rules as ideal_temporal_workflow.md
      apply: stable PascalCase activity names reused verbatim across Process /
      API Interfaces / Retries / Compensation; every decision's "no" branch routes
      to a NAMED exception (never back to the same step); "in parallel" only for
      genuinely independent activities; saga compensations phrased exactly as
      "<Comp> compensates <Activity>"; the one human/external wait is a signal
      paired with a timer so it is bounded; inputs are snake_case fields; NO
      free-form "X transitions to Y" state sentences in any Process.
-->

## Overview

The Order Platform team operates three related but independently-deployable
workflows. They run in sequence across an order's life but are separate Temporal
workflows, each triggered by its own event and each owning its own compensation:

1. **Order Placement** accepts a shopper's cart, validates it, reserves
   inventory, authorises payment, and creates the order. It emits `order_id`.
2. **Order Fulfilment** picks, packs, and ships a placed order, then captures the
   previously-authorised payment. It consumes `order_id` from Order Placement and
   emits `shipment_id`.
3. **Order Return** authorises and processes a return for a shipped order and
   refunds the customer. It consumes `order_id` from Order Placement and
   `shipment_id` from Order Fulfilment.

Cross-workflow dependencies (output -> input):

- Order Placement `order_id` -> Order Fulfilment `order_id`
- Order Placement `order_id` -> Order Return `order_id`
- Order Fulfilment `shipment_id` -> Order Return `shipment_id`

---

## Order Placement Purpose

The Order Placement workflow turns a submitted shopping cart into a confirmed
order: it validates the cart, reserves inventory, authorises payment, and creates
the order record. If payment authorisation fails after inventory is reserved, the
reservation is released so no stock is held for an order that will not be placed.

## Order Placement Trigger

The workflow starts when a shopper **submits a cart for checkout** and a
`checkout.submitted` request reaches the Order Service.

## Order Placement Actors

- Shopper
- Order Operations

## Order Placement Systems

- Order Service
- Catalogue Service
- Inventory Service
- Payment Gateway

## Order Placement Inputs and Outputs

**Inputs (these become the workflow input fields)**
- `cart_id` — identifier of the submitted cart
- `customer_id` — identifier of the checking-out customer
- `amount` — cart total to authorise
- `currency` — ISO currency code for the authorisation

**Outputs**
- `order_id` — identifier of the created order
- `authorization_id` — identifier of the payment authorisation
- `placement_status` — `placed` or `rejected`

## Order Placement Process

1. The Order Service **validates the cart** using `cart_id` and returns whether
   the cart is checkout-eligible.
2. If the cart is **not eligible**, the workflow raises `CartNotEligible` and
   rejects the checkout; if the cart **is eligible**, the workflow continues.
3. The Inventory Service **reserves inventory** for `cart_id` and returns a
   `reservation_id`.
4. The Payment Gateway **authorises payment** for `customer_id` for `amount` in
   `currency` and returns an `authorization_id`.
5. If the authorisation is **declined**, the workflow raises `PaymentDeclined`; if
   the authorisation **succeeds**, the workflow continues.
6. The Order Service **creates the order** for `cart_id` and returns an
   `order_id`.

## Order Placement Business Rules

- **BR-1:** A cart may only be placed when it is in the `open` state.
- **BR-2:** Inventory must be reserved before payment is authorised.
- **BR-3:** Payment must be authorised before the order is created.

## Order Placement Timers and SLAs

- Validate the cart must complete within **5 seconds**.
- Authorise payment must complete within **30 seconds**.

## Order Placement API Interfaces

| System            | Method | Endpoint / Action        | Purpose                                     |
|-------------------|--------|--------------------------|---------------------------------------------|
| Order Service     | POST   | `/orders/validate-cart`  | Validate the cart (`cart_id`)               |
| Inventory Service | POST   | `/inventory/reserve`     | Reserve inventory (`cart_id`)               |
| Payment Gateway   | POST   | `/payments/authorize`    | Authorise payment (`customer_id`, `amount`) |
| Order Service     | POST   | `/orders/create`         | Create the order (`cart_id`)                |

## Order Placement Exceptions and Error Handling

- **CartNotEligible:** the cart is not in a checkout-eligible state → reject the
  checkout with reason `CART_NOT_ELIGIBLE` and end the workflow.
- **PaymentDeclined:** the Payment Gateway declines the authorisation → release
  the inventory reservation and end the workflow.

## Order Placement Retries

- **Reserve inventory:** retry up to **3 times** with **exponential backoff**
  starting at 2 seconds.
- **Authorise payment:** retry up to **2 times** with a fixed **5-second** delay;
  do not retry on a `PaymentDeclined` error.

## Order Placement Compensation and Rollback

- **Release inventory** compensates **Reserve inventory** — return the reserved
  stock if placement is rolled back after reservation.

---

## Order Fulfilment Purpose

The Order Fulfilment workflow ships a placed order and then captures its payment:
it picks the items, packs the shipment, dispatches it, and captures the
previously-authorised payment. If dispatch fails after packing, the pack step is
rolled back so a packed-but-undispatched shipment is not left stranded.

## Order Fulfilment Trigger

The workflow starts when an **order is placed** and an `order.fulfil` request
reaches the Fulfilment Service. It requires the `order_id` produced by Order
Placement.

## Order Fulfilment Actors

- Warehouse Operator
- Fulfilment Operations

## Order Fulfilment Systems

- Fulfilment Service
- Warehouse Service
- Carrier Service
- Payment Gateway

## Order Fulfilment Inputs and Outputs

**Inputs (these become the workflow input fields)**
- `order_id` — identifier of the placed order to fulfil
- `authorization_id` — identifier of the payment authorisation to capture

**Outputs**
- `shipment_id` — identifier of the dispatched shipment
- `payment_id` — identifier of the captured payment
- `fulfilment_status` — `shipped` or `cancelled`

## Order Fulfilment Process

1. The Warehouse Service **picks the items** for `order_id` and returns a
   `pick_list_id`.
2. The Warehouse Service **packs the shipment** for `order_id` and returns a
   `package_id`.
3. The Carrier Service **dispatches the shipment** for `package_id` and returns a
   `shipment_id`.
4. If dispatch is **rejected by the carrier**, the workflow raises
   `CarrierRejected`; if dispatch **is accepted**, the workflow continues.
5. The workflow **waits for carrier pickup confirmation** — a `carrier.picked_up`
   signal sent by the Carrier Service — for up to the pickup-confirmation
   deadline.
6. The Payment Gateway **captures payment** for `authorization_id` and returns a
   `payment_id`.

## Order Fulfilment Business Rules

- **BR-1:** An order may only be fulfilled when it is in the `placed` state.
- **BR-2:** The shipment must be packed before it is dispatched.
- **BR-3:** Payment is captured only after the carrier confirms pickup.

## Order Fulfilment Timers and SLAs

- Dispatch the shipment must complete within **60 seconds**.
- Carrier pickup confirmation must arrive within **12 hours**; otherwise the
  fulfilment is cancelled.

## Order Fulfilment API Interfaces

| System            | Method | Endpoint / Action        | Purpose                                    |
|-------------------|--------|--------------------------|--------------------------------------------|
| Warehouse Service | POST   | `/warehouse/pick`        | Pick the items (`order_id`)                |
| Warehouse Service | POST   | `/warehouse/pack`        | Pack the shipment (`order_id`)             |
| Carrier Service   | POST   | `/carrier/dispatch`      | Dispatch the shipment (`package_id`)       |
| Payment Gateway   | POST   | `/payments/capture`      | Capture payment (`authorization_id`)       |

## Order Fulfilment Exceptions and Error Handling

- **CarrierRejected:** the carrier rejects the dispatch → roll back the packing
  and end the workflow with status `cancelled`.
- **PickupTimeout:** carrier pickup confirmation does not arrive within 12 hours →
  roll back the packing and cancel the fulfilment.

## Order Fulfilment Retries

- **Dispatch the shipment:** retry up to **3 times** with **exponential backoff**
  starting at 2 seconds; do not retry on a `CarrierRejected` error.
- **Capture payment:** retry up to **5 times** with exponential backoff starting
  at 1 second.

## Order Fulfilment Compensation and Rollback

- **Unpack the shipment** compensates **Pack the shipment** — undo the packing and
  return items to stock if fulfilment is rolled back after packing.

---

## Order Return Purpose

The Order Return workflow processes a customer's return for a shipped order: it
authorises the return, receives the returned item back into the warehouse, and
refunds the captured payment. If the refund fails after the item is received, the
return is escalated to Returns Operations rather than silently dropped.

## Order Return Trigger

The workflow starts when a customer **requests a return** and a `return.requested`
request reaches the Returns Service. It requires the `order_id` produced by Order
Placement and the `shipment_id` produced by Order Fulfilment.

## Order Return Actors

- Customer
- Returns Operations

## Order Return Systems

- Returns Service
- Warehouse Service
- Payment Gateway

## Order Return Inputs and Outputs

**Inputs (these become the workflow input fields)**
- `order_id` — identifier of the order being returned
- `shipment_id` — identifier of the shipment being returned
- `reason_code` — the customer's stated reason for the return

**Outputs**
- `return_id` — identifier of the processed return
- `refund_id` — identifier of the issued refund
- `return_status` — `refunded` or `rejected`

## Order Return Process

1. The Returns Service **authorises the return** using `order_id` and
   `reason_code` and returns whether the return is eligible.
2. If the return is **not eligible**, the workflow raises `ReturnNotEligible` and
   rejects the return; if the return **is eligible**, the workflow continues.
3. The Warehouse Service **receives the returned item** for `shipment_id` and
   returns a `return_id`.
4. The Payment Gateway **issues the refund** for `order_id` and returns a
   `refund_id`.

## Order Return Business Rules

- **BR-1:** A return may only be authorised for an order in the `shipped` state.
- **BR-2:** The returned item must be received before the refund is issued.
- **BR-3:** A refund may not exceed the captured payment amount.

## Order Return Timers and SLAs

- Authorise the return must complete within **10 seconds**.
- Issue the refund must complete within **30 seconds**.

## Order Return API Interfaces

| System            | Method | Endpoint / Action         | Purpose                                        |
|-------------------|--------|---------------------------|------------------------------------------------|
| Returns Service   | POST   | `/returns/authorize`      | Authorise the return (`order_id`)              |
| Warehouse Service | POST   | `/warehouse/receive`      | Receive the returned item (`shipment_id`)      |
| Payment Gateway   | POST   | `/payments/refund`        | Issue the refund (`order_id`)                  |

## Order Return Exceptions and Error Handling

- **ReturnNotEligible:** the order is not in a returnable state → reject the return
  with reason `RETURN_NOT_ELIGIBLE` and end the workflow.
- **RefundFailed:** the Payment Gateway cannot issue the refund → escalate the
  return to Returns Operations for manual handling.

## Order Return Retries

- **Receive the returned item:** retry up to **3 times** with exponential backoff
  starting at 2 seconds.
- **Issue the refund:** retry up to **5 times** with exponential backoff starting
  at 1 second.

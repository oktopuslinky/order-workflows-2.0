# Order Fulfillment Workflow

## Purpose

This workflow describes how the company fulfills a customer order from the moment
it is submitted through delivery, including payment, inventory, shipping, and the
handling of failures.

## Trigger

The workflow starts when a **customer submits an order** through the online store.

## Process

1. When the order is received, the system **validates the order details** and the
   **payment** via the Payment Gateway.
2. If the payment is **declined**, the order is **cancelled** and the customer is
   notified by email.
3. If the payment is valid, the **Warehouse Management System reserves inventory**.
4. In parallel, the system **sends an order confirmation** to the customer and
   **notifies the warehouse** to begin picking.
5. The warehouse **picks and packs the items**.
6. The carrier API is called to **create a shipment** and the order is shipped.
7. If shipment creation fails, the system **retries up to 3 times**. If it still
   fails, the reserved **inventory is released** (compensation) and the order is
   marked as **failed**.

## Rules

- Orders above $1,000 require **manager approval** before fulfillment.
- Orders must be shipped within **24 hours** of payment confirmation, otherwise an
  SLA-breach alert is raised.

## States

- Start states: `Order received`.
- End states: `Order delivered`, `Order cancelled`, `Order failed`.

## Systems

- Online Store, Payment Gateway, Warehouse Management System, Carrier API, Email Service.

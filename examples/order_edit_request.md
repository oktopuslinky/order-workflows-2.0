# Edit Request

<!--
Example edit request against examples/order_workflow.md.
The slug below must match the spec file name your compile produced
(see the <slug>.md files in your --spec-dir); adjust it if it differs.
-->

## Workflow: order-fulfillment-workflow

### Add

- After the items are picked and packed, the system **notifies the finance team**
  via the Email Service that the order is ready to invoice.
- A business rule: partial shipments are not allowed — an order ships only when
  every item is available.

### Modify

- Shipment creation retries change from 3 attempts to 5 attempts.
- The workflow owner is the Fulfillment Operations Team.

### Remove

- The manager-approval rule for orders above $1,000 (the policy was retired).

## Reason

June 2026 fulfillment policy update (OPS-142): approval threshold retired,
finance wants an invoice-ready notification, and carrier flakiness justifies
two extra shipment retries.

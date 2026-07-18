# Project workflows

Every workflow below is standalone: each has its own bundle directory,
worker, and task queue, and can be started independently. Cross-workflow
relationships are explicit triggers (a generated activity starts the
target by name) — never parent/child ownership.

| Workflow | Bundle | Task queue |
| --- | --- | --- |
| FulfilmentWorkflow | `order_fulfilment/` | `fulfilment-queue` |
| OrderFulfillmentWorkflow | `order_placement/` | `order-fulfillment-queue` |
| PaymentReconciliationWorkflow | `payment_reconciliation/` | `reconciliation-queue` |

## Trigger topology

- `order-placement` —(fire-and-forget)→ `order-fulfilment`
- `order-fulfilment` —(fire-and-forget)→ `payment-reconciliation`

Run every worker (one per bundle) so triggers can start their targets.
Workers read `TEMPORAL_ADDRESS` (default `localhost:7233`).
# Project workflows

Every workflow below is standalone: each has its own bundle directory,
worker, and task queue, and can be started independently. Cross-workflow
relationships are explicit triggers (a generated activity starts the
target by name) — never parent/child ownership.

| Workflow | Bundle | Task queue |
| --- | --- | --- |
| OrderFulfilmentWorkflow | `order_fulfilment/` | `order-fulfilment-queue` |
| EcommerceOrderWorkflow | `order_placement/` | `ecommerce-queue` |
| ReturnProcessingWorkflow | `order_return/` | `return-processing-queue` |

## Trigger topology

- `order-placement` —(fire-and-forget when `when an order is placed`)→ `order-fulfilment`
- `order-placement` —(fire-and-forget)→ `order-return`
- `order-fulfilment` —(fire-and-forget when `when a shipment is dispatched`)→ `order-return`

Run every worker (one per bundle) so triggers can start their targets.
Workers read `TEMPORAL_ADDRESS` (default `localhost:7233`).
# Project workflows

Every workflow below is standalone: each has its own bundle directory,
worker, and task queue, and can be started independently. Cross-workflow
relationships are explicit triggers (a generated activity starts the
target by name) — never parent/child ownership.

| Workflow | Bundle | Task queue |
| --- | --- | --- |
| OrderFulfillmentWorkflow | `order_fulfillment_workflow/` | `order-fulfillment-queue` |
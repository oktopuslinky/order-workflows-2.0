# Technical Design — Order Workflow

## 1. Components

The `OrderWorkflow` in `src/orders/workflow.py` calls the activities
`validate_order`, `provision_order`, `dispatch_order` and `release_provisioning`.

## 2. Compensation

When `dispatch_order` raises, the workflow calls `release_provisioning` — the
saga compensation for provisioning — and finishes with status `compensated`.

## 3. Diagram

See `docs/diagrams/order-state-machine.mmd`.

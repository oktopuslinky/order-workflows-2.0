# TDD-ORD-002 — OrderWorkflow — Temporal Implementation (Partial Shipment Support for Multi-Line Orders)
**Document ID:** TDD-ORD-002
**Linked EPIC:** EPIC-002
**Supersedes:** TDD-ORD-001
**Version:** 0.1
**Status:** Draft
**Author:** Platform Engineering

## 1. Overview
### Existing
The current OrderWorkflow processes orders as a single unit, with no support for partial shipments. It transitions through states like RECEIVED, VALIDATING, VALIDATED, PROVISIONING, PROVISIONED, DISPATCHING, DISPATCHED, and COMPLETED, with no intermediate partial states.

### Proposed
The new OrderWorkflow will support partial shipments by introducing shipment groups. The overall order state will transition to PARTIALLY_DISPATCHED until all groups are dispatched. A new state machine for shipment groups will be nested under the order workflow, with states like PENDING, PROVISIONED, DISPATCHED, DELIVERED, CANCELLED, or FAILED. The companion diagram will be order-state-machine-partial-shipment.mmd.

## 2. Why Temporal
### Existing
Temporal is used for its durable execution, automatic retries, and compensation support, ensuring no silent failures and maintaining an auditable state.

### Proposed
No change. Temporal's capabilities remain essential for handling partial shipments with idempotent activities, retries, and compensation logic.

## 3. High-Level Architecture
### Existing
The architecture involves an API Gateway, Temporal Server, and Worker Pool. Activities interact with external services like Inventory and Carriers.

### Proposed
The architecture remains largely the same, with adjustments in the Worker Pool to handle fan-out/fan-in for shipment groups and additional error handling for group-level failures.

## 4. Workflow Design
### 4.1 State Machine
#### Existing
The current state machine transitions through RECEIVED → VALIDATING → VALIDATED → PROVISIONING → PROVISIONED → DISPATCHING → DISPATCHED → COMPLETED, with terminal states REJECTED and CANCELLED. See order-state-machine.mmd.

#### Proposed
New states: PARTIALLY_PROVISIONED, PARTIALLY_DISPATCHED. Sub-state-machine for shipment groups: PENDING → PROVISIONED → DISPATCHED → DELIVERED/CANCELLED/FAILED. Diagram: order-state-machine-partial-shipment.mmd.

### 4.2 Activities
#### Existing
Activities: capture_order, validate_order, provision_order, dispatch_order, compensate_provisioning, compensate_dispatch. See TDD-ORD-001 §4.2.

#### Proposed
New/Changed Activities:
| Activity       | Purpose                                  | Idempotency Strategy       | Retry Policy |
|----------------|------------------------------------------|---------------------------|--------------|
| provision_group| Provision a shipment group               | Order ID + Group ID       | 5 attempts   |
| dispatch_group | Dispatch a shipment group               | Tracking Number          | 5 attempts   |
| compensate_group_provision | Compensate a group’s provisioning | Order ID + Group ID       | 3 attempts   |
| consolidate_complete | Generate final invoice               | Order ID                 | 2 attempts   |

### 4.3 Saga / Compensation Logic
#### Existing
Saga compensates in reverse order of completion. See TDD-ORD-001 §4.3.

#### Proposed
Saga pseudo-code:
for group in shipment_groups:
    try:
        provision_group(group)
        dispatch_group(group)
    except:
        compensate_group_provision(group)
        raise
**After all groups or on cancellation:**
if any_group_dispatched:
    compensate_dispatch_unshipped()
consolidate_complete()

### 4.4 Idempotency Keys
#### Existing
Activities use idempotency keys (e.g., order_id for provision_order) to prevent duplicate side effects. See TDD-ORD-001 §4.4 and order_activities.py.

#### Proposed
Add per-shipment-group idempotency keys for provision_group and dispatch_group activities to ensure no duplicate shipments. Update retry policies for group-level activities.

### 4.5 Signals & Queries
#### Existing
Signals: cancel_order, delivery_confirmed. Queries: get_status returns OrderState. See order_workflow.py.

#### Proposed
Extend get_status to include shipment_group_statuses. Add signal cancel_shipment_group with group_id parameter.

### 4.6 Timeouts & SLAs
#### Existing
Timeouts defined in TDD-ORD-001 §4.6 (e.g., PROVISION_TIMEOUT = 60s).

#### Proposed
Add timeouts for per-group activities (e.g., PROVISION_GROUP_TIMEOUT = 30s, DISPATCH_GROUP_TIMEOUT = 90s).

### 4.7 Handling Delivery Wait Time
#### Existing
Handled via continue_as_new in TDD-ORD-001 §4.7 for long backorders.

#### Proposed
Implement per-group continue_as_new with independent wait durations to avoid blocking the entire order.

## 5. Data Contracts
### Existing
The existing data contracts include `ProvisioningResult` and `DispatchResult` as single values, not lists, in `src/shared/types.py`. The `OrderState` enum in the same module does not have `PARTIALLY_PROVISIONED` or `PARTIALLY_DISPATCHED` states.

### Proposed
```python
from dataclasses import dataclass, field
from enum import Enum

class OrderStatus(Enum):
    # ... existing statuses ...
    PARTIALLY_PROVISIONED = "PARTIALLY_PROVISIONED"
    PARTIALLY_DISPATCHED = "PARTIALLY_DISPATCHED"

class ShipmentGroup:
    def __init__(self, group_id: str, line_items: list, status: str):
        self.group_id = group_id
        self.line_items = line_items
        self.status = status
        self.tracking_numbers = []

class ProvisioningResult:
    # ... existing fields ...
    shipment_group_id: str = field(default="")

class DispatchResult:
    # ... existing fields ...
    shipment_group_id: str = field(default="")
    tracking_number: str = field(default="")

class OrderState:
    # ... existing fields ...
    provisioning_results: list[ProvisioningResult] = field(default_factory=list)
    dispatch_results: list[DispatchResult] = field(default_factory=list)
    shipment_groups: list[ShipmentGroup] = field(default_factory=list)
```

## 6. Observability
### Existing
Observability relies on Temporal's built-in logging and the `get_status` query, which only returns the overall order status.

### Proposed
Enhance logging to include shipment group IDs in all activity logs. Update `get_status` to return a list of shipment group statuses alongside the overall order status, e.g., `{'overall_status': OrderStatus.PARTIALLY_DISPATCHED, 'groups': [{'id': 'group1', 'status': 'DISPATCHED'}, ...]}'.

## 7. Testing Strategy
### Existing
Test cases (TC-order-workflow.xlsx) do not cover partial shipment scenarios.

### Proposed
Update TC-06, TC-09, TC-10 to include partial shipment group failures and successes. Add new test cases: TC-18 (happy path with multiple groups), TC-19 (cancellation of a single group), TC-20 (compensation for a failed group).

## 8. Open Items / Future Work
### Existing
No open items as per the last update.

### Proposed
Open Items:
1. **Invoicing Decision**: Await Finance's final decision on consolidated vs. itemized invoices for partial shipments (Owner: Finance).
2. **Versioning Strategy**: Decide on workflow versioning for backward compatibility (Owner: Engineering).

## Diagrams Needed
- order-state-machine-partial-shipment.mmd

## Sources
- `Business_Docs/business-requirements/BRD-order-lifecycle-management.docx` — lines 1-60
- `Business_Docs/diagrams/system-flow-diagram.md`
- `Business_Docs/epics/EPIC-001-order-lifecycle-management.docx` — lines 1-58
- `Business_Docs/technical-design/TDD-order-workflow-temporal.docx` — lines 1-60, lines 61-78
- `Business_Docs/test-cases/TC-order-workflow.xlsx`
- `Business_Docs/test-cases/TP-order-workflow-test-plan.docx` — lines 1-60
- `Business_Docs/user-stories/US-002-validate-order.docx`
- `Business_Docs/user-stories/US-004-dispatch-order.docx`
- `existing_Codebase/activities/order_activities.py` — lines 97-107
- `existing_Codebase/shared/types.py`
- `existing_Codebase/workflows/order_workflow.py` — lines 1-112, lines 57-243
- `tests/test_order_workflow.py`
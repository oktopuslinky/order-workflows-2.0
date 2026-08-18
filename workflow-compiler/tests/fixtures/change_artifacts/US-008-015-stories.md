# User Stories — EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Linked BCR:** BCR-001

**Stories:** 8

> Retrieval coverage 66% — terms not found in the knowledge base: item, parent, partially, input, report, but, entire, includ, support, customer, ship, overall

## US-008: Split Order into Shipment Groups Based on Availability

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Status:** Proposed

**Story Points:** 8

**Implements:** BCR-01-01

### Story

As a Fulfilment Operator
I want the system to automatically split an order into one or more shipment groups based on line-item availability at provisioning time
so that in-stock items can ship immediately while backordered items are handled separately

### Acceptance Criteria

- [ ] Given an order with both in-stock and backordered line items, the system splits the order into multiple shipment groups
- [ ] Given a shipment group with all items in stock, the system provisions and dispatches this group immediately
- [ ] Given a shipment group with backordered items, the system marks these for delayed shipment and does not block the in-stock group

### Notes

Implements BCR-01-01. See TDD-ORD-002 §4.1 and TC-18 for test coverage. Design Note: Utilize inventory API for real-time availability checks.

## US-009: Independently Provision and Dispatch Each Shipment Group

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Status:** Proposed

**Story Points:** 13

**Implements:** BCR-01-02

### Story

As a Fulfilment Operator
I want each shipment group to be independently provisioned, dispatched, and tracked with its own tracking number
so that each group’s status can be managed and communicated separately to the customer

### Acceptance Criteria

- [ ] Given a shipment group is provisioned, the system assigns a unique tracking number
- [ ] Given a dispatch failure in one shipment group, the system compensates only that group without affecting others
- [ ] Given all shipment groups are dispatched, the parent order status updates to PARTIALLY_DISPATCHED

### Notes

Implements BCR-01-02. See TDD-ORD-002 §4.2 and TC-18 for test coverage. Design Note: Leverage Temporal’s fan-out/fan-in pattern for parallel group processing.

## US-010: Update Order State Machine for Partial Shipments Rules

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Status:** Proposed

**Story Points:** 5

**Implements:** BCR-01-03

### Story

As a System Architect
I want the order state machine updated to include PARTIALLY_PROVISIONED and PARTIALLY_DISPATCHED states
so that the system accurately reflects partial shipment statuses

### Acceptance Criteria

- [ ] Given an order with multiple shipment groups, the system transitions to PARTIALLY_PROVISIONED after the first group is provisioned
- [ ] Given all shipment groups are provisioned, the system transitions to PARTIALLY_DISPATCHED until all are dispatched
- [ ] Given a shipment group fails provisioning, the system rolls back only that group

### Notes

Implements BCR-01-03. See updated order-state-machine-partial-shipment.mmd and TDD-ORD-002 §4.3 for details.

## US-011: Implement Partial Shipment Cancellation Logic

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Status:** Proposed

**Story Points:** 8

**Implements:** BCR-01-05

### Story

As a Fulfilment Operator
I want to cancel either the entire order or an individual shipment group
so that customers can adjust their orders flexibly while maintaining inventory integrity

### Acceptance Criteria

- [ ] Given an order with multiple shipment groups, when the operator cancels the entire order, then all shipment groups are cancelled and inventory is released
- [ ] Given an order with multiple shipment groups, when the operator cancels a single shipment group, then only that group is cancelled and its inventory is released
- [ ] Given a cancelled shipment group, the parent order transitions to PARTIALLY_DISPATCHED if other groups are dispatched
- [ ] Given a fully cancelled order, the parent order transitions to CANCELLED

### Notes

Implements BCR-01-05. See TDD-ORD-002 §4.3 and TC-10 for test coverage. Design Note: Compensation logic must handle partial reversals.

## US-012: Enhance Status Query for Shipment Group Visibility

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Status:** Proposed

**Story Points:** 3

**Implements:** BCR-01-06

### Story

As a Customer Support Agent
I want to query the status of an order and see the status of each shipment group
so that I can provide detailed updates to customers

### Acceptance Criteria

- [ ] Given an order with multiple shipment groups, when querying the order status, then the response includes each group's status
- [ ] Given a shipment group in DISPATCHED, when querying, then its tracking number is displayed
- [ ] Given an order in PARTIALLY_DISPATCHED, when querying, then the overall status and all group statuses are shown

### Notes

Implements BCR-01-06. See TDD-ORD-002 §5.2 and TC-12 for test coverage. Design Note: Extend get_status() to return a list of shipment group statuses.

## US-013: Update Invoicing for Consolidated Partial Shipments

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Status:** Proposed

**Story Points:** 5

**Implements:** BCR-01-04

### Story

As a Finance System
I want to generate a single consolidated invoice once all shipment groups of an order are delivered
so that the customer receives one invoice for the entire order

### Acceptance Criteria

- [ ] Given all shipment groups are delivered, when the order completes, then a single invoice is generated
- [ ] Given a partial shipment order, when any group is still pending, then no invoice is generated
- [ ] Given an invoice for a partial shipment order, when all groups are delivered, then the invoice includes all items

### Notes

Implements BCR-01-04. See TDD-ORD-002 §4.5 and TC-01 for test coverage. Design Note: Trigger invoice on final delivery confirmation.

## US-014: Ensure Backward Compatibility for Existing Orders

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Status:** Proposed

**Story Points:** 5

**Implements:** BCR-01-01

### Story

As a Fulfillment Operator
I want the system to continue processing existing single-shipment orders without interruption
so that in-flight orders are not affected by the new partial shipment logic

### Acceptance Criteria

- [ ] Given an in-flight order in the old single-shipment workflow, when the new partial shipment logic is deployed, then the order completes under the old logic
- [ ] Given a new order started after deployment, when it has multiple line items, then the system splits it into shipment groups

### Notes

Implements BCR-01-01. See TDD-ORD-002 §4.1 and TC-18 for test coverage. Design Note: Versioning will be handled via Temporal's workflow.patched() for backward compatibility.

## US-015: Develop Comprehensive Test Plan for Partial Shipments

**Epic:** EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Status:** Proposed

**Story Points:** 8

**Implements:** BCR-01-06

### Story

As a QA Engineer
I want a comprehensive test plan that covers all partial shipment scenarios
so that the partial shipment feature is thoroughly validated

### Acceptance Criteria

- [ ] Given the test plan, when all test cases are executed, then 100% pass rate is achieved for happy path and edge cases
- [ ] Given a shipment group cancellation scenario, when the test is run, then the system correctly compensates and updates the parent order status

### Notes

Extends TC-order-workflow.xlsx. See TP-ORD-002 for the updated plan. Design Note: Test doubles will be used for shipment group simulations.


## Sources

- `Business_Docs/business-requirements/BRD-order-lifecycle-management.docx` — lines 1-60
- `Business_Docs/diagrams/system-flow-diagram.md`
- `Business_Docs/epics/EPIC-001-order-lifecycle-management.docx` — lines 1-58
- `Business_Docs/technical-design/TDD-order-workflow-temporal.docx` — lines 1-60, lines 61-78
- `Business_Docs/test-cases/TP-order-workflow-test-plan.docx`
- `Business_Docs/user-stories/US-002-validate-order.docx`
- `Business_Docs/user-stories/US-003-provision-order.docx` — lines 1-15
- `Business_Docs/user-stories/US-004-dispatch-order.docx`
- `Business_Docs/user-stories/US-005-complete-order.docx` — lines 1-15
- `existing_Codebase/activities/order_activities.py`
- `existing_Codebase/shared/types.py`
- `existing_Codebase/workflows/order_workflow.py` — lines 1-112, lines 57-243
- `tests/test_order_workflow.py` — lines 172-193
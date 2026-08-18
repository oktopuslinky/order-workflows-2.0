# EPIC-002 — Partial Shipment Support (Multi-Line Orders)

**Epic Owner:** VP, Supply Chain Operations

**Linked BRD:** BRD-ORD-001

**Linked BCR:** BCR-001

**Status:** Proposed

**Target Release:** R2026.4

> Retrieval coverage 65% — terms not found in the knowledge base: item, parent, partially, input, report, but, entire, includ, support, customer, ship, overall

## Epic Statement

As the Enterprise Order Management platform, we need to support partial shipments for multi-line orders, so that in-stock items ship immediately while backordered items ship separately once replenished, improving customer satisfaction and reducing average delivery time.

## Business Value

- Reduce average delivery time for non-backordered items by 30-40%
- Align with competitor capabilities
- Decrease customer complaints due to delayed shipments

## In-Scope Capabilities

- Split Order into Shipment Groups (Provisioning Stage)
- Independent Provisioning and Dispatch per Shipment Group (Provisioning & Dispatch Stages)
- Update Order Status to PARTIALLY_DISPATCHED (Dispatch Stage)
- Generate Consolidated Invoice upon Full Completion (Completion Stage)
- Enable Cancellation of Entire Order or Individual Shipment Group (All Stages)
- Enhance Status Query to Include Shipment Group Details (Status Query API)

## Definition of Done

- [ ] Passing all new partial-shipment test cases in TC-order-workflow.xlsx
- [ ] Successfully updating order-state-machine.mmd and adding order-state-machine-partial-shipment.mmd
- [ ] Confirming idempotency in shipment group creation
- [ ] Verifying compensation logic for partial shipments
- [ ] Validating single consolidated invoice generation for partial shipments
- [ ] Ensuring backward compatibility for in-flight single-shipment orders

## Story Map

| Story ID | Title | Status | Doc |
| --- | --- | --- | --- |
| US-008 | Split Order into Shipment Groups Based on Availability | Proposed |  |
| US-009 | Independently Provision and Dispatch Each Shipment Group | Proposed |  |
| US-010 | Update Order State Machine for Partial Shipments | Proposed |  |
| US-011 | Implement Partial Shipment Cancellation Logic | Proposed |  |
| US-012 | Enhance Status Query for Shipment Group Visibility | Proposed |  |
| US-013 | Update Invoicing for Consolidated Partial Shipments | Proposed |  |
| US-014 | Ensure Backward Compatibility for Existing Orders | Proposed |  |
| US-015 | Develop Comprehensive Test Plan for Partial Shipments | Proposed |  |

## Non-Functional Requirements

| NFR | Target |
| --- | --- |
| Idempotency in Shipment Group Creation | No duplicate shipments |
| Backward Compatibility | No impact on in-flight orders |
| Performance | Less than 5% increase in processing time |

## Dependencies

- Inventory Service
- Payment Gateway
- Finance Team (for invoicing decision)

## Risks

| Risk | Mitigation |
| --- | --- |
| Backward Compatibility Issues | Versioning strategy or separate workflow for new orders |
| Increased Workflow Complexity | Design review and targeted testing |
| Invoicing Errors | Finance team validation and automated tests |

## Sources

- `Business_Docs/business-requirements/BRD-order-lifecycle-management.docx` — lines 1-60
- `Business_Docs/epics/EPIC-001-order-lifecycle-management.docx` — lines 1-58
- `Business_Docs/technical-design/TDD-order-workflow-temporal.docx` — lines 1-60, lines 61-78
- `Business_Docs/test-cases/TP-order-workflow-test-plan.docx`
- `Business_Docs/user-stories/US-001-capture-order.docx`
- `Business_Docs/user-stories/US-002-validate-order.docx`
- `Business_Docs/user-stories/US-003-provision-order.docx` — lines 1-15
- `Business_Docs/user-stories/US-004-dispatch-order.docx` — lines 1-15
- `Business_Docs/user-stories/US-005-complete-order.docx`
- `existing_Codebase/activities/order_activities.py`
- `existing_Codebase/shared/types.py`
- `existing_Codebase/workflows/order_workflow.py` — lines 1-112, lines 57-243
- `tests/test_order_workflow.py`
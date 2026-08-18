# Impact Analysis — BCR-001 — Partial Shipment Support for Multi-Line Orders

**Change Request:** BCR-001

**Target Workflow:** OrderWorkflow (EPIC-001 / TDD-ORD-001)

**Knowledge Base:** Order lifecycle (Existing_KG)

**Status:** Draft

> Retrieval coverage 73% — terms not found in the knowledge base: item, parent, partially, input, report, entire, but, support, includ, customer, ship, overall

## 1. Change Summary

BCR-001 introduces structural changes to support partial shipments for multi-line orders, altering the workflow's state machine, data contracts, and compensation logic. The change is structural due to the addition of new states (PARTIALLY_PROVISIONED, PARTIALLY_DISPATCHED) and a nested shipment-group sub-state-machine. The overall approach involves updating the OrderWorkflow to handle multiple shipment groups independently while maintaining the parent order's status and invoice generation.

## 2. Requirements Assessment

| Req ID | Requirement | Impact |
| --- | --- | --- |
| BCR-01-01 | Split order into shipment groups based on line-item availability | OrderWorkflow, ProvisioningResult, DispatchResult, US-003, US-004, TC-01, TC-06 |
| BCR-01-02 | Independently provision, dispatch, and track each shipment group | OrderWorkflow, ProvisioningResult, DispatchResult, TC-06, TC-07, TC-10 |
| BCR-01-03 | Parent order remains PARTIALLY_DISPATCHED until all groups are dispatched | OrderState, OrderWorkflow, TC-12, TC-04 |
| BCR-01-04 | Parent order completes only after all groups are delivered and invoiced | complete_order, US-005, BR-06, TC-01, TC-17 |
| BCR-01-05 | Support cancellation of entire order or individual shipment group | OrderWorkflow, TC-08, TC-09, TC-10, BR-07 |
| BCR-01-06 | Status query returns per-shipment-group and overall order status | get_status, US-007, BR-09, TC-12 |

## 3. Affected Components

| Kind | Component | Change | Rationale | KG reference |
| --- | --- | --- | --- | --- |
| module | existing_Codebase/workflows/order_workflow.py | modify | Update state machine and workflow logic | fn:existing_Codebase/workflows/order_workflow.py:OrderWorkflow |
| class | OrderState | modify | Add PARTIALLY_PROVISIONED and PARTIALLY_DISPATCHED states | fn:existing_Codebase/shared/types.py:OrderState |
| class | ProvisioningResult | modify | Change to list[ProvisioningResult] for shipment groups | fn:existing_Codebase/shared/types.py:ProvisioningResult |
| class | DispatchResult | modify | Change to list[DispatchResult] for shipment groups | fn:existing_Codebase/shared/types.py:DispatchResult |
| function | provision_order | modify | Fan out to handle multiple shipment groups | fn:existing_Codebase/activities/order_activities.py:provision_order |
| function | dispatch_order | modify | Fan out to handle multiple shipment groups | fn:existing_Codebase/activities/order_activities.py:dispatch_order |
| function | compensate_provisioning | modify | Handle per shipment group compensation | fn:existing_Codebase/activities/order_activities.py:compensate_provisioning |
| function | compensate_dispatch | modify | Handle per shipment group compensation | fn:existing_Codebase/activities/order_activities.py:compensate_dispatch |
| document | order-state-machine.mmd | modify | Update state machine diagram | doc:Business_Docs/diagrams/mermaid/order-state-machine.mmd |
| document | order-state-machine-partial-shipment.mmd | add | New diagram for partial shipment state machine |  |
| story | US-003 | modify | Provisioning now handles multiple groups | US-003 |
| story | US-004 | modify | Dispatching now handles multiple groups | US-004 |
| story | US-005 | modify | Completion logic updated for multiple groups | US-005 |
| test_case | TC-01 | modify | Update for partial shipment happy path | TC-01 |
| test_case | TC-06 | modify | Update for group-level dispatch failure | TC-06 |
| test_case | TC-10 | modify | Update for cancellation of a group | TC-10 |
| test_case | TC-12 | modify | Update status query for group status | TC-12 |
| test_plan | TP-order-workflow-test-plan.docx | modify | Extend scope for partial shipment scenarios | doc:Business_Docs/test-cases/TP-order-workflow-test-plan.docx |
| epic | EPIC-002 | add | New epic for partial shipment capability |  |
| requirement | BR-06 | modify | Update completion criteria for multiple groups | BR-06 |
| requirement | BR-09 | modify | Status query now includes group status | BR-09 |
| diagram | system-flow-diagram.md | modify | Update to reflect partial shipment workflow | doc:Business_Docs/diagrams/system-flow-diagram.md |
| document | Business_Docs/technical-design/TDD-order-workflow-temporal.docx | modify | Update TDD to reflect new partial shipment logic and state machine changes | doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| document | Business_Docs/user-stories/US-005-complete-order.docx | modify | Update completion criteria to account for consolidated invoice and all shipment groups | doc:Business_Docs/user-stories/US-005-complete-order.docx |
| test_case | TC-09 | modify | Update test case to validate per-group compensation and cancellation logic | TC-09 |
| class | CompletionResult | modify | Update to track shipment group completion statuses | fn:existing_Codebase/shared/types.py:CompletionResult |
| function | complete_order | modify | Modify to generate consolidated invoice after all shipment groups are delivered | fn:existing_Codebase/activities/order_activities.py:complete_order |
| document | Business_Docs/test-cases/TC-order-workflow.xlsx | add | Add new test cases for partial shipment scenarios (e.g., mixed cancel, group-level failures) | doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| requirement | BR-07 | verify | Ensure cancellation logic works for individual shipment groups and the entire order | BR-07 |
| test_case | TC-16 | verify | Verify SLA alerts accommodate multiple shipment groups | TC-16 |
| epic | EPIC-001 | modify | Update story map or raise EPIC-002 | EPIC-001 |
| test_plan | TP-ORD-001 | modify | Remove out-of-scope line, extend plan | doc:Business_Docs/test-cases/TP-order-workflow-test-plan.docx |
| test_plan | TP-ORD-002 | add | New test plan for partial shipment | |
| test_plan | TP-ORD-001 §3.2 | modify | Remove 'partial shipment ... until BCR-001' | doc:Business_Docs/test-cases/TP-order-workflow-test-plan.docx |
| test_plan | TP-ORD-002 | add | New test plan for partial shipment logic | |

## 4. Impact on Existing Design

- Validate partial shipment logic against inventory allocation edge cases
- Ensure idempotency in shipment group creation to prevent duplicates
- Update worker registration to handle increased workflow complexity
- Design test doubles for shipment group scenarios in unit tests

## 5. Risks & Assumptions

- Backward compatibility issues with in-flight orders using the old single-shipment model
- Increased complexity in fan-out/fan-in compensation logic may lead to bugs
- Invoicing errors if group status and parent order status are not correctly synchronized

## 6. Open Decisions

- [ ] Finance: Finalize invoicing approach for partial shipments (consolidated vs. itemized)
- [ ] Engineering: Decide on the approach to versioning for backward compatibility
- [ ] Product: Determine the UI approach for displaying multiple tracking numbers to customers

## Appendix A — Knowledge-graph traversal (deterministic)

| Hops | Type | Node | Path | Via |
| --- | --- | --- | --- | --- |
| 0 | Class | DispatchResult | existing_Codebase/shared/types.py | seed |
| 0 | Class | OrderState | existing_Codebase/shared/types.py | seed |
| 0 | Class | ProvisioningResult | existing_Codebase/shared/types.py | seed |
| 0 | Class | OrderWorkflow | existing_Codebase/workflows/order_workflow.py | seed |
| 0 | Document | order-state-machine.mmd | Business_Docs/diagrams/mermaid/order-state-machine.mmd | seed |
| 0 | Document | TDD-order-workflow-temporal.docx | Business_Docs/technical-design/TDD-order-workflow-temporal.docx | seed |
| 0 | Document | US-002-validate-order.docx | Business_Docs/user-stories/US-002-validate-order.docx | seed |
| 0 | Document | US-005-complete-order.docx | Business_Docs/user-stories/US-005-complete-order.docx | seed |
| 0 | Epic | EPIC-001 |  | seed |
| 0 | Requirement | BCR-001 |  | seed |
| 1 | Class | CompletionResult | existing_Codebase/shared/types.py | RELATES_TO ← chk:existing_Codebase/shared/types.py:007 |
| 1 | Class | LineItem | existing_Codebase/shared/types.py | RELATES_TO ← chk:existing_Codebase/shared/types.py:001 |
| 1 | Class | OrderStatus | existing_Codebase/shared/types.py | RELATES_TO ← chk:existing_Codebase/shared/types.py:000 |
| 1 | Function | compensate_dispatch | existing_Codebase/activities/order_activities.py | RELATES_TO ← chk:existing_Codebase/activities/order_activities.py:008 |
| 1 | Function | complete_order | existing_Codebase/activities/order_activities.py | RELATES_TO ← chk:existing_Codebase/activities/order_activities.py:009 |
| 1 | Function | dispatch_order | existing_Codebase/activities/order_activities.py | RELATES_TO ← chk:existing_Codebase/activities/order_activities.py:007 |
| 1 | Function | provision_order | existing_Codebase/activities/order_activities.py | RELATES_TO ← chk:existing_Codebase/activities/order_activities.py:005 |
| 1 | Function | main | existing_Codebase/starter.py | RELATES_TO ← chk:existing_Codebase/starter.py:000 |
| 1 | Document | BRD-order-lifecycle-management.docx | Business_Docs/business-requirements/BRD-order-lifecycle-management.docx | RELATES_TO ← BCR-001 |
| 1 | Document | EPIC-001-order-lifecycle-management.docx | Business_Docs/epics/EPIC-001-order-lifecycle-management.docx | RELATES_TO ← BCR-001 |
| 1 | Document | TC-order-workflow.xlsx | Business_Docs/test-cases/TC-order-workflow.xlsx | RELATES_TO ← EPIC-001 |
| 1 | Document | TP-order-workflow-test-plan.docx | Business_Docs/test-cases/TP-order-workflow-test-plan.docx | RELATES_TO ← BCR-001 |
| 1 | Document | US-001-capture-order.docx | Business_Docs/user-stories/US-001-capture-order.docx | RELATES_TO ← EPIC-001 |
| 1 | Document | US-003-provision-order.docx | Business_Docs/user-stories/US-003-provision-order.docx | RELATES_TO ← EPIC-001 |
| 1 | Document | US-004-dispatch-order.docx | Business_Docs/user-stories/US-004-dispatch-order.docx | RELATES_TO ← EPIC-001 |
| 1 | UserStory | US-002 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-002-validate-order.docx |
| 1 | UserStory | US-005 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-005-complete-order.docx |
| 1 | TestCase | TC-01 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-005-complete-order.docx |
| 1 | TestCase | TC-02 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-002-validate-order.docx |
| 1 | TestCase | TC-03 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-002-validate-order.docx |
| 1 | TestCase | TC-04 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-002-validate-order.docx |
| 1 | TestCase | TC-11 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-005-complete-order.docx |
| 1 | TestCase | TC-14 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-005-complete-order.docx |
| 1 | TestCase | TC-17 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-002-validate-order.docx |
| 1 | TestCase | TC-order-workflow.xlsx |  | RELATES_TO ← doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| 1 | Requirement | BCR-001-partial-shipment-support.docx |  | RELATES_TO ← doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| 1 | Requirement | BR-02 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-002-validate-order.docx |
| 1 | Requirement | BR-03 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-002-validate-order.docx |
| 1 | Requirement | BR-06 |  | RELATES_TO ← doc:Business_Docs/user-stories/US-005-complete-order.docx |
| 1 | Requirement | BR-07 |  | RELATES_TO ← doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| 1 | Requirement | BR-09 |  | RELATES_TO ← doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| 1 | Requirement | BR-10 |  | RELATES_TO ← doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| 1 | Requirement | BR-11 |  | RELATES_TO ← doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| 1 | Requirement | BR-12 |  | RELATES_TO ← doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| 1 | Service | corpus | . | DOCUMENTED_BY ← doc:Business_Docs/diagrams/mermaid/order-state-machine.mmd |
| 1 | Service | Order Lifecycle Management |  | DOCUMENTED_BY ← doc:Business_Docs/technical-design/TDD-order-workflow-temporal.docx |
| 1 | Service | Order Lifecycle Service |  | DOCUMENTED_BY ← doc:Business_Docs/diagrams/mermaid/order-state-machine.mmd |
| 2 | Module | existing_Codebase/activities/order_activities.py | existing_Codebase/activities/order_activities.py | DOCUMENTED_BY ← svc:proc:order-lifecycle-service |
| 2 | Module | existing_Codebase/shared/types.py | existing_Codebase/shared/types.py | DOCUMENTED_BY ← svc:proc:order-lifecycle-service |
| 2 | Module | existing_Codebase/starter.py | existing_Codebase/starter.py | DOCUMENTED_BY ← svc:proc:order-lifecycle-service |
| 2 | Module | existing_Codebase/worker.py | existing_Codebase/worker.py | DOCUMENTED_BY ← svc:proc:order-lifecycle-service |
| 2 | Module | existing_Codebase/workflows/order_workflow.py | existing_Codebase/workflows/order_workflow.py | DOCUMENTED_BY ← svc:proc:order-lifecycle-service |
| 2 | Module | tests/test_order_workflow.py | tests/test_order_workflow.py | DOCUMENTED_BY ← svc:proc:order-lifecycle-service |
| 2 | Document | order-sequence.mmd | Business_Docs/diagrams/mermaid/order-sequence.mmd | DOCUMENTED_BY ← svc:. |
| 2 | Document | system-architecture.mmd | Business_Docs/diagrams/mermaid/system-architecture.mmd | DOCUMENTED_BY ← svc:. |
| 2 | Document | system-flow-diagram.md | Business_Docs/diagrams/system-flow-diagram.md | DOCUMENTED_BY ← svc:. |
| 2 | Document | README.md | README.md | DOCUMENTED_BY ← svc:. |
| 2 | Document | requirements.txt | requirements.txt | DOCUMENTED_BY ← svc:. |
| 2 | Epic | EPIC-001-A |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | Epic | EPIC-001-order-lifecycle-management.docx |  | RELATES_TO ← doc:Business_Docs/business-requirements/BRD-order-lifecycle-management.docx |
| 2 | UserStory | US-001 |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-001-capture-order.docx |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-001..US-005 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | UserStory | US-002-validate-order.docx |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-003 |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-003-provision-order.docx |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-004 |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-004-dispatch-order.docx |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-005-complete-order.docx |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-006 |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | UserStory | US-007 |  | RELATES_TO ← doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx |
| 2 | TestCase | TC-05 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | TestCase | TC-06 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | TestCase | TC-07 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | TestCase | TC-08 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | TestCase | TC-09 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | TestCase | TC-10 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | TestCase | TC-12 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | TestCase | TC-13 |  | RELATES_TO ← doc:Business_Docs/test-cases/TC-order-workflow.xlsx |
| 2 | TestCase | TC-15 |  | RELATES_TO ← doc:Business_Docs/test-cases/TP-order-workflow-test-plan.docx |
| 2 | TestCase | TC-16 |  | RELATES_TO ← doc:Business_Docs/test-cases/TP-order-workflow-test-plan.docx |
| 2 | Requirement | BR-01 |  | RELATES_TO ← doc:Business_Docs/business-requirements/BRD-order-lifecycle-management.docx |
| 2 | Requirement | BR-04 |  | RELATES_TO ← doc:Business_Docs/business-requirements/BRD-order-lifecycle-management.docx |
| 2 | Requirement | BR-05 |  | RELATES_TO ← doc:Business_Docs/business-requirements/BRD-order-lifecycle-management.docx |
| 2 | Requirement | BR-08 |  | RELATES_TO ← doc:Business_Docs/business-requirements/BRD-order-lifecycle-management.docx |
| 2 | Config | requirements.txt | requirements.txt | READS_CONFIG ← svc:. |

## Sources

- `Business_Docs/business-requirements/BRD-order-lifecycle-management.docx` — lines 1-60
- `Business_Docs/diagrams/system-flow-diagram.md`
- `Business_Docs/epics/EPIC-001-order-lifecycle-management.docx` — lines 1-58
- `Business_Docs/technical-design/TDD-order-workflow-temporal.docx` — lines 1-60, lines 61-78
- `Business_Docs/test-cases/TC-order-workflow.xlsx`
- `Business_Docs/test-cases/TP-order-workflow-test-plan.docx` — lines 1-60
- `Business_Docs/user-stories/US-001-capture-order.docx`
- `Business_Docs/user-stories/US-002-validate-order.docx`
- `Business_Docs/user-stories/US-003-provision-order.docx` — lines 1-15
- `Business_Docs/user-stories/US-004-dispatch-order.docx` — lines 1-15
- `Business_Docs/user-stories/US-005-complete-order.docx`
- `existing_Codebase/activities/order_activities.py`
- `existing_Codebase/shared/types.py`
- `existing_Codebase/workflows/order_workflow.py` — lines 1-112, lines 57-243
- `tests/test_order_workflow.py` — lines 172-193
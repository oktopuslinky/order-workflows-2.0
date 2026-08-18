# Impact Analysis — BCR-001 — Partial Shipment Support for Multi-Line Orders
**Change Request:** BCR-001
**Target Workflow:** OrderWorkflow (EPIC-001 / TDD-ORD-001)
**Knowledge Base:** Order lifecycle (Existing_KG)
**Status:** Draft > Retrieval coverage 73% — terms not found in the knowledge base: item, parent, partially, input, report, entire, but, support, includ, customer, ship, overall
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
| module | existing_CodeBase/workflows/order_workflow.py | modify | Update state machine and workflow logic | fn:existing_CodeBase/workflows/order_workflow.py:OrderWorkflow |
| class | OrderState | modify | Add PARTIALLY_PROVISIONED and PARTIALLY_DISPATCHED states | fn:existing_CodeBase/shared/types.py:OrderState |
| class | ProvisioningResult | modify | Change to list[ProvisioningResult] for shipment groups | fn:existing_CodeBase/shared/types.py:ProvisioningResult |
| class | DispatchResult | modify | Change to list[DispatchResult] for shipment groups | fn:existing_CodeBase/shared/types.py:DispatchResult |
| function | provision_order | modify | Fan out to handle multiple shipment groups | fn:existing_CodeBase/activities/order_activities.py:provision_order |
| function | dispatch_order | modify | Fan out to handle multiple shipment groups | fn:existing_CodeBase/activities/order_activities.py:dispatch_order |
| function | compensate_provisioning | modify | Handle per shipment group compensation | fn:existing_CodeBase/activities/order_activities.py:compensate_provisioning |
| function | compensate_dispatch | modify | Handle per shipment group compensation | fn:existing_CodeBase/activities/order_activities.py:compensate_dispatch |
| document | order-state-machine.mmd | modify | Update state machine diagram | doc:Business_Docs/diagrams/mermaid/order-state-machine.mmd |
| document | order-state-machine-partial-shipment.mmd | add | New diagram for partial shipment state machine | |
| epic | EPIC-001 | modify | Update story map to point at EPIC-002 | EPIC-001 |
| test_plan | TP-ORD-001 | modify | Remove out-of-scope line, extend plan | doc:Business_Docs/test-cases/TP-ORD-001.docx |
| ... | ... | ... | ... | ...
| epic | EPIC-002 | add | New epic for partial shipment capability | |
| ... | ... | ... | ... | ...
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
| 0 | Class | DispatchResult | existing_CodeBase/shared/types.py | seed |
| ... | ... | ... | ... | ...
## Sources
- `Business_Docs/business-requirements/BRD-order-lifecycle-management.docx` — lines 1-60
- ...
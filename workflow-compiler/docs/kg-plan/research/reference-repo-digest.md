# Digest — Intelligent_Workflow_Builder (branch `Sample_Doc_Code`)

Repo clone: `scratchpad/iwb` (single commit `8d193f2 Updated`). Converted text of every .docx/.xlsx: `scratchpad/iwb_txt/<name>.txt`.
The README calls it a "sample / reference repository" for an enterprise Order Capture → Validation → Provisioning → Dispatching → Completion process on Temporal (Python SDK), meant to double as onboarding template / "context for AI coding agents".

NOTE on paths: the README describes a layout `docs/…`, `src/…`, `tests/`, `business-change/` — but the actual checkout is `Existing_KG/Business_Docs/…`, `Existing_KG/existing_Codebase/…`, `Existing_KG/tests/`, `New_business-change/`. All in-doc cross-references (and Python imports `from src.…`) use the README layout, not the on-disk layout.

---

## 1. Inventory (bytes; words for docs / lines for code)

| Path (under `iwb/`) | Size | Notes |
|---|---|---|
| Existing_KG/README.md | 4,598 B | Repo overview, layout tree, how pieces connect, run/test commands |
| Existing_KG/requirements.txt | 58 B | `temporalio>=1.7.0`, `pytest>=8.0.0`, `pytest-asyncio>=0.23.0` |
| Existing_KG/Business_Docs/business-requirements/BRD-order-lifecycle-management.docx | 12,215 B / 817 words | BRD-ORD-001 v1.2 Approved |
| Existing_KG/Business_Docs/epics/EPIC-001-order-lifecycle-management.docx | 11,320 B / 538 words | EPIC-001, story map US-001..US-007 |
| Existing_KG/Business_Docs/technical-design/TDD-order-workflow-temporal.docx | 13,734 B / 1,115 words | TDD-ORD-001 v1.1 Approved |
| Existing_KG/Business_Docs/test-cases/TP-order-workflow-test-plan.docx | 13,087 B / 1,073 words | TP-ORD-001 v1.0 Approved |
| Existing_KG/Business_Docs/test-cases/TC-order-workflow.xlsx | 12,333 B / 2 sheets | 17 test cases + Summary sheet |
| Existing_KG/Business_Docs/user-stories/US-001-capture-order.docx | 9,527 B / 175 words | 3 pts, Done |
| Existing_KG/Business_Docs/user-stories/US-002-validate-order.docx | 9,444 B / 161 words | 5 pts, Done |
| Existing_KG/Business_Docs/user-stories/US-003-provision-order.docx | 9,478 B / 173 words | 5 pts, Done |
| Existing_KG/Business_Docs/user-stories/US-004-dispatch-order.docx | 9,559 B / 191 words | 8 pts, Done |
| Existing_KG/Business_Docs/user-stories/US-005-complete-order.docx | 9,400 B / 160 words | 3 pts, Done |
| Existing_KG/Business_Docs/diagrams/mermaid/order-state-machine.mmd | 1,363 B | stateDiagram-v2 |
| Existing_KG/Business_Docs/diagrams/mermaid/order-sequence.mmd | 1,403 B | sequenceDiagram happy path |
| Existing_KG/Business_Docs/diagrams/mermaid/system-architecture.mmd | 1,353 B | flowchart LR |
| Existing_KG/Business_Docs/diagrams/system-flow-diagram.md | 4,866 B | The 3 .mmd embedded verbatim in ```mermaid fences with headings 1/2/3 |
| Existing_KG/existing_Codebase/shared/types.py | 2,372 B / 98 lines | enums + dataclasses |
| Existing_KG/existing_Codebase/activities/order_activities.py | 6,787 B / 179 lines | 8 activities (mock bodies) |
| Existing_KG/existing_Codebase/workflows/order_workflow.py | 9,812 B / 243 lines | `OrderWorkflow` |
| Existing_KG/existing_Codebase/worker.py | 1,268 B / 55 lines | worker, TASK_QUEUE |
| Existing_KG/existing_Codebase/starter.py | 1,774 B / 57 lines | CLI starter |
| Existing_KG/existing_Codebase/{,shared,activities,workflows}/__init__.py | 0 B | empty |
| Existing_KG/tests/test_order_workflow.py | 8,199 B / 219 lines | 4 pytest tests |
| Existing_KG/tests/__init__.py | 0 B | |
| New_business-change/BCR-001-partial-shipment-support.docx | 11,591 B / 704 words | BCR-001, Proposed |

---

## 2. Existing system as documented

### 2.1 BRD — `BRD-ORD-001` "Enterprise Order Lifecycle Management — Capture to Completion" (v1.2, Approved, Owner: Order Management Product Team, Last Updated 2026-08-01)
- **1. Business Context**: fragmented point-to-point integrations (storefront/inventory/fulfillment/carrier) → orders "stuck", no single source of truth, manual Fulfillment↔Finance reconciliation, inconsistent retry/compensation. Need: single auditable enterprise-wide order workflow owning the order from capture to completed (delivered + invoiced).
- **2. Business Objectives** (table ID | Objective | Success Metric): BO-1 single system of record (100% orders queryable); BO-2 <0.1% manual intervention; BO-3 zero double-provision/double-ship; BO-4 15% cycle-time reduction in 2 quarters; BO-5 100% of cancellations correctly reverse completed steps.
- **3.1 In Scope**: capture from any channel; validation (inventory, payment auth, customer eligibility, fraud); provisioning (reserve inventory, pick/pack, warehouse); dispatch (carrier, label, hand-off, tracking#); completion (delivery confirmation, invoice, notification); cancellation/compensation at any stage prior to completion; status query API.
- **3.2 Out of Scope**: returns/refunds; **"Multi-warehouse split-shipment optimization (see business-change/BCR-001)"**; customer-facing tracking UI.
- **4. Stakeholders** (Role | Stakeholder | Interest): Business Sponsor = VP Supply Chain Operations; Product Owner = Order Mgmt Product Team; Engineering = Platform Engineering (Workflow Orchestration); Finance = Order-to-Cash; Customer Support = Support Ops; Compliance = Risk & Fraud.
- **5. High-Level Business Requirements** (Req ID | Requirement | Priority): BR-01 capture + unique order ID within 1s (Must); BR-02 validate inventory/payment/fraud before provisioning (Must); BR-03 reject with specific customer-communicable reason code (Must); BR-04 reserve only after validation, never twice (Must); BR-05 carrier + label after provisioning (Must); BR-06 Complete only after delivery confirmation + invoice (Must); BR-07 cancel pre-dispatch releases inventory (Must); BR-08 cancel post-dispatch → return-to-sender/recall (Should); BR-09 real-time status query (Must); BR-10 immutable audit trail 7 years (Must); BR-11 retry transient failures without duplicate side effects (Must); BR-12 alert Ops on SLA breach (Should).
- **6. Assumptions & Constraints**: downstream APIs idempotent / idempotency keys; exactly-once effect semantics for irreversible actions even under crashes; cloud-portable orchestration.
- **7. Related Documents**: EPIC-001, TDD, BCR-001 (with `docs/…` / `business-change/…` paths).

### 2.2 EPIC-001 "Order Lifecycle Management (Capture → Completion)" (Owner: Order Mgmt Product Team; Linked BRD BRD-ORD-001; Status: In Progress (Phase 1 Delivered); Target Release R2026.3)
- Epic Statement (As the Enterprise Order Management platform, we need a single durable workflow… retried or safely compensated).
- Business Value: no manual reconciliation; no silent-failure states; SOX audit trail; reusable orchestration pattern (returns, subscriptions, B2B bulk).
- In-Scope Capabilities: Capture; Validation (inventory, payment, fraud); Provisioning; Dispatch; Completion; Cancellation & Compensation; Status Query API; Operational Alerting on SLA breach.
- Definition of Done (☑/☐ checklist): ☑ passing all TC-order-workflow.xlsx cases; ☑ each stage an independently retryable Activity; ☑ cancellation reverses reversible side effects; ☑ audit trail; ☑ runbook + on-call alerting; ☐ load-tested 3x peak (EPIC-001-A); ☐ **Partial shipment support (moved to BCR-001)**.
- Story Map (Story ID | Title | Status | Doc): US-001 Capture Order (Done); US-002 Validate Order (Done); US-003 Provision Order (Done); US-004 Dispatch Order (Done); US-005 Complete Order (Done); **US-006 Cancel / Compensate Order (Done, "covered in TDD saga design; dedicated story planned for backlog grooming" — no docx)**; **US-007 Order Status Query API (Done, "implemented as a Temporal Query handler — see TDD §5.3" — no docx)**.
- NFRs (NFR | Target): Availability 99.95% capture & status APIs; Durability no state loss across crashes; Latency capture→validated p95 < 5s; Auditability 7 yrs; Idempotency no duplicate charge/reservation/dispatch.
- Dependencies: Inventory Service; Payment Gateway; Fraud/Risk Service; WMS; Carrier Aggregator API; Invoicing/Finance.
- Risks (Risk | Mitigation): carrier no idempotency → internal key + dedupe table; long backorder → continue-as-new; fraud latency → configurable timeout/retry + SLA alert.

### 2.3 User stories (all: Epic EPIC-001, Status Done; sections Story / Acceptance Criteria / Notes)
| ID | Title | Pts | Story (as/want/so that) | AC summary | Notes / traceability |
|---|---|---|---|---|---|
| US-001 | Capture Order | 3 | channel wants durable order_id immediately | valid OrderRequest starts OrderWorkflow, order_id ≤1s; duplicate order_id → no dup workflow, returns existing status; missing fields → sync validation error, no workflow; queryable via get_status() = RECEIVED | BR-01; order_id = Workflow ID → WorkflowExecutionAlreadyStarted idempotency |
| US-002 | Validate Order | 5 | workflow wants inventory/payment/fraud checks before reserving | all pass → VALIDATED; inventory fail → REJECTED INVENTORY_UNAVAILABLE fail-fast; payment declined → PAYMENT_DECLINED; fraud → FRAUD_HOLD + manual review; each check independently retryable | BR-02, BR-03; TDD §4.2; TC-02/03/04/17 |
| US-003 | Provision Order | 5 | reserve inventory + warehouse exactly once | success → PROVISIONED; retry dedupes on order_id; permanent fail → REJECTED PROVISIONING_FAILED, no compensation; cancel after → compensate_provisioning idempotent | BR-04; TDD §4.2/4.3; TC-05/09 |
| US-004 | Dispatch Order | 8 | carrier/label/hand-off exactly once | success → DISPATCHED; retry uses deterministic idempotency key (workflow.uuid4) → same shipment; permanent fail → compensate_provisioning + REJECTED DISPATCH_FAILED; cancel after dispatch → compensate_dispatch then compensate_provisioning | BR-05, BR-11; TDD §4.2/4.4; TC-06/07/10 |
| US-005 | Complete Order | 3 | wait for delivery, then invoice | delivery_confirmed signal → invoice → COMPLETED; invoice retry dedupes on order_id; continue_as_new after dispatch; cancel after COMPLETED = no-op logged in audit | BR-06; TDD §4.5/4.7; TC-01/11/14 |

### 2.4 TDD — `TDD-ORD-001` "Order Lifecycle Workflow — Temporal Implementation" (v1.1, Approved; Linked EPIC-001; Author Platform Engineering)
- **1. Overview**: single Temporal Workflow `OrderWorkflow`, each step an idempotent Activity; saga with reverse-order compensation.
- **2. Why Temporal** (Requirement (from BRD) | How Temporal satisfies it): BR-10 event history = audit; BR-11 RetryPolicy + idempotency keys; BR-09 Query handlers; BR-07/08 Signals (cancel_order); long-running → continue-as-new.
- **3. Architecture**: API Gateway → intake service (starter.py equivalent) → Temporal Client starts OrderWorkflow keyed by order_id (Workflow ID); Temporal Server; stateless Worker Pool (worker.py); activities call Inventory, Payments, Fraud, WMS, Carrier.
- **4.1 State Machine**: RECEIVED → VALIDATING → VALIDATED → PROVISIONING → PROVISIONED → DISPATCHING → DISPATCHED → COMPLETED; terminal REJECTED and CANCELLED from any non-terminal.
- **4.2 Activities** (Activity | Purpose | Idempotency strategy | Retry policy): capture_order (3 attempts, 1s→10s backoff); validate_order (3); provision_order (5 attempts, exp backoff, max 1m); compensate_provisioning (5); dispatch_order (5 attempts, exp, max 2m; idempotency key §4.4); compensate_dispatch (5, by tracking ID); complete_order (3, invoice keyed by order_id); reject_order / cancel_order_record (3, idempotent write).
- **4.3 Saga**: pseudo-code try validate/provision/dispatch/complete except ActivityError → if dispatch completed compensate_dispatch; if provision completed compensate_provisioning; reject_order(reason). Implemented with a "completed steps" stack, no saga framework.
- **4.4 Idempotency keys**: `workflow.uuid4()` generated before dispatch_order, passed as activity arg.
- **4.5 Signals & Queries**: Signal `cancel_order(reason: str)` any time before COMPLETED, checked between steps; Query `get_status() -> OrderState` (status enum, per-transition timestamps, latest failure reason).
- **4.6 Timeouts & SLAs** (Stage | Activity StartToCloseTimeout | Business SLA): Validate 30s / 2 min; Provision 60s / 10 min; Dispatch 120s / 4 hours; Complete 30s / 24 hours.
- **4.7 Delivery wait**: await Signal `delivery_confirmed`; `workflow.continue_as_new()` after dispatch carrying minimal state.
- **5. Data Contracts** (src/shared/types.py): OrderRequest, OrderState, ValidationResult/ProvisioningResult/DispatchResult/CompletionResult, OrderStatus.
- **6. Observability**: structured logs with order_id/workflow_id/run_id; Temporal UI/CLI as audit; SLA alerting via separate `SlaMonitorWorkflow` (design placeholder, not shown).
- **7. Testing Strategy**: `temporalio.testing.WorkflowEnvironment` time-skipping, mocked activities.
- **8. Open Items**: partial shipment (BCR-001); multi-warehouse split allocation; formal SlaMonitorWorkflow.

### 2.5 Test Plan — `TP-ORD-001` (v1.0, Approved; Linked TDD-ORD-001 / EPIC-001; Owner QA / Platform Engineering)
Sections: 1 Introduction; 2 Objectives (state machine paths, saga, idempotency, BR-09/10/12, CI regression on src/workflows|activities); 3.1 In Scope / 3.2 Out of Scope (load → EPIC-001-A; chaos → manual TC-15; **partial shipment out of scope "until BCR-001 is implemented; this plan will be extended at that time"**; downstream contract testing); 4 Test Strategy — 4.1 Levels (Unit / Workflow-Integration / Manual-Exploratory table: Level | Purpose | Tooling), 4.2 Test Types (Functional; Compensation/Saga; Reliability/Idempotency; NF/Scalability; NF/Observability; Edge cases), 4.3 Time-Skipping env, 4.4 Test Data (`make_order()` helper; `DECLINE_ME` payment token double); 5 Test Environment (Component | Test Configuration); 6 Entry Criteria (☐ list); 7 Exit Criteria (☐: 100% Automated pass; zero Sev-1/2; TC-15 manual once per RC; TC-16 planned implemented or deferred); 8 Deliverables (xlsx matrix; tests/test_order_workflow.py; CI reports; test summary report per release); 9 Roles & Responsibilities (Role | Responsibility: QA/Test Owner, Platform Engineering, Product Owner, Operations); 10 Risks to the Test Effort (Risk | Mitigation); 11 Approval.

### 2.6 Test-case matrix — `TC-order-workflow.xlsx` (sheet "Test Cases" + sheet "Summary")
Columns: **TC ID | Title | Preconditions | Steps | Expected Result | Type | Automated | Linked Story/Req | Notes**

| TC | Title | Type | Automated | Linked |
|---|---|---|---|---|
| TC-01 | Happy path — full order lifecycle | Functional | Yes | US-001..US-005 |
| TC-02 | Validation fails — insufficient inventory | Functional | Yes | US-002 |
| TC-03 | Validation fails — payment declined | Functional | Yes | US-002 |
| TC-04 | Validation fails — fraud score above threshold | Functional | Yes | US-002 |
| TC-05 | Provisioning fails after validation succeeds | Functional | Yes | US-003 |
| TC-06 | Dispatch fails after provisioning succeeds | Functional / Compensation | Yes | US-004 |
| TC-07 | Transient dispatch failure recovers on retry | Reliability / Idempotency | Yes | US-004 |
| TC-08 | Cancellation before provisioning | Functional / Cancellation | Yes | TDD §4.3 |
| TC-09 | Cancellation after provisioning, before dispatch | Functional / Compensation | Yes | TDD §4.3 |
| TC-10 | Cancellation after dispatch | Functional / Compensation | Yes | TDD §4.3 |
| TC-11 | Cancellation attempted after completion | Edge case | Yes | US-005 |
| TC-12 | Status query at every stage | Functional | Yes | TDD §4.5 |
| TC-13 | Duplicate order capture (same order_id) | Reliability / Idempotency | Yes | US-001 |
| TC-14 | Long backorder wait does not bloat history | Non-functional / Scalability | Yes | US-005 / TDD §4.7 |
| TC-15 | Worker crash mid-activity does not duplicate side effects | Reliability | Manual (chaos test) | TDD §4.2 (Notes: needs infra) |
| TC-16 | SLA breach alerting | Non-functional / Observability | Planned | TDD §6 (Notes: SlaMonitorWorkflow placeholder) |
| TC-17 | Invalid order request payload | Functional / Validation | Yes | US-001 |
Summary sheet: Automated 15 / Manual 1 / Planned 1 / Total 17; Totals by Type (Functional 6, Functional/Compensation 3, Functional/Cancellation 1, Functional/Validation 1, Reliability/Idempotency 2, Reliability 1, NF/Scalability 1, NF/Observability 1, Edge case 1); two Notes rows. Header rows: "Test Case Matrix — Order Lifecycle Workflow", "Linked TDD:", "Linked Epic:", "Automation: tests/test_order_workflow.py".
Reason codes appearing across docs: INVENTORY_UNAVAILABLE, PAYMENT_DECLINED, FRAUD_HOLD, PROVISIONING_FAILED, DISPATCH_FAILED, INVALID_REQUEST (TC-17 only), VALIDATION_FAILED (code fallback only).

### 2.7 Diagrams
- **order-state-machine.mmd** (`stateDiagram-v2`): states RECEIVED, VALIDATING, VALIDATED, PROVISIONING, PROVISIONED, DISPATCHING, DISPATCHED, COMPLETED, REJECTED, CANCELLED plus intermediate **COMPENSATING_PROVISION** (DISPATCHING→ on dispatch failed → REJECTED), **CANCELLING_COMPENSATE** (from PROVISIONING/PROVISIONED on cancel → CANCELLED), **CANCELLING_RECALL** (from DISPATCHING/DISPATCHED on cancel → CANCELLED). RECEIVED/VALIDATING/VALIDATED → CANCELLED directly. Transition labels e.g. "capture_order", "begin validation", "inventory OK, payment authorized, fraud clear", "cancel_order signal".
- **order-sequence.mmd** (`sequenceDiagram`, autonumber): participants Client (Order Intake API), TC (Temporal Client), WF (OrderWorkflow), INV, PAY, FRD, WMS, CAR, FIN. Calls: StartWorkflow(order_id, OrderRequest); capture_order()→RECEIVED; check_availability(sku,qty); authorize(payment_token,amount); score(order); VALIDATED; reserve_inventory(order_id,sku,qty)→reservation_id; PROVISIONED; create_shipment(order_id, idempotency_key, address)→tracking_number,label_url; DISPATCHED; continue_as_new; Note "awaits delivery_confirmed signal (hours/days)"; signal delivery_confirmed(order_id) from CAR; generate_invoice(order_id)→invoice_id; COMPLETED; query get_status → OrderState{status=COMPLETED}.
- **system-architecture.mmd** (`flowchart LR`): subgraphs Channels (WEB, MOB, PART, CC), Intake (GW API Gateway, INTAKE Order Intake Service), Orchestration "Temporal Orchestration Layer" (TS Temporal Server/Cloud, WRK1 Worker Pool - Order Namespace, WF OrderWorkflow), Downstream (INV, PAY, FRD, WMS, CAR, FIN), Consumers "Internal Consumers" (SUP Customer Support, OPS Operations Dashboard/Alerting, AUD Audit/Compliance Export). Edges labelled validate / authorize / score / reserve/release / create shipment/recall / generate invoice; SUP "query get_status", OPS "SLA monitor query", AUD "export event history".
- **system-flow-diagram.md**: H1 "System & Process Flow Diagrams — Order Lifecycle Workflow"; sections "## 1. Order State Machine" (see TDD §4.1), "## 2. End-to-End Sequence (Happy Path)" (TDD §4.7), "## 3. System Architecture" (TDD §3), each with the mmd content inline.

---

## 3. Existing codebase (Python, Temporal SDK; imports as `src.*`)

### shared/types.py
- `class OrderStatus(str, Enum)`: RECEIVED, VALIDATING, VALIDATED, PROVISIONING, PROVISIONED, DISPATCHING, DISPATCHED, COMPLETED, REJECTED, CANCELLED (10 — no COMPENSATING_*/CANCELLING_* intermediates from the diagram).
- Dataclasses: `LineItem(sku, quantity:int, unit_price:float)`; `ShippingAddress(line1, city, state, postal_code, country)`; `OrderRequest(order_id, customer_id, line_items:list[LineItem], shipping_address, payment_token)`; `ValidationResult(passed:bool, reason_code:Optional[str])`; `ProvisioningResult(reservation_id, warehouse_id)`; `DispatchResult(tracking_number, carrier, label_url, idempotency_key)`; `CompletionResult(invoice_id, delivered_at:datetime)`; `OrderState(order_id, status, failure_reason, received_at, validated_at, provisioned_at, dispatched_at, completed_at, tracking_number, invoice_id, history:list[str])`.

### activities/order_activities.py (all `@activity.defn`, async, mock bodies with `_call_*`-style helpers)
- `capture_order(order) -> str` — raises `ApplicationError(..., non_retryable=True)` if no line_items (TC-17).
- `validate_order(order) -> ValidationResult` — `_check_inventory` (all qty>0), `_authorize_payment` (token != "DECLINE_ME"), `_fraud_check` (customer_id != "FRAUD_FLAGGED"); reason codes INVENTORY_UNAVAILABLE / PAYMENT_DECLINED / FRAUD_HOLD.
- `provision_order(order) -> ProvisioningResult` — `RSV-{order_id}`, warehouse `WH-EAST-01`.
- `compensate_provisioning(reservation_id) -> None`.
- `dispatch_order(order, idempotency_key) -> DispatchResult` — `TRK-{key[:8].upper()}`, carrier `GLOBAL-EXPRESS`, label URL.
- `compensate_dispatch(tracking_number) -> None`.
- `complete_order(order_id) -> CompletionResult` — `INV-{order_id}`, delivered_at now(utc).
- `record_terminal_state(order_id, status, reason) -> None` (the TDD's "reject_order / cancel_order_record").

### workflows/order_workflow.py — `@workflow.defn class OrderWorkflow`
- Constants: VALIDATE_TIMEOUT 30s, PROVISION_TIMEOUT 60s, DISPATCH_TIMEOUT 120s, COMPLETE_TIMEOUT 30s; single `DEFAULT_RETRY = RetryPolicy(initial 1s, backoff 2.0, max interval 1m, maximum_attempts=5)` used for every activity (TDD's per-activity 3/5-attempt policies are NOT differentiated).
- State: `_state: OrderState`, `_cancel_requested`, `_cancel_reason`, `_delivery_confirmed`, `_provisioning_result`, `_dispatch_result`.
- Signals: `cancel_order(reason: str)` (ignored + history-logged if terminal); `delivery_confirmed()` (no args — sequence diagram shows `delivery_confirmed(order_id)`).
- Query: `get_status() -> OrderState`.
- `@workflow.run async run(order: OrderRequest) -> OrderState`: capture_order (uses VALIDATE_TIMEOUT) → VALIDATING → cancel check → validate_order (fail → `_finish_rejected(reason_code or "VALIDATION_FAILED")`) → VALIDATED → cancel check → PROVISIONING → provision_order (ActivityError → REJECTED PROVISIONING_FAILED) → PROVISIONED → cancel check (compensate_provisioning) → DISPATCHING, `idempotency_key = str(workflow.uuid4())` → dispatch_order (ActivityError → compensate_provisioning + REJECTED DISPATCH_FAILED) → DISPATCHED (tracking_number set) → cancel check (compensate_dispatch, compensate_provisioning) → **continue_as_new is only a comment block, not executed** → `wait_condition(delivery_confirmed or cancel_requested)` → cancel → both compensations + CANCELLED; else complete_order → invoice_id → COMPLETED.
- Helpers: `_transition(status)` appends `"{iso now} -> {STATUS}"` to history; `_maybe_cancel()`; `_compensate_provisioning()` / `_compensate_dispatch()` (guarded by result-not-None, append "Compensated provisioning (inventory released)" / "Compensated dispatch (shipment recalled)"); `_finish_rejected(reason)` / `_finish_cancelled()` set failure_reason, transition, call `record_terminal_state`.
- Docstring points to `docs/technical-design/TDD-order-workflow-temporal.md` (the file is .docx).

### worker.py / starter.py
- `TASK_QUEUE = "order-workflow-task-queue"`; `Client.connect("localhost:7233", namespace="default")`; Worker registers `OrderWorkflow` + all 8 activities; run `python -m src.worker`.
- starter: argparse `--customer-id` (req), `--sku` (req), `--qty` (1), `--payment-token` (tok_test_ok), `--order-id` (default `ORD-{uuid hex[:10] upper}`); builds one LineItem @19.99, fixed Dallas TX address; `client.start_workflow(OrderWorkflow.run, order, id=order_id, task_queue=TASK_QUEUE)`; prints workflow_id/run_id.

### tests/test_order_workflow.py (pytest-asyncio; `WorkflowEnvironment.start_time_skipping()`; TASK_QUEUE "test-order-workflow-task-queue"; `make_order()` helper; fake activities registered by name)
- `test_happy_path_reaches_dispatched` — TC-01 (partial): signals delivery_confirmed, asserts COMPLETED, tracking_number, `INV-{id}`.
- `test_validation_failure_rejects_without_provisioning` — TC-02: REJECTED / INVENTORY_UNAVAILABLE.
- `test_cancel_after_provisioning_compensates_reservation` — TC-09 (racy: signals immediately after start; assertion is `any("Compensated"...) or status == CANCELLED`, i.e. tautological).
- `test_status_query_reflects_current_state` — TC-12: query after completion only.
- So only 4 of the 15 "Automated=Yes" TCs have tests (TC-01, 02, 09, 12); TC-03..08, 10, 11, 13, 14, 17 are not implemented despite the xlsx marking them Yes.

### requirements.txt: `temporalio>=1.7.0`, `pytest>=8.0.0`, `pytest-asyncio>=0.23.0` (no upper pins, no pytest.ini/asyncio_mode config).

---

## 4. BCR-001 — "Partial Shipment Support for Multi-Line Orders" (FULL)
Header block: **Business Change Request (BCR)** / subtitle "Partial Shipment Support for Multi-Line Orders" / Document ID: BCR-001 / Status: **Proposed — Pending Impact Assessment** / Requested By: VP, Supply Chain Operations / Date Raised: 2026-08-10 / Target Workflow: OrderWorkflow (EPIC-001 / TDD-ORD-001).

**1. Change Summary** (verbatim): "Currently, OrderWorkflow provisions and dispatches an order as a single unit — if any line item is backordered, the entire order waits until all items are available (see current TDD §4.1/§4.6). The business now wants to support partial (split) shipments: line items that are in stock should ship immediately, while backordered items ship separately once replenished, without blocking or delaying the in-stock items."

**2. Business Justification**: customer complaints where one backordered item (of 5+) delays everything; competitor benchmarking shows partial shipment is standard; expected 30–40% reduction in average delivery time for the non-backordered portion of multi-line orders.

**3. Requested Change — Functional Requirements** (table Req ID | Requirement), verbatim:
- **BCR-01-01** — The system shall split an order into one or more "shipment groups" based on line-item availability at provisioning time.
- **BCR-01-02** — Each shipment group shall be independently provisioned, dispatched, and tracked (its own tracking number), while remaining associated with the parent order.
- **BCR-01-03** — The parent order shall remain in a PARTIALLY_DISPATCHED status until all shipment groups reach DISPATCHED.
- **BCR-01-04** — The parent order shall reach COMPLETED only once all shipment groups report delivery confirmation and a single consolidated invoice (or itemized multi-shipment invoice, pending Finance input) has been generated.
- **BCR-01-05** — Cancellation must support cancelling the entire order (all shipment groups, including unshipped backordered items) or an individual shipment group (e.g., customer no longer wants the backordered item but still wants the rest).
- **BCR-01-06** — Status query (get_status) shall return per-shipment-group status in addition to overall order status.
(No separate non-functional requirements section; NFR-ish content lives in §7 Risks.)

**4. Impact on Existing Design (Preliminary — TDD update required)** — "This is a structural change to the workflow, not an incremental one:"
- State machine: new states **PARTIALLY_PROVISIONED, PARTIALLY_DISPATCHED** and a shipment-group sub-state-machine nested under the order; current `docs/diagrams/mermaid/order-state-machine.mmd` "will need a companion **order-state-machine-partial-shipment.mmd**".
- Data contracts (`src/shared/types.py`): ProvisioningResult and DispatchResult assume one reservation/one shipment per order → "need to become list[ProvisioningResult] / list[DispatchResult] keyed by shipment group."
- Workflow (`src/workflows/order_workflow.py`): provisioning/dispatch currently await a single activity each → "need to fan out (e.g., asyncio.gather over per-group activities) and track completion of each group independently, including independent compensation per group."
- Saga/compensation (TDD §4.3): re-scope from order-level to shipment-group-level compensation, while still supporting order-level (all groups) compensation for BCR-01-05.
- Continue-as-new (TDD §4.7): each group may have its own delivery-wait duration — design work needed so one slow group doesn't block history-size management for the others.
- Invoicing (`complete_order` activity): needs Finance decision on consolidated vs itemized (BCR-01-04) before implementation.

**5. Out of Scope for This Change**: multi-warehouse optimization/routing of which warehouse fulfils which group (v1 reuses single-warehouse allocation per group); customer-facing UI for multiple tracking numbers.

**6. Dependencies / Follow-up Actions** (☐ checklist — these are the named expected deliverables):
- ☐ Engineering: "produce an updated TDD section (or new **TDD-ORD-002**) covering the shipment-group design before implementation begins."
- ☐ Finance: decide consolidated vs. itemized invoicing (blocks BCR-01-04).
- ☐ QA: "extend **docs/test-cases/TC-order-workflow.md** with partial-shipment scenarios (split provisioning, independent dispatch failure/compensation per group, mixed cancel scenarios)." (note: says `.md`, the actual matrix is `.xlsx`)
- ☐ "Update EPIC-001 story map or raise a new **EPIC-002** if this is sized as its own epic (recommended, given the structural impact in §4)."

**7. Risks** (table Risk | Notes): Backward compatibility — in-flight single-shipment orders must complete under old logic; new logic for new workflows only or versioning via `workflow.patched()`; Increased workflow complexity — fan-out/fan-in compensation, recommend design review; Invoicing correctness — must not double- or under-invoice across groups.

Not present in BCR: explicit acceptance criteria per requirement, explicit list of impacted stories/test IDs, effort/sizing, target release. Cross-references to BCR-001 elsewhere: BRD §3.2 & §7, EPIC DoD, TDD §8, TP §3.2.

---

## 5. Document conventions / templates (for generating new docs in the same style)

Common docx styling (all docs): first paragraph = document type in Normal style, bold, 22pt (sz 44); second = subtitle 14pt (sz 28) not bold; then a metadata block of `Label: value` lines (label bold); Word built-in Heading 1 / Heading 2 styles; bullet lists = "List Paragraph" style; tables have no named table style, header row shaded `2F5496` (dark blue, white text); checklists are plain paragraphs starting with `☑  ` / `☐  ` (two spaces); inline code/paths (e.g. `get_status()`, `docs/...`) rendered in Consolas runs; en/em dashes and → arrows used freely; docProps creator "Un-named". Section headings numbered "N. Title" / "N.M Title" for BRD, TDD, TP, BCR; unnumbered for EPIC; US docs use Heading 2 only.

**BRD** — Title "Business Requirements Document (BRD)"; subtitle "<Name> — <Range>"; meta: Document ID (BRD-ORD-001), Version, Status, Owner, Last Updated. H1s: 1. Business Context (prose + bullets + bold need statement); 2. Business Objectives [ID | Objective | Success Metric; IDs BO-n]; 3. Scope → H2 3.1 In Scope, 3.2 Out of Scope (for this phase) (bullets); 4. Stakeholders [Role | Stakeholder | Interest]; 5. High-Level Business Requirements [Req ID | Requirement | Priority; IDs BR-NN; "The system shall …"; Must/Should]; 6. Assumptions & Constraints (bullets); 7. Related Documents (bullets "ID: title (path)").

**EPIC** — Title "EPIC-001"; subtitle "<Name> (Capture → Completion)"; meta: Epic Owner, Linked BRD, Status, Target Release. H1s: Epic Statement; Business Value (bullets); In-Scope Capabilities (bullets); Definition of Done (☑/☐ lines); Story Map [Story ID | Title | Status | Doc]; Non-Functional Requirements [NFR | Target]; Dependencies (bullets); Risks [Risk | Mitigation].

**User Story** — Title "US-00N: <Title>"; meta: Epic ("EPIC-001 — Order Lifecycle Management"), Status, Story Points. H2s: Story (3 lines: "As …," / "I want …," / "so that ….") ; Acceptance Criteria (☐ lines, Given/When style, "Given …, the order transitions to …"); Notes ("Implements BR-xx. See TDD §x.y and TC-xx/TC-yy for test coverage." + design remark). Filename `US-00N-<kebab-title>.docx`.

**TDD** — Title "Technical Design Document (TDD)"; subtitle "<Workflow> — Temporal Implementation"; meta: Document ID (TDD-ORD-001), Linked EPIC, Version, Status, Author. H1s: 1. Overview; 2. Why Temporal [Requirement (from BRD) | How Temporal satisfies it]; 3. High-Level Architecture (bullets, refs mmd); 4. Workflow Design → H2 4.1 State Machine, 4.2 Activities [Activity | Purpose | Idempotency strategy | Retry policy], 4.3 Saga / Compensation Logic (pseudo-code), 4.4 Idempotency Keys…, 4.5 Signals & Queries (bullets), 4.6 Timeouts & SLAs [Stage | Activity StartToCloseTimeout | Business SLA (alerting)], 4.7 Handling Delivery Wait Time; 5. Data Contracts (bullets naming types); 6. Observability; 7. Testing Strategy; 8. Open Items / Future Work.

**Test Plan** — Title "Test Plan"; subtitle "<Workflow> — Capture to Completion"; meta: Document ID (TP-ORD-001), Linked TDD, Linked Epic, Version, Status, Owner. H1s: 1. Introduction; 2. Objectives (bullets); 3. Scope → 3.1 In Scope / 3.2 Out of Scope; 4. Test Strategy → 4.1 Levels of Testing [Level | Purpose | Tooling], 4.2 Test Types Covered (bullets "Type — description"), 4.3 Time-Skipping Test Environment, 4.4 Test Data; 5. Test Environment [Component | Test Configuration]; 6. Entry Criteria (☐); 7. Exit Criteria (☐); 8. Deliverables (bullets); 9. Roles & Responsibilities [Role | Responsibility]; 10. Risks to the Test Effort [Risk | Mitigation]; 11. Approval.

**Test-case xlsx** — Sheet "Test Cases": columns A–I `TC ID | Title | Preconditions | Steps | Expected Result | Type | Automated | Linked Story/Req | Notes`; IDs `TC-NN` (2-digit); Title style "<Scenario> — <detail>"; Type vocabulary: Functional; Functional / Compensation; Functional / Cancellation; Functional / Validation; Reliability / Idempotency; Reliability; Non-functional / Scalability; Non-functional / Observability; Edge case; Automated values: Yes / Manual (chaos test) / Planned; Linked values: US-00N, "US-001..US-005", "TDD §4.3". Sheet "Summary": title row, "Linked TDD:", "Linked Epic:", "Automation:", blank, "Totals by Automation Status" (Automated (Yes)/Manual/Planned/Total Test Cases), "Totals by Type" (one row per Type), "Notes" (free text rows).

**BCR** — Title "Business Change Request (BCR)"; subtitle; meta: Document ID (BCR-001), Status, Requested By, Date Raised, Target Workflow. H1s: 1. Change Summary; 2. Business Justification (bullets); 3. Requested Change — Functional Requirements [Req ID | Requirement; IDs BCR-01-0N]; 4. Impact on Existing Design (Preliminary — TDD update required) (bullets "Component: impact"); 5. Out of Scope for This Change; 6. Dependencies / Follow-up Actions (☐ "Owner: action"); 7. Risks [Risk | Notes].

**Diagrams** — `.mmd` raw sources + one `system-flow-diagram.md` embedding them under numbered H2s with a "See TDD §x" line. State names UPPER_SNAKE; transition labels lowercase phrases; sequence participants aliased 2–6 letter caps.

ID formats: BRD-ORD-001 / TDD-ORD-001 / TP-ORD-001 / EPIC-001 / EPIC-001-A / US-00N / TC-NN / BO-n / BR-NN / BCR-001 / BCR-01-0N. Version strings "1.0/1.1/1.2"; Status vocabulary: Approved, In Progress (Phase 1 Delivered), Done, Proposed — Pending Impact Assessment; Target Release "R2026.3".

---

## 6. Gaps / oddities
1. **Layout mismatch**: README/docs reference `docs/`, `src/`, `tests/`, `business-change/`; on disk it's `Existing_KG/Business_Docs`, `Existing_KG/existing_Codebase`, `Existing_KG/tests`, `New_business-change`. Code imports `src.…` and workflow docstring points to a `.md` TDD — the code will not import as checked out without a `src` package alias.
2. **continue_as_new not implemented**: TDD §4.7, US-005 AC, TC-14, sequence diagram all say continue-as-new after dispatch; workflow has only a commented placeholder.
3. **Retry policies**: TDD §4.2 specifies per-activity policies (3 vs 5 attempts, max 1m vs 2m); code uses one DEFAULT_RETRY (5 attempts, max 1m) everywhere; capture_order and record_terminal_state use VALIDATE_TIMEOUT.
4. **State enum vs diagram**: diagram has COMPENSATING_PROVISION, CANCELLING_COMPENSATE, CANCELLING_RECALL; `OrderStatus` has none of them (compensation is only history text).
5. **Activity naming**: TDD names `reject_order / cancel_order_record`; code has one `record_terminal_state`.
6. **Test coverage**: only 4 tests for 15 "Automated=Yes" TCs; TC-03/04/05/06/07/08/10/11/13/14/17 not implemented. TC-09 test is racy and its assertion is tautological. TC-17 expects reason INVALID_REQUEST but a non-retryable ApplicationError from capture_order is not caught in `run()` (workflow would fail rather than end REJECTED).
7. **Signal signature**: sequence diagram `delivery_confirmed(order_id)` vs code `delivery_confirmed()` no args; diagram shows carrier sending it.
8. **US-006 / US-007** listed Done in the EPIC story map but have no documents; EPIC references "TDD §5.3" which doesn't exist (queries are §4.5).
9. **BCR-001 §6** references `docs/test-cases/TC-order-workflow.md` (actual is `.xlsx`); BCR has no acceptance criteria, no explicit list of impacted stories/TCs; Finance decision (BCR-01-04) is an unresolved blocker; BCR-01-01 splits at *provisioning* time but validation (`_check_inventory`) currently fails the whole order if any item is unavailable — BCR does not say how validation changes.
10. TDD §4.6 SLA table and SlaMonitorWorkflow (TC-16) are placeholders; no code. TP §4.4 mentions `DECLINE_ME` double which exists only in the real activity, not in the test doubles.
11. Docs are dated 2026-08-01 (BRD) / 2026-08-10 (BCR); repo has a single commit "Updated"; docx creator "Un-named" (generated).
12. `pytest-asyncio` used with `@pytest.mark.asyncio` but no `asyncio_mode` config; `python -m src.starter` imports `TASK_QUEUE` from `src.worker`, so starting an order imports the worker module.

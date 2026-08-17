# Enterprise Order Workflow — Reference Repository

This is a **sample / reference repository** for an enterprise-wide **Order Capture → Validation → Provisioning → Dispatching → Completion** process, implemented as a durable workflow using **Temporal**.

It's structured the way a real engineering team would organize requirements, design, tests, diagrams, and code for a long-running business workflow — so it can double as a template for onboarding, context for AI coding agents, or a starting point for your own order-management build.

## Repository Structure

```
order-workflow-repo/
├── docs/
│   ├── business-requirements/     # BRD — what the business needs and why
│   │   └── BRD-order-lifecycle-management.docx
│   ├── epics/                     # EPIC — the large body of work, broken into stories
│   │   └── EPIC-001-order-lifecycle-management.docx
│   ├── technical-design/          # TDD — how the workflow is engineered on Temporal
│   │   └── TDD-order-workflow-temporal.docx
│   ├── test-cases/                # Test case matrix + test plan for the workflow
│   │   ├── TC-order-workflow.xlsx
│   │   └── TP-order-workflow-test-plan.docx
│   ├── user-stories/              # Prior/backlog user stories delivered under the EPIC
│   │   ├── US-001-capture-order.docx
│   │   ├── US-002-validate-order.docx
│   │   ├── US-003-provision-order.docx
│   │   ├── US-004-dispatch-order.docx
│   │   └── US-005-complete-order.docx
│   └── diagrams/
│       ├── system-flow-diagram.md     # System / integration flow (rendered Mermaid)
│       └── mermaid/                   # Raw .mmd sources
│           ├── order-state-machine.mmd
│           ├── order-sequence.mmd
│           └── system-architecture.mmd
│
├── src/                            # Temporal codebase (Python SDK)
│   ├── shared/
│   │   └── types.py                # Order data contracts (dataclasses, enums)
│   ├── activities/
│   │   └── order_activities.py     # Capture / Validate / Provision / Dispatch / Complete activities
│   ├── workflows/
│   │   └── order_workflow.py       # OrderWorkflow — the durable orchestration (saga)
│   ├── worker.py                   # Temporal worker process
│   └── starter.py                  # CLI to start a new order workflow execution
│
├── tests/
│   └── test_order_workflow.py      # Workflow unit tests (Temporal time-skipping test env)
│
├── business-change/                # NEW/CHANGED requirements against the current workflow
│   └── BCR-001-partial-shipment-support.docx
│
└── requirements.txt
```

## How the pieces connect

1. **BRD** → captures the enterprise-wide business need (`docs/business-requirements`).
2. **EPIC** → decomposes the BRD into a delivery-sized body of work (`docs/epics`), which is broken into the **user stories** (`docs/user-stories`).
3. **TDD** → describes how the EPIC is implemented as a Temporal workflow, including the state machine and saga/compensation design (`docs/technical-design`).
4. **Diagrams** → Mermaid source + rendered system flow diagrams that visualize the state machine, sequence of calls, and system architecture (`docs/diagrams`).
5. **Code** (`src/`) → the actual Temporal workflow + activities implementing the design.
6. **Test cases** (`docs/test-cases/TC-order-workflow.xlsx`) map to automated tests in `tests/`, and are governed by the **Test Plan** (`docs/test-cases/TP-order-workflow-test-plan.docx`), which defines test strategy, environment, entry/exit criteria, and sign-off.
7. **business-change/** → any *new* requirement raised against the *existing, live* workflow (e.g., a Business Change Request / BCR) is tracked separately from the original BRD/EPIC, so you can see what changed, why, and what it touches — without rewriting the original requirement history.

## Running the workflow locally

```bash
pip install -r requirements.txt

# 1. Start a local Temporal dev server (requires the `temporal` CLI)
temporal server start-dev

# 2. In a separate terminal, start the worker
python -m src.worker

# 3. In a separate terminal, kick off an order
python -m src.starter --customer-id CUST-1001 --sku SKU-4471 --qty 2
```

## Running tests

```bash
pytest tests/ -v
```

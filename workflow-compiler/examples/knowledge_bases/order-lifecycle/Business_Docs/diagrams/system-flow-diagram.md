# System & Process Flow Diagrams — Order Lifecycle Workflow

Source `.mmd` files live in `docs/diagrams/mermaid/`. Rendered here for convenience (any Mermaid-aware viewer — GitHub, GitLab, most IDEs, or the Mermaid Live Editor — will render these directly).

## 1. Order State Machine

Governs every valid transition the `OrderWorkflow` can make. See TDD §4.1.

```mermaid
stateDiagram-v2
    [*] --> RECEIVED: capture_order

    RECEIVED --> VALIDATING: begin validation
    VALIDATING --> VALIDATED: inventory OK, payment authorized, fraud clear
    VALIDATING --> REJECTED: validation failed

    VALIDATED --> PROVISIONING: begin provisioning
    PROVISIONING --> PROVISIONED: inventory reserved, warehouse allocated
    PROVISIONING --> REJECTED: provisioning failed (nothing to compensate)

    PROVISIONED --> DISPATCHING: begin dispatch
    DISPATCHING --> DISPATCHED: carrier label generated, package handed off
    DISPATCHING --> COMPENSATING_PROVISION: dispatch failed
    COMPENSATING_PROVISION --> REJECTED: inventory released

    DISPATCHED --> COMPLETED: delivery confirmed, invoice generated

    RECEIVED --> CANCELLED: cancel_order signal
    VALIDATING --> CANCELLED: cancel_order signal
    VALIDATED --> CANCELLED: cancel_order signal
    PROVISIONING --> CANCELLING_COMPENSATE: cancel_order signal
    PROVISIONED --> CANCELLING_COMPENSATE: cancel_order signal
    CANCELLING_COMPENSATE --> CANCELLED: inventory released

    DISPATCHING --> CANCELLING_RECALL: cancel_order signal
    DISPATCHED --> CANCELLING_RECALL: cancel_order signal
    CANCELLING_RECALL --> CANCELLED: shipment recalled, inventory released

    REJECTED --> [*]
    CANCELLED --> [*]
    COMPLETED --> [*]
```

## 2. End-to-End Sequence (Happy Path)

Shows the calls the workflow makes to downstream systems and the delivery-confirmation signal wait. See TDD §4.7.

```mermaid
sequenceDiagram
    autonumber
    participant Client as Order Intake API
    participant TC as Temporal Client
    participant WF as OrderWorkflow (Temporal)
    participant INV as Inventory Service
    participant PAY as Payment Gateway
    participant FRD as Fraud Service
    participant WMS as Warehouse Mgmt System
    participant CAR as Carrier API
    participant FIN as Invoicing/Finance

    Client->>TC: StartWorkflow(order_id, OrderRequest)
    TC->>WF: new OrderWorkflow execution
    WF->>WF: capture_order() -> RECEIVED

    WF->>INV: check_availability(sku, qty)
    INV-->>WF: available
    WF->>PAY: authorize(payment_token, amount)
    PAY-->>WF: authorized
    WF->>FRD: score(order)
    FRD-->>WF: pass
    WF->>WF: VALIDATED

    WF->>WMS: reserve_inventory(order_id, sku, qty)
    WMS-->>WF: reservation_id
    WF->>WF: PROVISIONED

    WF->>CAR: create_shipment(order_id, idempotency_key, address)
    CAR-->>WF: tracking_number, label_url
    WF->>WF: DISPATCHED
    WF->>WF: continue_as_new (carry forward minimal state)

    Note over WF: Workflow awaits delivery_confirmed signal (hours/days)

    CAR-->>WF: signal: delivery_confirmed(order_id)
    WF->>FIN: generate_invoice(order_id)
    FIN-->>WF: invoice_id
    WF->>WF: COMPLETED

    Client->>WF: query get_status(order_id)
    WF-->>Client: OrderState{status=COMPLETED, ...}
```

## 3. System Architecture

How the workflow orchestration layer sits between customer-facing channels and downstream enterprise systems. See TDD §3.

```mermaid
flowchart LR
    subgraph Channels
        WEB[Web Storefront]
        MOB[Mobile App]
        PART[Partner API]
        CC[Call Center]
    end

    subgraph Intake
        GW[API Gateway]
        INTAKE[Order Intake Service]
    end

    subgraph Orchestration["Temporal Orchestration Layer"]
        TS[(Temporal Server / Cloud)]
        WRK1[Worker Pool - Order Namespace]
        WF[[OrderWorkflow]]
    end

    subgraph Downstream["Downstream Systems"]
        INV[(Inventory Service)]
        PAY[(Payment Gateway)]
        FRD[(Fraud/Risk Service)]
        WMS[(Warehouse Mgmt System)]
        CAR[(Carrier Aggregator API)]
        FIN[(Invoicing / Finance)]
    end

    subgraph Consumers["Internal Consumers"]
        SUP[Customer Support]
        OPS[Operations Dashboard/Alerting]
        AUD[Audit / Compliance Export]
    end

    WEB --> GW
    MOB --> GW
    PART --> GW
    CC --> GW
    GW --> INTAKE
    INTAKE -- StartWorkflow(order_id) --> TS
    TS <--> WRK1
    WRK1 --> WF

    WF -- validate --> INV
    WF -- authorize --> PAY
    WF -- score --> FRD
    WF -- reserve/release --> WMS
    WF -- create shipment/recall --> CAR
    WF -- generate invoice --> FIN

    SUP -- query get_status --> TS
    OPS -- SLA monitor query --> TS
    AUD -- export event history --> TS
```

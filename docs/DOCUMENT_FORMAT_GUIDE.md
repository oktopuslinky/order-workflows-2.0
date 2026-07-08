# Workflow Document Format Guide

This guide defines the recommended structure and writing style for business workflow documents
processed by `workflow-compiler`. Following it maximises the accuracy of every pipeline stage:
metadata extraction, fact extraction, graph building, CVPA classification, and Temporal design.

Each section below maps directly to what one or more of the LLM prompt templates needs to extract.
Omitting a section doesn't break the pipeline, but the corresponding artifact field will be empty
or inferred with lower confidence.

---

## Quick reference: section → pipeline stage

| Document section | Feeds |
|---|---|
| Header block (name, domain, owner, tags) | `discover_workflow` → metadata |
| Purpose | `discover_workflow` → `purpose` |
| Trigger | `discover_workflow` → `trigger_events` |
| Actors | `discover_workflow` → `actors` |
| Systems | `discover_workflow` → `systems`, `extract_facts` → `systems` |
| States | `discover_workflow` → `start_states`, `end_states` |
| Inputs / Outputs | `extract_facts` → `inputs`, `outputs` |
| Process Steps | `extract_facts` → `activities`, `decisions`, `events`, `state_transitions` |
| Business Rules | `extract_facts` → `rules` |
| Timers & SLAs | `extract_facts` → `timers` |
| API Interfaces | `extract_facts` → `apis` |
| Exceptions & Error Handling | `extract_facts` → `exceptions` |
| Retries | `extract_facts` → `retries` |
| Compensation / Rollback | `extract_facts` → `compensation_candidates`, `design_temporal` → `compensation_activities` |

---

## Document template

Copy this skeleton and fill it in. Required sections are marked **[required]**.
Optional sections improve output quality when the information is known.

```
# <Workflow Name>

## Metadata                              [required]
## Purpose                               [required]
## Trigger                               [required]
## Actors                                [required]
## Systems                               [required]
## States                                [required]
## Inputs and Outputs
## Process
## Business Rules
## Timers and SLAs
## API Interfaces
## Exceptions and Error Handling
## Retries
## Compensation and Rollback
```

---

## Section-by-section guidance

### `# <Workflow Name>` — H1 title [required]

The document title is the workflow name. Make it concise and action-oriented.

```markdown
# Cancel Order Workflow
# Employee Onboarding Workflow
# Order Fulfillment Workflow
```

---

### `## Metadata` [required]

A small table of administrative facts. The `discover_workflow` agent reads these into the
workflow metadata.
Always include **Domain** and **Owner**; add **Version** and **Tags** when relevant.

```markdown
## Metadata

| Field   | Value                            |
|---------|----------------------------------|
| Domain  | Telecom OMS                      |
| Owner   | Order Management Team            |
| Version | 3.0                              |
| Tags    | cancellation, saga, compensation |
```

---

### `## Purpose` [required]

One to three sentences that describe the business intent. Answer: *why does this workflow exist
and what business outcome does it produce?*

Write in plain present-tense prose. Do not list steps here.

```markdown
## Purpose

This workflow manages the end-to-end cancellation of a customer order, including
eligibility checking, in-flight task termination, service deprovisioning, inventory
release, and billing reversal where applicable.
```

---

### `## Trigger` [required]

State the single event (or small set of events) that starts the workflow.
Use the word **"when"** or **"starts when"** — this is the exact phrasing the
`discover_workflow` agent looks for to identify `trigger_events`.

```markdown
## Trigger

The workflow starts when a **customer submits a cancellation request** through the
CRM, self-service portal, or internal care console.
```

---

### `## Actors` [required]

List the human roles and external parties that participate. Do not list systems here
(systems have their own section). Use a bulleted list.

```markdown
## Actors

- Customer
- Care Agent (CRM operator)
- Compliance Officer (for legal holds)
- Billing Team (for disputed reversals)
```

---

### `## Systems` [required]

List every external system, service, or application the workflow interacts with.
Use the exact name you will also use in the Process and API sections — consistency
lets the fact extractor deduplicate correctly.

```markdown
## Systems

- OMS Temporal Workflow (orchestration)
- CRM / Care Console
- Provisioning Platform
- Service Inventory (TMF638)
- Billing / Mediation System
- Kafka Event Bus
- Notification Service
- Audit / Compliance Archive
```

---

### `## States` [required]

Explicitly declare start and end states. Label them clearly. The `discover_workflow`
agent extracts `start_states` and `end_states` from this section.

```markdown
## States

- **Start states:** `Order received`, `Cancellation requested`
- **End states:** `Order cancelled`, `Order failed`, `Cancel window expired`
```

---

### `## Inputs and Outputs`

List the data and artifacts the workflow consumes and produces. This feeds
`extract_facts` → `inputs` and `outputs`.

Use a two-column list or simple bullets. Be specific about field names for technical
workflows — this is what populates activity input/output specs in the Temporal design.

```markdown
## Inputs and Outputs

**Inputs**
- `orderId` — identifier of the order to cancel
- `cancelScope` — `full` or `partial`
- `cancelReason` — reason code (e.g. `customer_requested`)
- `targetItemIds` — item list for partial cancellations (optional)

**Outputs**
- `cancelId` — identifier of the completed cancellation
- `serviceStatus` — `deprovisioned` or `unchanged`
- `inventoryStatus` — `released` or `unchanged`
```

---

### `## Process` [required]

The numbered sequence of steps. This is the single most important section — the
graph builder derives all nodes and edges from facts extracted here.

**Writing rules that maximize extraction accuracy:**

1. **One activity per numbered item.** Don't bundle two actions in one sentence.
2. **Use imperative verbs in active voice.** "The system validates the order" not
   "order validation occurs."
3. **Make every decision explicit.** State both branches using "if … then … otherwise …"
   or "if … the workflow proceeds to X; if not, the workflow proceeds to Y."
4. **Name parallel branches explicitly.** Use "in parallel" or "concurrently" at the
   start of the sentence.
5. **Name state transitions explicitly.** "The order transitions from `received` to
   `in_progress`."
6. **Emit events explicitly.** "The system publishes an `order.cancelled` event to Kafka."

```markdown
## Process

1. The workflow receives a cancellation request and **validates the request payload**
   (orderId, cancelScope, cancelReason are all present).
2. The system **checks order eligibility** for cancellation: verifies the order state
   allows cancellation, checks for legal holds, and validates contract rules.
3. If the order is **ineligible**, the workflow **rejects the request** and publishes
   an `oms.order.cancel.ineligible` event. The order transitions to `cancel_rejected`.
4. If the order is **eligible**, in parallel the system:
   - **stops any in-flight provisioning tasks** via the Provisioning Platform, and
   - **publishes an `oms.order.cancel.requested` event** to the Kafka Event Bus.
5. The system **deprovisions the service** via the Provisioning Platform (TMF640),
   removing configuration and deactivating the service.
6. The system **releases reserved inventory** via the Service Inventory system (TMF638).
7. The Billing / Mediation System **stops or reverses applicable charges**.
8. The system **publishes an `oms.order.cancel.completed` event** to Kafka and
   **sends a cancellation confirmation** to the customer via the Notification Service.
9. The order transitions to `cancelled`.
```

---

### `## Business Rules`

State constraints and policies as individual bullet points, each self-contained.
These feed `extract_facts` → `rules`.

Assign a rule ID when the document is technical or will be referenced elsewhere —
the Temporal design can reference rule IDs in activity descriptions.

```markdown
## Business Rules

- **BR-CO-01:** `orderType` must be `CANCEL` for cancellation flows.
- **BR-CO-02:** Cancellation can only proceed if the order is in a cancelable state
  (`received`, `in_progress`, or `on_hold`).
- **BR-CO-03:** In-flight provisioning tasks must be stopped before deprovisioning begins.
- **BR-CO-04:** Deprovisioning and inventory release are mandatory when the service has
  already started.
- **BR-CO-05:** Billing stop or reversal must be invoked if charges have been applied.
- Orders above $1,000 require **manager approval** before cancellation proceeds.
```

---

### `## Timers and SLAs`

State all time-based constraints. Use concrete durations, not vague terms.
These feed `extract_facts` → `timers` and inform Temporal timer nodes.

```markdown
## Timers and SLAs

- Eligibility check must complete within **10 seconds**; otherwise a timeout is raised.
- Deprovisioning must complete within **5 minutes**; on timeout, escalate to the
  Provisioning Platform team and retry.
- The entire cancellation workflow must complete within **2 hours** of the initial
  request; after this, an SLA-breach alert is raised to the Operations team.
- Cancel window: customers may only cancel within **30 days** of order creation.
```

---

### `## API Interfaces`

List every API call the workflow makes. These feed `extract_facts` → `apis` and
become Temporal activity stubs in the design. For each API, provide:
**system name**, **method**, **endpoint or action**, and **purpose**.

```markdown
## API Interfaces

| System | Method | Endpoint / Action | Purpose |
|---|---|---|---|
| OMS | POST | `/oms/order/cancel` | Accept cancellation request |
| Provisioning Platform | POST/DELETE | TMF640 Service Activation | Stop in-flight tasks, deprovision |
| Service Inventory | POST/PATCH | TMF638 | Release reserved resources |
| Billing / Mediation | POST | `/billing/stop-charges` | Stop or reverse charges |
| Notification Service | POST | `/notify/customer` | Send cancellation confirmation |
```

---

### `## Exceptions and Error Handling`

List every named exception or failure condition. These feed `extract_facts` →
`exceptions`. For each exception, state the **trigger** and the **handling action**.

```markdown
## Exceptions and Error Handling

- **Cancel window expired:** the order is past the 30-day cancel window → reject
  the request with reason `CANCEL_WINDOW_EXPIRED`.
- **Legal hold:** a compliance restriction blocks cancellation → block the workflow
  and escalate to the Compliance Officer.
- **Partial bundle cancel:** only one leg of a bundle is eligible for cancellation →
  compensate the remaining legs and continue with the eligible leg.
- **Deprovision failure:** the Provisioning Platform returns a 500 error → retry
  (see Retries section); on final failure, escalate to the Provisioning Team.
- **Billing reversal failure:** charge reversal is rejected → escalate to the
  Billing Team for manual resolution.
```

---

### `## Retries`

State retry policies explicitly per action. These feed `extract_facts` → `retries`
and directly populate `retry_policy` fields in the Temporal design.

```markdown
## Retries

- **Deprovision service:** retry up to **3 times** with **exponential backoff**
  starting at 5 seconds. After 3 failures, escalate.
- **Inventory release:** retry up to **3 times** with a fixed **10-second** delay.
- **Billing stop:** retry up to **2 times**. After 2 failures, escalate to Billing Team.
- **Notification send:** retry up to **5 times** with exponential backoff. Failure
  is non-fatal — log and continue.
```

---

### `## Compensation and Rollback`

Describe the saga compensations: what is undone, what triggered the rollback, and which
earlier activity each compensation reverses. These feed `extract_facts` →
`compensation_candidates` and `design_temporal` → `compensation_activities`.

Use the exact pattern: **"[Compensation action] compensates [original action]"** — this
phrasing is what the Temporal generator uses to wire compensation relationships.

```markdown
## Compensation and Rollback

- **Re-provision service** compensates **Deprovision service** — if the cancellation
  must be reversed after deprovisioning, restore the service configuration.
- **Restore inventory reservation** compensates **Release inventory** — return the
  released resources to the order's reservation if cancellation is reversed.
- **Reverse billing stop** compensates **Stop charges** — reinstate billing if the
  cancellation is voided.
- For partial bundle cancellations: **compensate remaining bundle legs** by leaving
  the non-cancelled legs in their current state and issuing a partial-cancel event.
```

---

## Writing style rules (applies to all sections)

These rules exist because the fact extraction and graph builder agents parse
prose literally. Ambiguous language produces low-confidence facts and sparse graphs.

| Do | Avoid |
|---|---|
| "The system validates the payment" | "Payment validation occurs" |
| "If the check fails, the workflow cancels the order" | "Failure leads to cancellation" |
| "Retries up to 3 times with exponential backoff" | "The system may retry a few times" |
| "In parallel, A and B" | "A and B happen at the same time" |
| "The order transitions from `received` to `cancelled`" | "The order becomes cancelled" |
| "Compensates DeactivateService" | "Undoes the deactivation" |
| "Within 24 hours" | "Quickly" / "in a timely manner" |
| "Via the Payment Gateway" | "Through the payment system" (use the exact system name) |

---

## Minimal valid example

Below is the smallest document that will produce a useful graph with high confidence.

```markdown
# Refund Request Workflow

## Metadata

| Field  | Value           |
|--------|-----------------|
| Domain | Customer Support |
| Owner  | Support Ops      |

## Purpose

This workflow processes a customer refund request from submission through approval
and payment, including fraud screening and handling of rejection cases.

## Trigger

The workflow starts when a **customer submits a refund request** via the support portal.

## Actors

- Customer
- Support Agent

## Systems

- Support Portal, Fraud Detection API, Payment Gateway, Email Service.

## States

- **Start states:** `Refund requested`
- **End states:** `Refund issued`, `Refund rejected`

## Process

1. The system **validates the refund request** (order ID exists, refund window open).
2. The Fraud Detection API **screens the request for fraud signals**.
3. If the request is **flagged as fraudulent**, the Support Agent is notified and the
   request is **placed on hold** for manual review.
4. If the request **passes screening**, the system **calculates the refund amount**
   based on the order total and return policy.
5. The Payment Gateway **issues the refund** to the original payment method.
6. If the refund **fails**, the system **retries up to 2 times**. On final failure,
   the Support Agent is notified to process manually.
7. The Email Service **sends a refund confirmation** to the customer.

## Business Rules

- Refund requests must be submitted within **30 days** of purchase.
- Refunds above $500 require **manager approval**.

## Timers and SLAs

- Fraud screening must complete within **30 seconds**; otherwise raise an SLA alert.
- The refund must be issued within **5 business days** of approval.

## Retries

- **Issue refund:** retry up to **2 times** with a **60-second** fixed delay.

## Compensation and Rollback

- **Reverse refund** compensates **Issue refund** — void the refund transaction if
  the order is later found to be fraudulent post-issuance.
```

---

## Checklist before submitting a document

- [ ] H1 title is the workflow name
- [ ] Metadata table includes Domain and Owner
- [ ] Purpose is 1–3 sentences of business intent (no process steps)
- [ ] Trigger uses "starts when" and names a concrete event
- [ ] Actors section lists only human roles (no systems)
- [ ] Systems section lists every named system used in the process steps
- [ ] States section has explicit start and end states in backticks
- [ ] Process steps are numbered, one activity per item
- [ ] Every decision has both branches stated explicitly
- [ ] Parallel activities use "in parallel"
- [ ] Every retry states a count and a delay
- [ ] Every compensation uses "compensates [original activity name]"
- [ ] SLAs use concrete durations (not "quickly" or "soon")

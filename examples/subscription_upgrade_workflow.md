# Subscription Plan Upgrade Workflow

## Metadata

| Field   | Value                                          |
|---------|------------------------------------------------|
| Domain  | Telecom OMS                                    |
| Owner   | Order Management Team                          |
| Version | 1.0                                            |
| Tags    | upgrade, subscription, saga, compensation, provisioning |

---

## Purpose

This workflow manages the end-to-end upgrade of a customer's active subscription plan,
including eligibility validation, proration billing, service re-provisioning with the
new entitlements, and rollback if any step fails. It ensures the customer is never
left without service during the transition.

---

## Trigger

The workflow starts when a **customer submits a subscription upgrade request** through
the self-service portal, mobile app, or a Care Agent submits the request via the CRM.

---

## Actors

- Customer
- Care Agent (CRM operator)
- Billing Team (for proration disputes)
- Compliance Officer (for regulatory plan changes)

---

## Systems

- OMS Temporal Workflow (orchestration)
- CRM / Care Console
- Product Catalog Service
- Entitlement Service
- Provisioning Platform (TMF640)
- Service Inventory (TMF638)
- Billing / Mediation System
- Payment Gateway
- Kafka Event Bus
- Notification Service
- Audit / Compliance Archive

---

## States

- **Start states:** `Upgrade requested`
- **End states:** `Upgrade completed`, `Upgrade failed`, `Upgrade rejected`

---

## Inputs and Outputs

**Inputs**
- `subscriptionId` — identifier of the active subscription to upgrade
- `targetPlanId` — identifier of the destination plan in the Product Catalog
- `effectiveDate` — `immediate` or an ISO-8601 future date
- `requestedBy` — `customer` or `agent`
- `promoCode` — optional promotional discount code

**Outputs**
- `upgradeId` — identifier of the completed upgrade transaction
- `newPlanId` — confirmed active plan identifier post-upgrade
- `proratedAmount` — billing adjustment applied (positive = charge, negative = credit)
- `provisioningStatus` — `completed` or `rolled_back`
- `effectiveTimestamp` — ISO-8601 time at which the new plan became active

---

## Process

1. The workflow receives the upgrade request and **validates the request payload**
   (subscriptionId, targetPlanId, and effectiveDate are all present and well-formed).
2. The Product Catalog Service **resolves the target plan** to confirm it exists,
   is published, and is available to the customer's market region.
3. The system **checks subscription eligibility** for upgrade: verifies the subscription
   is in an upgradeable state (`active` or `suspended`), checks for existing in-flight
   change orders, and validates contract lock-in rules.
4. If the subscription is **ineligible**, the workflow **rejects the upgrade request**,
   publishes an `oms.subscription.upgrade.rejected` event to the Kafka Event Bus, and
   transitions the subscription to `upgrade_rejected`. The workflow ends.
5. If the subscription is **eligible**, the Billing / Mediation System **calculates the
   proration amount** based on the current billing cycle, the old plan rate, and the
   new plan rate.
6. If a `promoCode` is provided, the Billing / Mediation System **validates and applies
   the promotional discount** to the proration amount.
7. The Payment Gateway **pre-authorises the proration charge** (if the proration amount
   is positive). If pre-authorisation fails, the workflow **rejects the upgrade request**
   and transitions to `upgrade_rejected`. The workflow ends.
8. The subscription transitions from `active` to `upgrade_in_progress`.
9. In parallel, the system:
   - **publishes an `oms.subscription.upgrade.started` event** to the Kafka Event Bus, and
   - **updates the entitlements** in the Entitlement Service with the new plan's feature set.
10. The Provisioning Platform (TMF640) **re-provisions the service** with the new plan's
    configuration, replacing the old entitlements with the new ones.
11. The Service Inventory (TMF638) **updates the resource reservation** to reflect the
    new plan's resource requirements.
12. The Payment Gateway **captures the pre-authorised proration charge** (if applicable).
13. If the charge capture **fails**, the workflow **reverses the provisioning**, restores
    the old entitlements, and escalates to the Billing Team for manual resolution.
    The subscription transitions to `upgrade_failed`. The workflow ends.
14. In parallel, the system:
    - **publishes an `oms.subscription.upgrade.completed` event** to the Kafka Event Bus, and
    - **sends an upgrade confirmation** to the customer via the Notification Service.
15. The Audit / Compliance Archive **records the upgrade transaction** with a full audit trail.
16. The subscription transitions from `upgrade_in_progress` to `active` with the new plan.

---

## Business Rules

- **BR-SU-01:** The target plan must have a higher tier or price than the current plan;
  downgrades are handled by a separate Downgrade Workflow.
- **BR-SU-02:** Upgrades can only be initiated if the subscription is in `active` or
  `suspended` state.
- **BR-SU-03:** Only one in-flight change order (upgrade, downgrade, or cancel) may be
  active on a subscription at any time.
- **BR-SU-04:** Proration is calculated as: `(days_remaining / days_in_cycle) × (new_rate − old_rate)`.
- **BR-SU-05:** Promotional codes must be validated against the Product Catalog before
  they are applied to the proration amount.
- **BR-SU-06:** The Payment Gateway pre-authorisation must be obtained before any
  provisioning change is applied.
- **BR-SU-07:** Entitlement updates and the Kafka event must be issued atomically
  (via the saga pattern); a failure in either must trigger full rollback.
- **BR-SU-08:** Upgrades affecting regulatory plan categories require a Compliance
  Officer review before provisioning begins.

---

## Timers and SLAs

- Request payload validation must complete within **5 seconds**; otherwise raise a
  timeout error and reject the request.
- Product Catalog plan resolution must complete within **10 seconds**; on timeout,
  retry once then fail.
- Eligibility check must complete within **15 seconds**; on timeout, escalate to the
  Order Management Team and halt the workflow.
- Payment Gateway pre-authorisation must complete within **30 seconds**; on timeout,
  treat as a pre-auth failure and reject the upgrade.
- Service re-provisioning must complete within **10 minutes**; on timeout, trigger
  rollback and escalate to the Provisioning Platform team.
- The entire upgrade workflow must complete within **30 minutes** of the initial
  request; after this deadline, an SLA-breach alert is raised to the Operations team.
- Promotional code validation must complete within **5 seconds**; on timeout, skip
  the discount and proceed without the promo code applied.

---

## API Interfaces

| System                      | Method | Endpoint / Action                   | Purpose                                      |
|-----------------------------|--------|--------------------------------------|----------------------------------------------|
| Product Catalog Service     | GET    | `/catalog/plans/{planId}`            | Resolve and validate target plan             |
| Entitlement Service         | PUT    | `/entitlements/{subscriptionId}`     | Update feature entitlements to new plan      |
| Billing / Mediation System  | POST   | `/billing/prorate`                   | Calculate proration amount                   |
| Billing / Mediation System  | POST   | `/billing/promo/validate`            | Validate and apply promotional discount      |
| Payment Gateway             | POST   | `/payments/pre-auth`                 | Pre-authorise proration charge               |
| Payment Gateway             | POST   | `/payments/capture/{preAuthId}`      | Capture pre-authorised charge                |
| Payment Gateway             | DELETE | `/payments/pre-auth/{preAuthId}`     | Release pre-authorisation on failure         |
| Provisioning Platform       | PUT    | TMF640 `/serviceActivation`          | Re-provision service with new plan config    |
| Service Inventory           | PATCH  | TMF638 `/resourceInventory`          | Update resource reservation for new plan     |
| Notification Service        | POST   | `/notify/customer`                   | Send upgrade confirmation to customer        |
| Audit / Compliance Archive  | POST   | `/audit/transactions`                | Record upgrade audit trail                   |
| Kafka Event Bus             | PUBLISH| `oms.subscription.upgrade.*`         | Publish lifecycle events                     |

---

## Exceptions and Error Handling

- **Plan not found:** the target plan does not exist in the Product Catalog → reject
  the upgrade with reason `PLAN_NOT_FOUND`.
- **Plan unavailable in region:** the target plan exists but is not available for the
  customer's market region → reject with reason `PLAN_REGION_UNAVAILABLE`.
- **Ineligible subscription state:** the subscription is not in `active` or `suspended`
  state → reject with reason `SUBSCRIPTION_NOT_UPGRADEABLE`.
- **Concurrent change order conflict:** another in-flight change order is already active
  → reject with reason `CONCURRENT_CHANGE_ORDER_CONFLICT` and advise the customer to
  retry after the current change order completes.
- **Invalid promotional code:** the promo code does not exist or has expired → skip
  the discount and continue without the promo code; notify the customer via the
  Notification Service.
- **Pre-authorisation failure:** the Payment Gateway declines the pre-auth → reject
  the upgrade with reason `PAYMENT_PRE_AUTH_FAILED` and notify the customer.
- **Provisioning timeout:** the Provisioning Platform does not respond within 10 minutes
  → trigger rollback (see Compensation and Rollback); escalate to the Provisioning
  Platform team.
- **Entitlement update failure:** the Entitlement Service returns a non-2xx response →
  retry (see Retries); on final failure, trigger rollback.
- **Charge capture failure:** the Payment Gateway declines the capture after provisioning
  succeeds → trigger rollback; escalate to the Billing Team for manual resolution.
- **Compliance hold:** the target plan falls under a regulated category and requires
  Compliance Officer approval → pause the workflow and send an approval request to the
  Compliance Officer. Resume on approval; reject on denial.

---

## Retries

- **Resolve target plan:** retry up to **2 times** with a **5-second** fixed delay.
  After 2 failures, fail the workflow with `PLAN_RESOLUTION_FAILED`.
- **Calculate proration:** retry up to **2 times** with a **5-second** fixed delay.
  After 2 failures, fail the workflow with `PRORATION_FAILED`.
- **Pre-authorise charge:** retry up to **1 time** with a **10-second** fixed delay.
  After 1 failure, reject the upgrade with `PAYMENT_PRE_AUTH_FAILED`.
- **Update entitlements:** retry up to **3 times** with **exponential backoff**
  starting at 5 seconds. After 3 failures, trigger full rollback.
- **Re-provision service:** retry up to **3 times** with **exponential backoff**
  starting at 10 seconds. After 3 failures, trigger full rollback and escalate.
- **Update resource inventory:** retry up to **3 times** with a **10-second** fixed delay.
  After 3 failures, trigger full rollback.
- **Capture charge:** retry up to **2 times** with a **15-second** fixed delay.
  After 2 failures, trigger rollback and escalate to the Billing Team.
- **Send notification:** retry up to **5 times** with **exponential backoff** starting
  at 2 seconds. Failure is non-fatal — log and continue.
- **Record audit trail:** retry up to **3 times** with a **5-second** fixed delay.
  Failure is non-fatal — log and alert the Compliance team.

---

## Compensation and Rollback

- **Restore old entitlements** compensates **Update entitlements** — if the workflow
  rolls back after entitlement update, reinstate the previous plan's feature set in
  the Entitlement Service.
- **Re-provision with old plan** compensates **Re-provision service** — if the workflow
  rolls back after provisioning, restore the service configuration to the original plan.
- **Restore old resource reservation** compensates **Update resource inventory** — return
  the resource reservation to the original plan's resource requirements in the Service
  Inventory.
- **Release pre-authorisation** compensates **Pre-authorise charge** — if the workflow
  rolls back before charge capture, release the held payment pre-authorisation via the
  Payment Gateway.
- **Reverse charge capture** compensates **Capture charge** — if post-capture rollback
  is required, void or refund the captured transaction via the Payment Gateway.
- **Publish rollback event** compensates **Publish upgrade started event** — publish an
  `oms.subscription.upgrade.rolled_back` event to the Kafka Event Bus to notify
  downstream consumers of the failed upgrade.

# Account Provisioning Workflow

<!--
  workflow-compiler specification (v1) — slug: account-provisioning
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
Prepares a registered customer's account for use by reserving an account number, configuring it based on a subscription plan, and activating it.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Customer Platform team, Provisioning Service
- systems: Provisioning Service
- triggers: customer record registered and account.provision request received
- start states: customer record registered
- end states: provisioning_status: active, provisioning_status: failed
- tags: 

## Inputs
- customer_record_id
- plan_code

## Outputs
- account_id
- provisioning_status

## Business Rules
- If configuration is invalid, raise ConfigurationInvalid and roll back provisioning
- Configure account with retry up to 3 times with exponential backoff starting at 1 second

## API Interfaces
- Provisioning Service (reserve account number, configure account, activate account)

## Systems Involved
- Provisioning Service
- Customer Platform

## Timers and SLAs
<!-- none -->

## Retries
- Configure account: up to 3 times with exponential backoff starting at 1 second

## Activities
- [a1] Reserve account number
- [a2] Configure account
- [a3] Activate account

## Decisions
- [d1] Is configuration valid? — after: a2; yes: a3; no: e1
- [d2] Is activation successful? — after: a3; yes: end; no: e2

## Exceptions
- [e1] ConfigurationInvalid — raised by: a2
- [e2] ActivationFailed — raised by: a3

## Compensations
- [c1] Roll back provisioning — compensates: a1
- [c2] Deconfigure and roll back — compensates: a2

## Events
- [ev1] account.provision request — kind: trigger; emitted by: start
- [ev2] account_id — kind: output_emit; emitted by: a1
- [ev3] provisioning_status — kind: output_emit; emitted by: a3

## State Transitions
<!-- none -->

## Assumptions
<!-- none -->

## Ambiguities
<!-- none -->

## Suggested Edits
<!-- none -->

## Open Questions
- [ ] (R6-bounded-waits) What deadline bounds each wait (e.g. 24 hours)?
  Answer: 

## Cross-Workflow Dependencies
- [ ] uses output `customer_record_id` of `customer-onboarding` as input `customer_record_id` — Account Provisioning consumes the customer_record_id produced by Customer Onboarding

## Triggers
<!-- none -->

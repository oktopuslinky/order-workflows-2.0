# Customer Onboarding Workflow

<!--
  workflow-compiler specification (v1) — slug: customer-onboarding
  This file is a projection of the structured spec. Edit it freely, then run
  `workflow-compiler validate <project-id>` to fold your edits back in.
  Lines you add are recorded as human-provided. Keep the `[id]` markers on
  existing entries so your edits update the right element.
-->

## Purpose
Registers a new customer by validating the application, verifying identity, creating a customer record, and notifying the customer of the outcome.

## Metadata
- domain: 
- owner: 
- version: 0.1.0
- actors: Customer, Onboarding Service, Identity Service, Customer Service, Notification Service, Provisioning Service
- systems: Onboarding Service, Identity Service, Customer Service, Notification Service, Provisioning Service
- triggers: 
- start states: new application submitted
- end states: rejected, registered
- tags: 

## Inputs
- application_id
- email

## Outputs
- customer_record_id
- onboarding_status

## Business Rules
- Application must be complete to proceed
- Identity verification required

## API Interfaces
- Onboarding Service.validateApplication
- Identity Service.verifyIdentity
- Customer Service.createCustomerRecord
- Notification Service.notifyCustomer

## Systems Involved
- Onboarding Service
- Identity Service
- Customer Service
- Notification Service

## Timers and SLAs
<!-- none -->

## Retries
- Verify customer identity: up to 3 times with exponential backoff (starting at 2 seconds)
- Notify customer: up to 5 times (non-fatal on failure)

## Activities
- [a1] Validate Application
- [a2] Verify Identity
- [a3] Create Customer Record
- [a4] Notify Customer

## Decisions
- [d1] Is Application Complete? — after: a1; yes: a2; no: e1

## Exceptions
- [e1] ApplicationIncomplete — raised by: a1
- [e2] IdentityCheckFailed — raised by: a2

## Compensations
<!-- none -->

## Events
- [ev1] application.received — kind: trigger; emitted by: start
- [ev2] onboarding_status — kind: output_emit; emitted by: a4

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
- [ ] What is the deadline for the application to be processed after submission?
  Answer: 

## Cross-Workflow Dependencies
- [ ] provides output `customer_record_id` to `account-provisioning` input `customer_record_id` — Account Provisioning consumes the customer_record_id produced by Customer Onboarding

## Triggers
- [ ] triggers `account-provisioning` (fire-and-forget) when `when a customer record is registered`
  input customer_record_id: step output `customer_record_id` (str)

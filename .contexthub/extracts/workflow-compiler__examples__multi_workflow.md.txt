# Customer Lifecycle Operations

This document describes two related but distinct business processes operated by
the Customer Platform team: customer onboarding and account provisioning.
Provisioning consumes the customer record produced by onboarding.

## Onboarding Purpose

The customer onboarding workflow registers a new customer: it validates the
application, verifies the customer's identity, creates the customer record, and
notifies the customer of the outcome.

## Onboarding Trigger

The workflow starts when a **customer application is submitted** and an
`application.received` request reaches the Onboarding Service.

## Onboarding Inputs and Outputs

**Inputs**
- `application_id` — identifier of the submitted application
- `email` — the applicant's email address

**Outputs**
- `customer_record_id` — identifier of the created customer record
- `onboarding_status` — `registered` or `rejected`

## Onboarding Process

1. The Onboarding Service **validates the application** using `application_id`
   and returns whether the application is complete.
2. If the application is **incomplete**, the workflow raises
   `ApplicationIncomplete` and rejects the application; if the application is
   **complete**, the workflow continues.
3. The Identity Service **verifies the customer identity** for `email` and
   returns a `verification_id`.
4. The Customer Service **creates the customer record** and returns a
   `customer_record_id`.
5. The Notification Service **notifies the customer** of the registration
   outcome.

## Onboarding Error Handling

- **ApplicationIncomplete:** the application is missing required fields →
  reject the application and end the workflow.
- **IdentityCheckFailed:** identity verification fails → reject the
  application and end the workflow.

## Onboarding Retries

- **Verify the customer identity:** retry up to **3 times** with exponential
  backoff starting at 2 seconds.
- **Notify the customer:** retry up to **5 times**; failure is non-fatal.

## Provisioning Purpose

The account provisioning workflow prepares a registered customer's account for
use: it reserves an account number, configures the account, and activates it.
If activation fails after configuration, the configuration is rolled back.

## Provisioning Trigger

The workflow starts when a **customer record is registered** and an
`account.provision` request reaches the Provisioning Service. It requires the
`customer_record_id` produced by customer onboarding.

## Provisioning Inputs and Outputs

**Inputs**
- `customer_record_id` — identifier of the registered customer record
- `plan_code` — the subscription plan to provision

**Outputs**
- `account_id` — identifier of the activated account
- `provisioning_status` — `active` or `failed`

## Provisioning Process

1. The Provisioning Service **reserves an account number** for
   `customer_record_id` and returns an `account_id`.
2. The Provisioning Service **configures the account** for `plan_code`.
3. If the configuration is **invalid**, the workflow raises
   `ConfigurationInvalid`; if the configuration is **valid**, the workflow
   continues.
4. The Provisioning Service **activates the account** and returns the final
   `provisioning_status`.

## Provisioning Error Handling

- **ConfigurationInvalid:** the plan configuration cannot be applied → roll
  back the provisioning (release the account number) and end the workflow.
- **ActivationFailed:** activation does not complete → roll back the
  provisioning (deconfigure the account, release the account number).

## Provisioning Retries

- **Configure the account:** retry up to **3 times** with exponential backoff
  starting at 1 second.

## Provisioning Compensation

- **Release the account number** compensates **Reserves an account number** —
  return the reserved number if provisioning is rolled back.
- **Deconfigure the account** compensates **Configures the account** — undo the
  plan configuration if provisioning is rolled back after configuration.

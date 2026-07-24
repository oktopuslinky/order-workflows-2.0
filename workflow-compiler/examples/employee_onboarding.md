# Employee Onboarding Workflow

## Purpose

This workflow describes how the People Operations team onboards a newly hired
employee, from offer acceptance through their first day, including IT provisioning,
compliance checks, and the handling of failures.

## Trigger

The workflow starts when a **candidate accepts an offer** in the HR system.

## Process

1. When the offer is accepted, the system **creates an employee record** in the HRIS.
2. The system **runs a background check** via the Screening API.
3. If the background check is **flagged**, the case is **escalated to a recruiter**
   for manual review and the onboarding is **paused** until a decision is recorded.
4. If the background check **passes**, in parallel the system:
   - **provisions IT accounts** (email, SSO, laptop) via the IT Service Desk, and
   - **enrolls the employee in payroll and benefits**.
5. The system **sends a welcome email** with first-day instructions.
6. The new hire must **complete required compliance training** within 7 days.
7. If account provisioning fails, the system **retries up to 3 times**. If it still
   fails, the partially created **accounts are de-provisioned** (compensation) and
   the case is marked as **onboarding failed**.

## Rules

- Background checks must complete within **48 hours**, otherwise an SLA-breach alert
  is raised to People Operations.
- Employees in regulated roles require **additional certification verification**
  before payroll enrollment.

## States

- Start states: `Offer accepted`.
- End states: `Onboarding complete`, `Onboarding failed`, `Candidate withdrawn`.

## Systems

- HRIS, Screening API, IT Service Desk, Payroll System, Learning Management System,
  Email Service.

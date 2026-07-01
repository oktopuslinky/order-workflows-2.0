<!--
MASTER WORKFLOW DOCUMENT — edit me, then re-run.

How to edit:
  * Each `# Heading` below is ONE workflow. Add a workflow you noticed by adding a
    new `# Name` section in the same shape; delete one by removing its section.
  * Fix any facts, steps, inputs, retries, or compensations directly in the prose.
  * Use "## Notes to the compiler" (global) and each "### Guidance" block (per
    workflow) to talk to the compiler: list missing flows, corrections, or priorities.
    These notes GUIDE the compiler on the next `reauthor` and are never compiled into
    code.
  * To make workflow A call workflow B, add a Process line:
    "The workflow invokes `B` as a child workflow."

Two ways to re-run:
  * Refine the document (another review round, reads your notes):
      workflow-compiler reauthor <this-file> --out <this-file>
  * Compile every workflow to a diagram + Temporal code:
      workflow-compiler compile-authored <this-file> --out-dir generated/
-->


## Notes to the compiler

<!-- Global notes to the compiler. List workflows you saw that are missing, corrections, or priorities. Read on `reauthor`. -->
_(no notes yet)_

## Workflows detected

- **CancelOrderWorkflow**

# CancelOrderWorkflow

## Metadata

| Field   | Value |
|---------|-------|
| Domain  | — |
| Owner   | — |
| Version | 0.1.0 |
| Tags    | — |

## Purpose

To facilitate the cancellation of existing orders through a defined interface.

## Trigger

_(trigger not extracted)_

## Actors

- _(none provided)_

## Systems

- _(none provided)_

## Inputs and Outputs

**Inputs (these become the workflow input fields)**
- _(none provided)_

**Outputs**
- _(none provided)_

## Process

1. _(no activities were extracted)_

## Business Rules

- _(none provided)_

## Timers and SLAs

- _(none provided)_

## API Interfaces

_(no external API calls were extracted)_

## Exceptions and Error Handling

- _(no exceptions were extracted)_

## Retries

- _(none provided)_

## Compensation and Rollback

- _(no compensations were extracted)_

### Guidance

<!-- Notes to the compiler about THIS workflow. Read on `reauthor`. -->
_(none)_

### Open questions

- What is the exact process for 'Manual review' (OMS-CO-409) and who performs it?
- How are 'Retry' and 'Escalate' actions (e.g., OMS-CO-429, OMS-CO-500) implemented in the workflow?

### Readiness gaps

- **R1-trigger** (required): What event starts this workflow (e.g. 'order.settle received')?
- **R2-inputs** (required): What named inputs does the workflow receive (e.g. order_id, amount)?
- **R3-outputs** (optional): What does the workflow produce when it completes?
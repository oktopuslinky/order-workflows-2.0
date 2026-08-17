# Business Requirements — Order Lifecycle

## 1. Purpose

Orders are captured, validated, provisioned and dispatched. If dispatch fails the
provisioning step is compensated (released) so no stock stays reserved.

## 2. Requirements

| ID | Requirement |
|---|---|
| BR-01 | An order must be validated before provisioning. |
| BR-02 | Dispatch failure must compensate provisioning. |
| BR-03 | The customer receives a status query at every stage. |

## 3. Stories

- US-001 Capture order
- US-002 Validate order
- US-003 Provision order (implements BR-01)
- US-004 Dispatch order (implements BR-02)

## 4. Test cases

- TC-01 validates a captured order (covers US-002)
- TC-02 compensates provisioning on dispatch failure (covers US-004)

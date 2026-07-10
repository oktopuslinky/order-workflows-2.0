# ReturnProcessingWorkflow (generated Temporal workflow)

Manages the return processing workflow from authorisation to refund.

This package was generated **deterministically** from a reviewed
`TemporalWorkflowDesign`. It is a runnable scaffold: the control flow, signals,
queries, timers, child workflows, retry policies, and saga compensation are
wired up, but each activity body raises `NotImplementedError` for you to fill in.

The files use **flat, absolute imports** (`from activities import ...`), matching
the layout in the Temporal Python docs, so each script is run directly from
inside this directory — no package installation or `PYTHONPATH` needed.

## Files

| File | Purpose |
|------|---------|
| `shared.py` | Dataclasses for workflow / activity inputs |
| `activities.py` | `@activity.defn` units of work (implement these) |
| `workflow.py` | `@workflow.defn` orchestration: `ReturnProcessingWorkflow` |
| `worker.py` | Worker registering the workflow + activities on `return-processing-queue` |
| `starter.py` | Client that starts one workflow execution |

## Run it

Install the SDK and start a local Temporal server:

```bash
pip install temporalio
temporal server start-dev          # terminal 1, leave running
```

From **inside this directory**, run the worker and then the starter:

```bash
python worker.py                   # terminal 2, leave running
python starter.py                  # terminal 3
```

The worker polls the `return-processing-queue` task queue; the starter submits a single
`ReturnProcessingWorkflow` execution and prints its result. Open the Web UI at
http://localhost:8233 to watch the execution.

## Next steps

- Implement each activity in `activities.py`.
- Populate the `WorkflowInput()` fields in `starter.py`.
- Replace the default `str` input fields in `shared.py` with real types.
- Review the generated retry policies and timeouts against your SLAs.

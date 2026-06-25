# Example workflows

Sample business workflow documents you can feed to `workflow-compiler`.

| File                     | Domain        | Highlights                                                        |
|--------------------------|---------------|-------------------------------------------------------------------|
| `order_workflow.md`      | E-commerce    | Payment validation, parallel fulfillment, retries, compensation.  |
| `employee_onboarding.md` | People Ops    | Background-check gate, parallel provisioning, SLA timer, rollback. |

## Try one

```bash
# Up to the review gate:
workflow-compiler compile examples/order_workflow.md

# End-to-end (skips the human gate):
workflow-compiler compile examples/employee_onboarding.md --auto-approve

# Just preview the graph + Mermaid diagram (no LLM persistence):
workflow-compiler inspect examples/order_workflow.md --out order.mmd
```

Each document exercises every stage of the pipeline: discovery, fact extraction,
graph building, structural review, CVPA classification, and Temporal design.
Paste the generated `.mmd` into <https://mermaid.live> to view the graph.

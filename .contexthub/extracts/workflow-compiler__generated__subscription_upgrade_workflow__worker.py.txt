"""Worker process for the SubscriptionUpgradeWorkflow workflow.

Start a local Temporal dev server in one terminal::

    temporal server start-dev

Then, from inside this package directory, run the worker::

    python worker.py

Keep it running, then start a workflow with ``python starter.py``.
"""

from __future__ import annotations

import asyncio

from temporalio import workflow
from temporalio.client import Client
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from workflow import SubscriptionUpgradeWorkflow
    from activities import (
        validate_request_payload,
        resolve_target_plan,
        check_subscription_eligibility,
        calculate_proration_amount,
        validate_and_apply_promotional_discount,
        pre_authorise_proration_charge,
        update_entitlements,
        re_provision_service,
        update_resource_inventory,
        capture_pre_authorised_charge,
        publish_events,
        send_upgrade_confirmation,
        record_audit_trail,
        restore_old_entitlements,
        re_provision_with_old_plan,
        restore_old_resource_reservation,
        release_pre_authorisation,
        reverse_charge_capture,
        publish_rollback_event,
    )

TASK_QUEUE = "subscription-upgrade-queue"


async def main() -> None:
    """Connect to Temporal and run the worker until cancelled."""
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[SubscriptionUpgradeWorkflow],
        activities=[validate_request_payload, resolve_target_plan, check_subscription_eligibility, calculate_proration_amount, validate_and_apply_promotional_discount, pre_authorise_proration_charge, update_entitlements, re_provision_service, update_resource_inventory, capture_pre_authorised_charge, publish_events, send_upgrade_confirmation, record_audit_trail, restore_old_entitlements, re_provision_with_old_plan, restore_old_resource_reservation, release_pre_authorisation, reverse_charge_capture, publish_rollback_event],
    )
    print(f"Worker started on task queue {TASK_QUEUE!r}. Press Ctrl+C to exit.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

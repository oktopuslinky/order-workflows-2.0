"""Shared dataclasses for the Cancelrequestworkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the Cancelrequestworkflow workflow."""

    order_id: int = 0
    order_type: str = ""
    flow_type: str = ""


@dataclass
class CancelrequestintakeInput:
    """Input to the matching activity / child workflow."""

    order_id: int = 0
    order_type: str = ""


@dataclass
class EligibilitycheckInput:
    """Input to the matching activity / child workflow."""

    request_id: str = ""


@dataclass
class DeprovisioningInput:
    """Input to the matching activity / child workflow."""

    request_id: str = ""


@dataclass
class InventoryreleaseInput:
    """Input to the matching activity / child workflow."""

    deprovision_status: str = ""


@dataclass
class CompensateremaininglegsInput:
    """Input to the matching activity / child workflow."""

    pass

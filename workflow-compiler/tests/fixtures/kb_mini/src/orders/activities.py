"""Activities used by the order workflow."""


def validate_order(order: dict) -> bool:
    """Validate the captured order (BR-01)."""
    return bool(order.get("items"))


def provision_order(order: dict) -> str:
    """Reserve stock for the order and return a provisioning id."""
    return f"prov-{order['id']}"


def dispatch_order(order: dict, provisioning_id: str) -> str:
    """Hand the order to the carrier."""
    if order.get("fail_dispatch"):
        raise RuntimeError("carrier rejected the shipment")
    return f"ship-{order['id']}"


def release_provisioning(provisioning_id: str) -> None:
    """Compensation for provision_order (BR-02)."""
    return None

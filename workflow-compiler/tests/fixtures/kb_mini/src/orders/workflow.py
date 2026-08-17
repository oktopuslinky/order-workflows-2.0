"""The order workflow: capture -> validate -> provision -> dispatch, with a saga."""

from .activities import dispatch_order, provision_order, release_provisioning, validate_order


class OrderWorkflow:
    """Runs the order lifecycle and compensates provisioning when dispatch fails."""

    def __init__(self) -> None:
        self.status = "captured"

    def run(self, order: dict) -> str:
        if not validate_order(order):
            self.status = "rejected"
            return self.status
        self.status = "validated"
        provisioning_id = provision_order(order)
        self.status = "provisioned"
        try:
            dispatch_order(order, provisioning_id)
        except RuntimeError:
            release_provisioning(provisioning_id)
            self.status = "compensated"
            raise
        self.status = "dispatched"
        return self.status

    def get_status(self) -> str:
        return self.status

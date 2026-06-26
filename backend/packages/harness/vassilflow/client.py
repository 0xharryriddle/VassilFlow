"""Client facade for VassilFlow integrations."""

from deerflow.client import DeerFlowClient, StreamEvent, StreamEventType


class VassilFlowClient(DeerFlowClient):
    """VassilFlow-named embedded client facade.

    The implementation still lives in ``deerflow.client.DeerFlowClient`` during
    the migration window; this subclass gives new integrations a stable
    VassilFlow-owned type name without changing runtime behavior.
    """

__all__ = ["DeerFlowClient", "StreamEvent", "StreamEventType", "VassilFlowClient"]

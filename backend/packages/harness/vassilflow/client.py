"""Client facade for VassilFlow integrations."""

from deerflow.client import DeerFlowClient, StreamEvent, StreamEventType

VassilFlowClient = DeerFlowClient

__all__ = ["DeerFlowClient", "StreamEvent", "StreamEventType", "VassilFlowClient"]

"""Runtime facade for VassilFlow integrations.

These names bridge to the current DeerFlow implementation. Boundary-level
statuses and entities live in :mod:`vassilflow.boundary`.
"""

from deerflow.runtime import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    ConflictError,
    DisconnectMode,
    MemoryStreamBridge,
    RunContext,
    RunManager,
    RunRecord,
    StreamBridge,
    StreamEvent,
    UnsupportedStrategyError,
    make_stream_bridge,
    run_agent,
)
from deerflow.runtime import (
    RunStatus as DeerFlowRunStatus,
)

RuntimeRunStatus = DeerFlowRunStatus
RunStatus = DeerFlowRunStatus

__all__ = [
    "ConflictError",
    "DeerFlowRunStatus",
    "DisconnectMode",
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "MemoryStreamBridge",
    "RunContext",
    "RunManager",
    "RunRecord",
    "RunStatus",
    "RuntimeRunStatus",
    "StreamBridge",
    "StreamEvent",
    "UnsupportedStrategyError",
    "make_stream_bridge",
    "run_agent",
]

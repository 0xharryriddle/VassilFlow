"""Runtime facade for VassilFlow integrations.

These names bridge to the current implementation modules. Boundary-level
statuses and entities live in :mod:`vassilflow.boundary`.
"""

from importlib import import_module

_runtime_impl = import_module("deerflow.runtime")

_IMPLEMENTATION_EXPORTS = [
    "ConflictError",
    "DisconnectMode",
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "MemoryStreamBridge",
    "RunContext",
    "RunManager",
    "RunRecord",
    "RunStatus",
    "StreamBridge",
    "StreamEvent",
    "UnsupportedStrategyError",
    "checkpointer_context",
    "get_checkpointer",
    "get_store",
    "make_checkpointer",
    "make_store",
    "make_stream_bridge",
    "reset_checkpointer",
    "reset_store",
    "run_agent",
    "serialize",
    "serialize_channel_values",
    "serialize_channel_values_for_api",
    "serialize_lc_object",
    "serialize_messages_tuple",
    "store_context",
    "strip_data_url_image_blocks",
]

globals().update({name: getattr(_runtime_impl, name) for name in _IMPLEMENTATION_EXPORTS})

DeerFlowRunStatus = _runtime_impl.RunStatus
RuntimeRunStatus = _runtime_impl.RunStatus
RunStatus = _runtime_impl.RunStatus
VassilFlowRunStatus = _runtime_impl.RunStatus

__all__ = sorted(
    [
        *_IMPLEMENTATION_EXPORTS,
        "DeerFlowRunStatus",
        "RunStatus",
        "RuntimeRunStatus",
        "VassilFlowRunStatus",
    ]
)

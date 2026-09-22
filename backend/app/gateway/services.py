"""Run lifecycle service layer.

Centralizes the business logic for creating runs, formatting SSE
frames, and consuming stream bridge events.  Router modules
(``thread_runs``, ``runs``) are thin HTTP handlers that delegate here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import convert_to_messages
from langgraph.types import Command

from app.gateway.agent_runtime_readiness import (
    enforce_agent_runtime_readiness,
)
from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
from app.gateway.capability_inputs import (
    extract_capability_inputs,
    inject_trusted_capability_inputs,
    resolve_capability_inputs_for_run,
)
from app.gateway.deps import get_checkpointer, get_local_provider, get_run_context, get_run_manager, get_stream_bridge
from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE, get_trusted_internal_owner_user_id
from app.gateway.utils import sanitize_log_param
from vassilflow.capabilities import CAPABILITY_INPUTS_CONTEXT_KEY
from vassilflow.config.agent_contract import (
    DEFAULT_ASSISTANT_ID,
    CanonicalAgentIdentity,
    resolve_agent_identity,
    validate_agent_identity_claim,
)
from vassilflow.config.app_config import get_app_config
from vassilflow.config.builtin_agents import is_builtin_agent
from vassilflow.runtime import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    ConflictError,
    DisconnectMode,
    RunManager,
    RunRecord,
    RunStatus,
    StreamBridge,
    UnsupportedStrategyError,
    run_agent,
)
from vassilflow.runtime.context_compaction import thread_context_lock
from vassilflow.runtime.runs.naming import resolve_root_run_name
from vassilflow.runtime.secret_context import redact_config_secrets
from vassilflow.runtime.user_context import reset_current_user, set_current_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSE formatting
# ---------------------------------------------------------------------------


def format_sse(event: str, data: Any, *, event_id: str | None = None) -> str:
    """Format a single SSE frame.

    Field order: ``event:`` -> ``data:`` -> ``id:`` (optional) -> blank line.
    This matches the LangGraph Platform wire format consumed by the
    ``useStream`` React hook and the Python ``langgraph-sdk`` SSE decoder.
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Input / config helpers
# ---------------------------------------------------------------------------


def normalize_stream_modes(raw: list[str] | str | None) -> list[str]:
    """Normalize the stream_mode parameter to a list.

    Default matches what ``useStream`` expects: values + messages-tuple.
    """
    if raw is None:
        return ["values"]
    if isinstance(raw, str):
        return [raw]
    return raw if raw else ["values"]


def normalize_input(raw_input: dict[str, Any] | None) -> dict[str, Any]:
    """Convert LangGraph Platform input format to LangChain state dict.

    Delegates dict→message coercion to ``langchain_core.messages.utils.convert_to_messages``
    so that ``additional_kwargs`` (e.g. uploaded-file metadata — gh #3132), ``id``,
    ``name``, and non-human roles (ai/system/tool) survive unchanged.  An earlier
    hand-rolled version only forwarded ``content`` and collapsed every role to
    ``HumanMessage``, which silently stripped frontend-supplied attachments.

    Malformed message dicts (missing ``role``/``type``/``content``, unsupported
    role, etc.) raise ``HTTPException(400)`` with the offending index, instead
    of bubbling up as a 500.  The gateway is a system boundary, so per-entry
    validation errors are the right shape for clients to retry against.
    """
    if raw_input is None:
        return {}
    messages = raw_input.get("messages")
    if messages and isinstance(messages, list):
        converted: list[Any] = []
        for index, msg in enumerate(messages):
            if isinstance(msg, BaseMessage):
                converted.append(msg)
            elif isinstance(msg, dict):
                try:
                    converted.extend(convert_to_messages([msg]))
                except (ValueError, TypeError, NotImplementedError) as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid message at input.messages[{index}]: {exc}",
                    ) from exc
            else:
                converted.append(msg)
        return {**raw_input, "messages": converted}
    return raw_input


_DEFAULT_ASSISTANT_ID = DEFAULT_ASSISTANT_ID
_DEFAULT_RECURSION_LIMIT = 100
_DEFAULT_MAX_RECURSION_LIMIT = 1000


# Whitelist of run-context keys that the langgraph-compat layer forwards from
# ``body.context`` into the run config. ``config["context"]`` exists in
# LangGraph >=0.6, but these values must be written to both ``configurable``
# (for legacy ``_get_runtime_config`` consumers) and ``context`` because
# LangGraph >=1.1.9 no longer makes ``ToolRuntime.context`` fall back to
# ``configurable`` for consumers like ``setup_agent``.
_CONTEXT_CONFIGURABLE_KEYS: frozenset[str] = frozenset(
    {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "is_bootstrap",
        "bootstrap_agent_name",
    }
)

# Keys honored only for internally-authenticated callers.
# ``non_interactive`` strips ``ask_clarification`` from the lead-agent toolset;
# browser/API clients must not be able to force autonomous execution.
_CONTEXT_INTERNAL_CALLER_KEYS: frozenset[str] = frozenset({"non_interactive"})

# Keys forwarded from ``body.context`` into ``config['context']`` only, never
# into ``config['configurable']``. ``configurable`` is persisted in checkpoints,
# so request-scoped secrets such as ``github_token`` must stay out of it.
_CONTEXT_RUNTIME_ONLY_KEYS: frozenset[str] = frozenset({"github_token", "disable_clarification"})
_SERVER_OWNED_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "agent_name",
        "assistant_id",
        "bootstrap_agent_name",
        "agent_allowed_tools",
        "agent_allow_acp_agents",
        "agent_allow_mcp_tools",
        "agent_data_access",
        "agent_policy",
        CAPABILITY_INPUTS_CONTEXT_KEY,
    }
)
_SERVER_OWNED_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "agent_name",
        "assistant_id",
        "agent_origin",
        "tool_groups",
        "allowed_tools",
        "agent_data_access",
        "agent_allow_acp_agents",
        "agent_allow_mcp_tools",
        "agent_policy_version",
        "available_skills",
    }
)


def sanitize_run_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove runtime-owned identity and policy claims from client metadata."""

    if not metadata:
        return {}
    return {key: value for key, value in metadata.items() if not (isinstance(key, str) and (key.startswith("__") or key in _SERVER_OWNED_METADATA_KEYS))}


def sanitize_thread_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build thread metadata without duplicating the canonical identity."""

    return sanitize_run_metadata(metadata)


def validate_run_agent_identity_claims(
    identity: CanonicalAgentIdentity,
    *,
    request_config: Mapping[str, Any] | None = None,
    request_context: Mapping[str, Any] | None = None,
) -> None:
    """Validate legacy identity hints without allowing them to route a run."""

    if request_config:
        for section_name in ("configurable", "context"):
            section = request_config.get(section_name)
            if isinstance(section, Mapping) and "agent_name" in section:
                validate_agent_identity_claim(
                    identity,
                    section.get("agent_name"),
                    source=f"config.{section_name}",
                )
    if request_context and "agent_name" in request_context:
        validate_agent_identity_claim(
            identity,
            request_context.get("agent_name"),
            source="context",
        )


def inject_canonical_agent_identity(
    config: dict[str, Any],
    identity: CanonicalAgentIdentity,
) -> None:
    """Stamp the server-owned identity into every runtime-visible container."""

    for section_name in ("configurable", "context"):
        section = config.get(section_name)
        if section is None and identity.is_default:
            continue
        if section is None:
            section = config.setdefault(section_name, {})
        if not isinstance(section, dict):
            raise ValueError(f"request config {section_name!r} must be an object")
        if identity.agent_name is None:
            section.pop("agent_name", None)
        else:
            section["agent_name"] = identity.agent_name

    metadata = config.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("request config 'metadata' must be an object")
    metadata["assistant_id"] = identity.assistant_id
    if identity.agent_name is None:
        metadata.pop("agent_name", None)
    else:
        metadata["agent_name"] = identity.agent_name


async def enforce_thread_agent_identity(
    thread_store: Any,
    thread_id: str,
    identity: CanonicalAgentIdentity,
    *,
    record: Mapping[str, Any] | None = None,
    upgrade_legacy: bool = True,
) -> None:
    """Keep one canonical Agent identity for the lifetime of a thread."""

    if record is None:
        record = await thread_store.get(thread_id)
    if record is None:
        return
    try:
        stored = resolve_agent_identity(record.get("assistant_id"))
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="Thread has an invalid stored assistant identity",
        ) from exc
    if stored.assistant_id == identity.assistant_id:
        return

    # Before canonical assistant IDs, Agent chats were stored as lead_agent
    # with the real name only in metadata. Upgrade that exact legacy shape.
    legacy_name = (record.get("metadata") or {}).get("agent_name")
    if stored.is_default and identity.agent_name is not None:
        try:
            legacy_identity = resolve_agent_identity(legacy_name)
        except ValueError:
            legacy_identity = None
        if legacy_identity is not None and legacy_identity == identity:
            if upgrade_legacy:
                await thread_store.update_assistant_id(
                    thread_id,
                    identity.assistant_id,
                )
            return

    raise HTTPException(
        status_code=409,
        detail=(f"Thread is bound to assistant {stored.assistant_id!r}, not {identity.assistant_id!r}"),
    )


async def bind_thread_agent_identity(
    thread_store: Any,
    thread_id: str,
    identity: CanonicalAgentIdentity,
    *,
    metadata: Mapping[str, Any] | None,
    owner_user_id: str | None,
) -> None:
    """Atomically create or validate the thread's canonical Agent binding.

    The caller must hold ``thread_context_lock(thread_id)``. Database uniqueness
    remains the cross-worker arbiter; when another worker wins creation, the
    winning row is re-read and validated before this run can proceed.
    """

    existing = await thread_store.get(thread_id)
    if existing is None and owner_user_id:
        unscoped = await thread_store.get(thread_id, user_id=None)
        if unscoped is not None:
            if unscoped.get("user_id") != owner_user_id:
                await thread_store.update_owner(
                    thread_id,
                    owner_user_id,
                    user_id=None,
                )
            existing = await thread_store.get(thread_id)

    if existing is None:
        try:
            await thread_store.create(
                thread_id,
                assistant_id=identity.assistant_id,
                metadata=sanitize_thread_metadata(metadata),
            )
            return
        except Exception:
            # A different worker may have inserted the globally unique thread
            # between our read and create. Only continue if its binding agrees.
            existing = await thread_store.get(thread_id)
            if existing is None:
                raise

    await enforce_thread_agent_identity(
        thread_store,
        thread_id,
        identity,
        record=existing,
    )


def strip_internal_context_keys(config: dict[str, Any]) -> None:
    """Drop internal-only keys a non-internal caller smuggled into run config."""

    for section in ("context", "configurable"):
        value = config.get(section)
        if isinstance(value, dict):
            for key in _CONTEXT_INTERNAL_CALLER_KEYS:
                value.pop(key, None)


def merge_run_context_overrides(config: dict[str, Any], context: Mapping[str, Any] | None, *, internal: bool = False) -> None:
    """Merge whitelisted keys from ``body.context`` into both ``config['configurable']``
    and ``config['context']`` so they are visible to legacy configurable readers and
    to LangGraph ``ToolRuntime.context`` consumers (e.g. the ``setup_agent`` tool —
    see issue #2677).

    ``user_id`` is intentionally propagated into ``config['context']`` in addition to
    the whitelisted keys, so non-web callers (e.g. IM channels) that supply identity in
    ``body.context`` keep it on ``ToolRuntime.context``. It is merged with
    ``setdefault`` so a server-authenticated id stamped by
    :func:`inject_authenticated_user_context` always wins over the client-supplied one.
    Internal-only caller keys are accepted only when ``internal`` is true. A
    second set of runtime-only keys is written to ``config['context']`` only so
    request-scoped secrets and runtime flags are not checkpointed through
    ``configurable``.
    """
    if not context:
        return
    configurable = config.setdefault("configurable", {})
    runtime_context = config.setdefault("context", {})
    keys = _CONTEXT_CONFIGURABLE_KEYS | _CONTEXT_INTERNAL_CALLER_KEYS if internal else _CONTEXT_CONFIGURABLE_KEYS
    for key in keys:
        if key in context:
            value = context[key]
            if key == "bootstrap_agent_name":
                bootstrap_enabled = (
                    context.get("is_bootstrap") is True or (isinstance(configurable, Mapping) and configurable.get("is_bootstrap") is True) or (isinstance(runtime_context, Mapping) and runtime_context.get("is_bootstrap") is True)
                )
                if not bootstrap_enabled:
                    raise HTTPException(
                        status_code=400,
                        detail="bootstrap_agent_name requires bootstrap mode",
                    )
                try:
                    target_identity = resolve_agent_identity(value)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                if target_identity.is_default or is_builtin_agent(target_identity.agent_name):
                    raise HTTPException(
                        status_code=400,
                        detail="bootstrap_agent_name must identify a new personal Agent",
                    )
                value = target_identity.agent_name
            if isinstance(configurable, dict):
                configurable.setdefault(key, value)
            if isinstance(runtime_context, dict):
                runtime_context.setdefault(key, value)
    for key in _CONTEXT_RUNTIME_ONLY_KEYS:
        if key in context and isinstance(runtime_context, dict):
            runtime_context.setdefault(key, context[key])
    if "user_id" in context and isinstance(runtime_context, dict):
        runtime_context.setdefault("user_id", context["user_id"])
    if "channel_user_id" in context and isinstance(runtime_context, dict):
        runtime_context.setdefault("channel_user_id", context["channel_user_id"])


async def resolve_trusted_internal_owner_for_attribution(request: Request, owner_user_id: str | None) -> Any | None:
    """Resolve the VassilFlow user used only for trusted internal attribution."""

    if not owner_user_id:
        return None
    user = getattr(request.state, "user", None)
    if getattr(user, "system_role", None) != INTERNAL_SYSTEM_ROLE:
        return None
    try:
        return await get_local_provider().get_user(owner_user_id)
    except Exception:
        logger.exception("Failed to resolve trusted internal owner %s", sanitize_log_param(owner_user_id))
        return None


def inject_authenticated_user_context(
    config: dict[str, Any],
    request: Request,
    *,
    internal_owner_user: Any | None = None,
) -> None:
    """Stamp the authenticated user into the run context for background tools.

    Tool execution may happen after the request handler has returned, so tools
    that persist user-scoped files should not rely only on ambient ContextVars.
    The value comes from server-side auth state, never from client context.
    """

    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        return

    if getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
        runtime_context = config.setdefault("context", {})
        if not isinstance(runtime_context, dict):
            return
        if internal_owner_user is None:
            runtime_context.pop("user_role", None)
            runtime_context.pop("oauth_provider", None)
            runtime_context.pop("oauth_id", None)
            return
        owner_user_id = getattr(internal_owner_user, "id", None)
        if owner_user_id is not None:
            runtime_context["user_id"] = str(owner_user_id)
        runtime_context["user_role"] = getattr(internal_owner_user, "system_role", None)
        runtime_context["oauth_provider"] = getattr(internal_owner_user, "oauth_provider", None)
        runtime_context["oauth_id"] = getattr(internal_owner_user, "oauth_id", None)
        return

    runtime_context = config.setdefault("context", {})
    if isinstance(runtime_context, dict):
        runtime_context["user_id"] = str(user_id)
        runtime_context["user_role"] = getattr(user, "system_role", None)
        runtime_context["oauth_provider"] = getattr(user, "oauth_provider", None)
        runtime_context["oauth_id"] = getattr(user, "oauth_id", None)


def resolve_agent_factory(assistant_id: str | None):
    """Resolve the agent factory callable from config.

    Custom agents are implemented as ``lead_agent`` + an ``agent_name``
    injected into ``configurable`` or ``context`` — see
    :func:`build_run_config`.  All ``assistant_id`` values therefore map to the
    same factory; the routing happens inside ``make_lead_agent`` when it reads
    ``cfg["agent_name"]``.
    """
    from vassilflow.agents.lead_agent.agent import make_lead_agent

    return make_lead_agent


def _resolve_max_recursion_limit() -> int:
    """Resolve the server-side ceiling for client supplied recursion limits."""
    try:
        return get_app_config().max_recursion_limit
    except Exception:
        return _DEFAULT_MAX_RECURSION_LIMIT


def _clamp_recursion_limit(value: Any, max_limit: int) -> int:
    """Clamp a client supplied recursion_limit into a safe server range."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return _DEFAULT_RECURSION_LIMIT
    return min(value, max_limit)


def build_run_config(
    thread_id: str,
    request_config: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    *,
    assistant_id: str | None = None,
) -> dict[str, Any]:
    """Build a RunnableConfig dict for the agent.

    When *assistant_id* refers to a custom agent (anything other than
    ``"lead_agent"`` / ``None``), the name is forwarded as ``agent_name`` in
    both ``configurable`` and ``context`` so it is visible to legacy
    configurable readers and to LangGraph ``ToolRuntime.context`` consumers
    (e.g. the ``setup_agent`` tool, which since LangGraph >=1.1.9 no longer
    falls back from ``context`` to ``configurable``). Client-supplied
    ``agent_name`` hints are accepted only when they match the canonical
    identity derived from ``assistant_id``. ``make_lead_agent`` reads this key to
    load the matching ``agents/<name>/SOUL.md`` and per-agent config —
    without it the agent silently runs as the default lead agent.

    This mirrors the channel manager's ``_resolve_run_params`` logic so that
    the LangGraph Platform-compatible HTTP API and the IM channel path behave
    identically.
    """
    identity = resolve_agent_identity(assistant_id)
    validate_run_agent_identity_claims(identity, request_config=request_config)

    # Lead-agent recursion budget (LangGraph super-steps for the lead graph
    # only). Independent of subagent depth: a `task()` dispatch runs the whole
    # subagent inside ONE lead tools-node step, and subagents enforce their own
    # limit via `subagents.max_turns`. Do not conflate this 100 with the
    # general-purpose subagent's max_turns.
    config: dict[str, Any] = {"recursion_limit": _DEFAULT_RECURSION_LIMIT}
    if request_config:
        # LangGraph >= 0.6.0 introduced ``context`` as the preferred way to
        # pass thread-level data and rejects requests that include both
        # ``configurable`` and ``context``.  If the caller already sends
        # ``context``, honour it and skip our own ``configurable`` dict.
        if "context" in request_config:
            if "configurable" in request_config:
                logger.warning(
                    "build_run_config: client sent both 'context' and 'configurable'; preferring 'context' (LangGraph >= 0.6.0). thread_id=%s, caller_configurable keys=%s",
                    thread_id,
                    list(request_config.get("configurable", {}).keys()),
                )
            context_value = request_config["context"]
            if context_value is None:
                context = {}
            elif isinstance(context_value, Mapping):
                context = {key: value for key, value in context_value.items() if not (isinstance(key, str) and (key.startswith("__") or key in _SERVER_OWNED_CONTEXT_KEYS))}
            else:
                raise ValueError("request config 'context' must be a mapping or null.")
            context["thread_id"] = thread_id
            config["context"] = context
            config["configurable"] = {"thread_id": thread_id}
        else:
            configurable = {"thread_id": thread_id}
            requested_configurable = request_config.get("configurable", {})
            if requested_configurable is None:
                requested_configurable = {}
            if not isinstance(requested_configurable, Mapping):
                raise ValueError("request config 'configurable' must be a mapping or null.")
            configurable.update({key: value for key, value in requested_configurable.items() if key != "thread_id" and key not in _SERVER_OWNED_CONTEXT_KEYS})
            config["configurable"] = configurable
        for k, v in request_config.items():
            if k not in ("configurable", "context", "metadata"):
                config[k] = v
        request_metadata = request_config.get("metadata")
        if request_metadata is not None:
            if not isinstance(request_metadata, Mapping):
                raise ValueError("request config 'metadata' must be a mapping or null.")
            config["metadata"] = sanitize_run_metadata(request_metadata)
        if "recursion_limit" in request_config:
            max_limit = _resolve_max_recursion_limit()
            clamped = _clamp_recursion_limit(request_config["recursion_limit"], max_limit)
            if clamped != request_config["recursion_limit"]:
                logger.warning(
                    "build_run_config: clamped client recursion_limit %r -> %d (max %d). thread_id=%s",
                    request_config["recursion_limit"],
                    clamped,
                    max_limit,
                    thread_id,
                )
            config["recursion_limit"] = clamped
    else:
        config["configurable"] = {"thread_id": thread_id}

    if not identity.is_default:
        config.setdefault("run_name", resolve_root_run_name(config, identity.agent_name))
    sanitized_metadata = sanitize_run_metadata(metadata)
    if sanitized_metadata:
        config.setdefault("metadata", {}).update(sanitized_metadata)
    inject_canonical_agent_identity(config, identity)
    return config


async def apply_checkpoint_to_run_config(
    config: dict[str, Any],
    *,
    body: Any,
    thread_id: str,
    request: Request,
) -> None:
    """Validate an optional run checkpoint and attach it to RunnableConfig."""
    checkpoint = getattr(body, "checkpoint", None)
    checkpoint_id = getattr(body, "checkpoint_id", None)
    checkpoint_ns = ""
    checkpoint_map = None

    if checkpoint:
        if not isinstance(checkpoint, Mapping):
            raise HTTPException(status_code=400, detail="checkpoint must be an object")
        checkpoint_thread_id = checkpoint.get("thread_id")
        if checkpoint_thread_id is not None and str(checkpoint_thread_id) != thread_id:
            raise HTTPException(status_code=400, detail="checkpoint thread_id does not match request thread_id")
        raw_checkpoint_id = checkpoint.get("checkpoint_id")
        if raw_checkpoint_id:
            checkpoint_id = str(raw_checkpoint_id)
        raw_checkpoint_ns = checkpoint.get("checkpoint_ns")
        if raw_checkpoint_ns is not None:
            checkpoint_ns = str(raw_checkpoint_ns)
        checkpoint_map = checkpoint.get("checkpoint_map")

    if not checkpoint_id:
        return

    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": str(checkpoint_id),
        }
    }
    if checkpoint_map is not None:
        read_config["configurable"]["checkpoint_map"] = checkpoint_map

    checkpointer = get_checkpointer(request)
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(read_config)
    except Exception as exc:
        logger.exception("Failed to validate checkpoint %s for thread %s", checkpoint_id, sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to validate checkpoint") from exc
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Checkpoint {checkpoint_id} not found")

    configurable = config.setdefault("configurable", {})
    if not isinstance(configurable, dict):
        raise HTTPException(status_code=400, detail="request config configurable must be an object")
    configurable["thread_id"] = thread_id
    configurable["checkpoint_ns"] = checkpoint_ns
    configurable["checkpoint_id"] = str(checkpoint_id)
    if checkpoint_map is not None:
        configurable["checkpoint_map"] = checkpoint_map


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def start_run(
    body: Any,
    thread_id: str,
    request: Request,
) -> RunRecord:
    """Create a RunRecord and launch the background agent task.

    Parameters
    ----------
    body : RunCreateRequest
        The validated request body (typed as Any to avoid circular import
        with the router module that defines the Pydantic model).
    thread_id : str
        Target thread.
    request : Request
        FastAPI request — used to retrieve singletons from ``app.state``.
    """
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    try:
        identity = resolve_agent_identity(body.assistant_id)
        validate_run_agent_identity_claims(
            identity,
            request_config=getattr(body, "config", None),
            request_context=getattr(body, "context", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    disconnect = DisconnectMode.cancel if body.on_disconnect == "cancel" else DisconnectMode.continue_

    body_context = getattr(body, "context", None) or {}
    model_name = body_context.get("model_name")

    # Coerce non-string model_name values to str before truncation.
    if model_name is not None and not isinstance(model_name, str):
        model_name = str(model_name)

    # Validate model against the allowlist when a model_name is provided.
    if model_name:
        app_config = get_app_config()
        resolved = app_config.get_model_config(model_name)
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"Model {model_name!r} is not in the configured model allowlist",
            )

    owner_user_id = get_trusted_internal_owner_user_id(request)
    # Stateless run endpoints carry thread_id in the request *body*, so the
    # @require_permission(owner_check=True) decorator -- which resolves ownership
    # from the path param -- cannot protect them. Enforce thread ownership here,
    # before any run is created, so one user cannot start runs on (or read /wait
    # checkpoint state from) another user's thread. Missing rows (auto-created
    # temp threads) and NULL-owner rows (shared / pre-auth data) stay accessible
    # via check_access; only a thread already owned by another user is rejected
    # with 404, matching thread_runs.py's anti-enumeration behaviour. Internal
    # channel runs act on behalf of the connection owner carried in
    # X-VassilFlow-Owner-User-Id, so they are scoped to that owner instead of
    # bypassing the check -- a leaked internal token must not grant cross-user
    # thread access.
    user = getattr(request.state, "user", None)
    if user is not None:
        allowed = await run_ctx.thread_store.check_access(thread_id, str(user.id))
        if not allowed and owner_user_id and getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
            # Channel workers may also act for the connection owner named in
            # the trusted header (e.g. claiming a legacy default-owned channel
            # thread for its real owner).
            allowed = await run_ctx.thread_store.check_access(thread_id, owner_user_id)
        if not allowed:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    owner_context_token = set_current_user(SimpleNamespace(id=owner_user_id)) if owner_user_id else None
    try:
        capability_user_id = owner_user_id or (str(user.id) if user is not None and getattr(user, "id", None) is not None else "default")
        existing_thread = await run_ctx.thread_store.get(thread_id)
        if existing_thread is None:
            # Ownership was checked above. This read catches accessible legacy
            # rows without an owner before any domain or checkpoint lookup.
            existing_thread = await run_ctx.thread_store.get(
                thread_id,
                user_id=None,
            )
        await enforce_thread_agent_identity(
            run_ctx.thread_store,
            thread_id,
            identity,
            record=existing_thread,
            upgrade_legacy=False,
        )
        resolved_capability_inputs = await resolve_capability_inputs_for_run(
            extract_capability_inputs(body),
            identity=identity,
            user_id=capability_user_id,
        )
        await enforce_agent_runtime_readiness(
            identity,
            get_app_config(),
            user_id=capability_user_id,
        )
        agent_factory = resolve_agent_factory(identity.assistant_id)
        command = getattr(body, "command", None)
        if command and command.get("resume") is not None:
            graph_input = Command(resume=command["resume"])
        else:
            graph_input = normalize_input(body.input)
        try:
            config = build_run_config(
                thread_id,
                body.config,
                body.metadata,
                assistant_id=identity.assistant_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await apply_checkpoint_to_run_config(
            config,
            body=body,
            thread_id=thread_id,
            request=request,
        )

        is_internal_caller = getattr(getattr(request, "state", None), "auth_source", None) == AUTH_SOURCE_INTERNAL
        merge_run_context_overrides(
            config,
            getattr(body, "context", None),
            internal=is_internal_caller,
        )
        if not is_internal_caller:
            strip_internal_context_keys(config)
        internal_owner_user = await resolve_trusted_internal_owner_for_attribution(
            request,
            owner_user_id,
        )
        inject_authenticated_user_context(
            config,
            request,
            internal_owner_user=internal_owner_user,
        )
        inject_trusted_capability_inputs(
            config,
            resolved_capability_inputs,
        )
        stream_modes = normalize_stream_modes(body.stream_mode)

        try:
            async with thread_context_lock(thread_id):
                await bind_thread_agent_identity(
                    run_ctx.thread_store,
                    thread_id,
                    identity,
                    metadata=body.metadata,
                    owner_user_id=owner_user_id,
                )
                record = await run_mgr.create_or_reject(
                    thread_id,
                    identity.assistant_id,
                    on_disconnect=disconnect,
                    metadata=sanitize_run_metadata(body.metadata),
                    kwargs={"input": body.input, "config": redact_config_secrets(body.config)},
                    multitask_strategy=body.multitask_strategy,
                    model_name=model_name,
                    user_id=owner_user_id,
                )
                try:
                    await run_ctx.thread_store.update_status(thread_id, "running")
                except Exception:
                    logger.warning(
                        "Failed to mark thread_meta running for %s (non-fatal)",
                        sanitize_log_param(thread_id),
                    )
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except UnsupportedStrategyError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

        task = asyncio.create_task(
            run_agent(
                bridge,
                run_mgr,
                record,
                ctx=run_ctx,
                agent_factory=agent_factory,
                graph_input=graph_input,
                config=config,
                stream_modes=stream_modes,
                stream_subgraphs=body.stream_subgraphs,
                interrupt_before=body.interrupt_before,
                interrupt_after=body.interrupt_after,
            )
        )
        record.task = task

        # Title sync is handled by worker.py's finally block which reads the
        # title from the checkpoint and calls thread_store.update_display_name
        # after the run completes.

        return record
    finally:
        if owner_context_token is not None:
            reset_current_user(owner_context_token)


async def sse_consumer(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
):
    """Async generator that yields SSE frames from the bridge.

    The ``finally`` block implements ``on_disconnect`` semantics:
    - ``cancel``: abort the background task on client disconnect.
    - ``continue``: let the task run; events are discarded.
    """
    last_event_id = request.headers.get("Last-Event-ID")
    try:
        async for entry in bridge.subscribe(record.run_id, last_event_id=last_event_id):
            if await request.is_disconnected():
                break

            if entry is HEARTBEAT_SENTINEL:
                yield ": heartbeat\n\n"
                continue

            if entry is END_SENTINEL:
                yield format_sse("end", None, event_id=entry.id or None)
                return

            yield format_sse(entry.event, entry.data, event_id=entry.id or None)

    finally:
        if record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)


async def wait_for_run_completion(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
) -> bool:
    """Block until the run publishes ``END_SENTINEL``, honouring on_disconnect.

    The non-streaming ``/wait`` endpoints used to ``await record.task``
    directly with no disconnect handling.  When the client (or an
    intermediate HTTP proxy) timed out during a long tool call such as
    ``pip install``, the handler would swallow ``CancelledError`` and
    serialize whatever checkpoint happened to exist — masking a half-finished
    run as a normal completion (issue #3265).

    This helper consumes the same bridge that ``sse_consumer`` does so the
    wait path shares its disconnect semantics: each wake-up polls
    ``request.is_disconnected()``; on a real disconnect it cancels the
    background run when ``record.on_disconnect`` is ``cancel``.  The bridge's
    heartbeat sentinels guarantee at least one wake-up per
    ``heartbeat_interval`` even when the agent emits no events for a while.

    Returns:
        ``True`` when ``END_SENTINEL`` was observed (run reached a terminal
        state), ``False`` when the loop exited because the client
        disconnected.  Callers must skip checkpoint serialization on
        ``False`` so a partial checkpoint is not returned as a normal
        response.
    """
    completed = False
    try:
        async for entry in bridge.subscribe(record.run_id):
            # END_SENTINEL means the run reached a terminal state; honour it
            # even if the client just disconnected so the caller still serializes
            # the real final checkpoint.
            if entry is END_SENTINEL:
                completed = True
                return True
            if await request.is_disconnected():
                break
            # Heartbeats and regular events: keep waiting for END_SENTINEL.
        return completed
    finally:
        if not completed and record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)

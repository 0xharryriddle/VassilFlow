"""Canonical identity and runtime policy types for VassilFlow Agents."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

DEFAULT_ASSISTANT_ID = "lead_agent"
_DEFAULT_ASSISTANT_ALIASES = frozenset({DEFAULT_ASSISTANT_ID, "lead-agent"})
_AGENT_NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")

AgentDataAccess = Literal["thread_uploads", "thread_workspace", "thread_outputs"]
AGENT_DATA_ACCESS_SCOPES: tuple[AgentDataAccess, ...] = (
    "thread_uploads",
    "thread_workspace",
    "thread_outputs",
)
AGENT_POLICY_VERSION = 1
AGENT_POLICY_VERSION_KEY = "agent_policy_version"


@dataclass(frozen=True, slots=True)
class CanonicalAgentIdentity:
    """Server-normalized identity used by routing, storage, and the harness."""

    assistant_id: str
    agent_name: str | None

    @property
    def is_default(self) -> bool:
        return self.agent_name is None


@dataclass(frozen=True, slots=True)
class AgentRuntimePolicy:
    """Effective tool and thread-data boundary for one Agent invocation.

    ``None`` means the default harness behavior is inherited. An empty set is
    an explicit deny-all policy.
    """

    allowed_tool_names: frozenset[str] | None = None
    data_access: frozenset[AgentDataAccess] | None = None
    allow_mcp_tools: bool = False
    allow_acp_agents: bool = False


def is_default_agent_alias(value: object) -> bool:
    """Return whether *value* is reserved for the default Agent identity."""

    return isinstance(value, str) and value.strip().lower() in _DEFAULT_ASSISTANT_ALIASES


def serialize_agent_runtime_policy(
    policy: AgentRuntimePolicy | None,
) -> dict[str, Any]:
    """Serialize a policy for trusted runtime metadata propagation."""

    if policy is None:
        return {}
    return {
        AGENT_POLICY_VERSION_KEY: AGENT_POLICY_VERSION,
        "allowed_tools": (sorted(policy.allowed_tool_names) if policy.allowed_tool_names is not None else None),
        "agent_data_access": (sorted(policy.data_access) if policy.data_access is not None else None),
        "agent_allow_mcp_tools": policy.allow_mcp_tools,
        "agent_allow_acp_agents": policy.allow_acp_agents,
    }


def deserialize_agent_runtime_policy(
    values: Mapping[str, Any] | None,
) -> AgentRuntimePolicy | None:
    """Rehydrate trusted policy metadata, including the pre-versioned shape."""

    if not values:
        return None
    has_policy = AGENT_POLICY_VERSION_KEY in values or any(
        key in values
        for key in (
            "allowed_tools",
            "agent_data_access",
            "agent_allow_mcp_tools",
            "agent_allow_acp_agents",
        )
    )
    if not has_policy:
        return None

    if AGENT_POLICY_VERSION_KEY in values:
        version = values.get(AGENT_POLICY_VERSION_KEY)
        if type(version) is not int or version != AGENT_POLICY_VERSION:
            # Unknown policy shapes must never widen execution. An empty
            # allowlist/data set is the portable fail-closed representation.
            return AgentRuntimePolicy(
                allowed_tool_names=frozenset(),
                data_access=frozenset(),
            )

    allowed_tools = values.get("allowed_tools")
    data_access = values.get("agent_data_access")
    valid_data_scopes = frozenset(AGENT_DATA_ACCESS_SCOPES)
    return AgentRuntimePolicy(
        allowed_tool_names=(None if allowed_tools is None else frozenset(str(name) for name in allowed_tools) if isinstance(allowed_tools, (list, tuple, set, frozenset)) else frozenset()),
        data_access=(None if data_access is None else frozenset(scope for scope in data_access if isinstance(scope, str) and scope in valid_data_scopes) if isinstance(data_access, (list, tuple, set, frozenset)) else frozenset()),
        allow_mcp_tools=values.get("agent_allow_mcp_tools") is True,
        allow_acp_agents=values.get("agent_allow_acp_agents") is True,
    )


def resolve_agent_identity(assistant_id: str | None) -> CanonicalAgentIdentity:
    """Normalize one external assistant id into the canonical Agent identity."""

    if assistant_id is None:
        return CanonicalAgentIdentity(DEFAULT_ASSISTANT_ID, None)
    if not isinstance(assistant_id, str):
        raise ValueError("assistant_id must be a string or null")

    raw = assistant_id.strip().lower()
    if not raw:
        raise ValueError("assistant_id cannot be empty")
    if raw in _DEFAULT_ASSISTANT_ALIASES:
        return CanonicalAgentIdentity(DEFAULT_ASSISTANT_ID, None)

    agent_name = raw.replace("_", "-")
    if not _AGENT_NAME_PATTERN.fullmatch(agent_name):
        raise ValueError(f"Invalid assistant_id {assistant_id!r}: use letters, digits, and hyphens only")
    return CanonicalAgentIdentity(agent_name, agent_name)


def validate_agent_identity_claim(
    identity: CanonicalAgentIdentity,
    claimed_agent_name: object,
    *,
    source: str,
) -> None:
    """Reject a client-side ``agent_name`` that disagrees with assistant_id."""

    if claimed_agent_name is None:
        return
    if not isinstance(claimed_agent_name, str):
        raise ValueError(f"{source}.agent_name must be a string")

    claimed = resolve_agent_identity(claimed_agent_name)
    if claimed.agent_name != identity.agent_name:
        expected = identity.agent_name or DEFAULT_ASSISTANT_ID
        raise ValueError(f"{source}.agent_name conflicts with assistant_id; expected {expected!r}")

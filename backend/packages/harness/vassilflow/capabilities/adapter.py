"""Generic capability adapter contract for specialized built-in Agents."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from langchain.agents.middleware import AgentMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

from vassilflow.persistence.project_repository import ProjectRepository
from vassilflow.reflection import resolve_class

_CAPABILITY_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


@dataclass(frozen=True, slots=True)
class CapabilityResolutionContext:
    """Server-owned identity available while resolving an optimistic input."""

    assistant_id: str
    agent_name: str
    user_id: str


@dataclass(frozen=True, slots=True)
class CapabilityReadinessContext:
    """Server-owned scope available while probing one capability adapter."""

    assistant_id: str
    agent_name: str
    user_id: str | None


class CapabilityReadinessCheck(BaseModel):
    """Sanitized dependency state projected into catalog and health APIs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,95}$")
    status: Literal["ready", "degraded", "unavailable"]
    required: bool
    detail: str = Field(min_length=1, max_length=300)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 8:
            raise ValueError("Readiness metadata cannot exceed eight entries")
        for key, item in value.items():
            if re.fullmatch(r"^[a-z][a-z0-9_.-]{0,63}$", key) is None:
                raise ValueError("Readiness metadata has an invalid key")
            if not isinstance(item, str) or len(item) > 200:
                raise ValueError("Readiness metadata values must be bounded strings")
        return value


class CapabilityInputError(ValueError):
    """Base class for a capability input that cannot become trusted context."""


class CapabilityInputInvalidError(CapabilityInputError):
    """The optimistic envelope or domain payload is invalid."""


class CapabilityInputUnsupportedError(CapabilityInputError):
    """The selected Agent does not own the requested capability."""


class CapabilityInputNotFoundError(CapabilityInputError):
    """A user-scoped resource referenced by the input does not exist."""


class CapabilityInputConflictError(CapabilityInputError):
    """The input references stale or conflicting resource state."""


class CapabilityInputIntegrityError(CapabilityInputError):
    """The referenced canonical resource failed integrity checks."""


class CapabilityInputUnavailableError(CapabilityInputError):
    """The adapter could not read an otherwise valid resource."""


@runtime_checkable
class AgentCapabilityAdapter(Protocol):
    """Domain adapter loaded from a server-owned built-in Agent definition."""

    key: str

    def resolve_input(
        self,
        kind: str,
        payload: Mapping[str, Any],
        *,
        context: CapabilityResolutionContext,
    ) -> Mapping[str, Any]:
        """Validate optimistic input and return trusted runtime payload."""

    def build_middlewares(self) -> Sequence[AgentMiddleware]:
        """Return fresh middleware instances owned by this capability."""

    def check_readiness(
        self,
        *,
        context: CapabilityReadinessContext,
    ) -> Sequence[CapabilityReadinessCheck]:
        """Return bounded, non-mutating dependency readiness checks."""

    def build_project_repositories(
        self,
        *,
        context: CapabilityReadinessContext,
    ) -> Sequence[ProjectRepository]:
        """Return repositories owned by this capability and request scope."""


def load_capability_adapters(
    adapter_paths: tuple[str, ...],
) -> tuple[AgentCapabilityAdapter, ...]:
    """Create and validate fresh adapters declared by one built-in Agent."""

    adapters: list[AgentCapabilityAdapter] = []
    seen_keys: set[str] = set()
    for adapter_path in adapter_paths:
        adapter_class = resolve_class(adapter_path)
        adapter = adapter_class()
        if not isinstance(adapter, AgentCapabilityAdapter):
            raise TypeError(f"Capability adapter {adapter_path!r} does not implement AgentCapabilityAdapter")
        if _CAPABILITY_KEY_RE.fullmatch(adapter.key) is None:
            raise ValueError(f"Capability adapter {adapter_path!r} has an invalid key")
        if adapter.key in seen_keys:
            raise ValueError(f"Built-in Agent capability key {adapter.key!r} is duplicated")
        seen_keys.add(adapter.key)
        adapters.append(adapter)
    return tuple(adapters)


def capability_middlewares(
    adapter_paths: tuple[str, ...],
) -> list[AgentMiddleware]:
    """Build middleware contributions from declared capability adapters."""

    return [middleware for adapter in load_capability_adapters(adapter_paths) for middleware in adapter.build_middlewares()]


def capability_readiness(
    adapter_paths: tuple[str, ...],
    *,
    context: CapabilityReadinessContext,
) -> tuple[CapabilityReadinessCheck, ...]:
    """Run adapter readiness checks and enforce adapter-owned check keys."""

    checks: list[CapabilityReadinessCheck] = []
    seen_keys: set[str] = set()
    for adapter in load_capability_adapters(adapter_paths):
        for check in adapter.check_readiness(context=context):
            if not check.key.startswith(f"{adapter.key}."):
                raise ValueError(f"Capability readiness key {check.key!r} is not owned by adapter {adapter.key!r}")
            if check.key in seen_keys:
                raise ValueError(f"Capability readiness key {check.key!r} is duplicated")
            seen_keys.add(check.key)
            checks.append(check)
    return tuple(checks)


def capability_project_repositories(
    adapter_paths: tuple[str, ...],
    *,
    context: CapabilityReadinessContext,
) -> tuple[ProjectRepository, ...]:
    """Collect project repositories contributed by capability adapters."""

    return tuple(repository for adapter in load_capability_adapters(adapter_paths) for repository in adapter.build_project_repositories(context=context))

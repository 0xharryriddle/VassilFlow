"""Product-facing metadata for agents exposed by the gateway."""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from vassilflow.capabilities import CapabilityReadinessCheck
from vassilflow.config.agent_contract import (
    AGENT_DATA_ACCESS_SCOPES,
    AgentDataAccess,
)
from vassilflow.config.app_config import AppConfig
from vassilflow.config.builtin_agents import (
    AgentCategory,
    BuiltinAgentDefinition,
    evaluate_builtin_agent,
)


class AgentLaunchMetadata(BaseModel):
    """Describe how the frontend starts work with an agent."""

    kind: Literal["chat", "project"]
    path: str = Field(..., pattern=r"^/workspace/")
    project_kind: str | None = None


class AgentManagementMetadata(BaseModel):
    """Actions the current user may perform on an agent definition."""

    can_edit: bool
    can_delete: bool


class AgentReadinessMetadata(BaseModel):
    """One sanitized runtime dependency check for an Agent."""

    key: str
    status: Literal["ready", "degraded", "unavailable"]
    required: bool
    detail: str
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentProductMetadata(BaseModel):
    """Catalog metadata kept separate from the harness runtime config."""

    id: str
    display_name: str
    origin: Literal["builtin", "personal", "team"]
    category: AgentCategory
    icon: str
    status: Literal["available", "degraded", "unavailable"]
    required_tools: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    degraded_requirements: list[str] = Field(default_factory=list)
    readiness: list[AgentReadinessMetadata] = Field(default_factory=list)
    data_access: list[AgentDataAccess] = Field(default_factory=list)
    starter_prompts: list[str] = Field(default_factory=list)
    chat_extension: str | None = None
    launch: AgentLaunchMetadata
    management: AgentManagementMetadata


def build_custom_agent_product(
    name: str,
    *,
    management_enabled: bool = True,
) -> AgentProductMetadata:
    """Build catalog metadata for a per-user custom chat agent."""

    return AgentProductMetadata(
        id=f"personal:{name}",
        display_name=name,
        origin="personal",
        category="custom",
        icon="bot",
        status="available",
        data_access=list(AGENT_DATA_ACCESS_SCOPES),
        chat_extension=None,
        launch=AgentLaunchMetadata(
            kind="chat",
            path=f"/workspace/agents/{name}/chats/new",
        ),
        management=AgentManagementMetadata(
            can_edit=management_enabled,
            can_delete=management_enabled,
        ),
    )


def build_builtin_agent_product(
    definition: BuiltinAgentDefinition,
    app_config: AppConfig,
    *,
    readiness: Sequence[CapabilityReadinessCheck] = (),
) -> AgentProductMetadata:
    """Build catalog metadata from verified runtime capability evidence."""

    availability = evaluate_builtin_agent(definition, app_config)
    unavailable_checks = [check for check in readiness if check.required and check.status == "unavailable"]
    degraded_checks = [check for check in readiness if check.status != "ready" and not (check.required and check.status == "unavailable")]
    if not availability.available or unavailable_checks:
        status = "unavailable"
    elif degraded_checks:
        status = "degraded"
    else:
        status = "available"
    return AgentProductMetadata(
        id=f"builtin:{definition.name}",
        display_name=definition.display_name,
        origin="builtin",
        category=definition.category,
        icon=definition.icon,
        status=status,
        required_tools=list(definition.required_tools),
        missing_requirements=[
            *availability.missing_tools,
            *(check.key for check in unavailable_checks),
        ],
        degraded_requirements=[check.key for check in degraded_checks],
        readiness=[
            AgentReadinessMetadata(
                key=check.key,
                status=check.status,
                required=check.required,
                detail=check.detail,
                metadata=check.metadata,
            )
            for check in readiness
        ],
        data_access=list(definition.data_access),
        starter_prompts=list(definition.starter_prompts),
        chat_extension=definition.chat_extension,
        launch=AgentLaunchMetadata(
            kind=definition.launch_kind,
            path=definition.launch_path,
            project_kind=definition.project_kind,
        ),
        management=AgentManagementMetadata(
            can_edit=False,
            can_delete=False,
        ),
    )

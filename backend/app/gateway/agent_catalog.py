"""Product-facing metadata for agents exposed by the gateway."""

from typing import Literal

from pydantic import BaseModel, Field

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


class AgentProductMetadata(BaseModel):
    """Catalog metadata kept separate from the harness runtime config."""

    id: str
    display_name: str
    origin: Literal["builtin", "personal", "team"]
    category: AgentCategory
    icon: str
    status: Literal["available", "unavailable"]
    required_tools: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    data_access: list[AgentDataAccess] = Field(default_factory=list)
    starter_prompts: list[str] = Field(default_factory=list)
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
) -> AgentProductMetadata:
    """Build catalog metadata from verified runtime capability evidence."""

    availability = evaluate_builtin_agent(definition, app_config)
    return AgentProductMetadata(
        id=f"builtin:{definition.name}",
        display_name=definition.display_name,
        origin="builtin",
        category=definition.category,
        icon=definition.icon,
        status="available" if availability.available else "unavailable",
        required_tools=list(definition.required_tools),
        missing_requirements=list(availability.missing_tools),
        data_access=list(definition.data_access),
        starter_prompts=list(definition.starter_prompts),
        launch=AgentLaunchMetadata(
            kind="chat",
            path=f"/workspace/agents/{definition.name}/chats/new",
        ),
        management=AgentManagementMetadata(
            can_edit=False,
            can_delete=False,
        ),
    )

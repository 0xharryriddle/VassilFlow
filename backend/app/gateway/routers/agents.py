"""Catalog and management API for built-in and custom Agents."""

import asyncio
import logging
import shutil

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.gateway.agent_catalog import (
    AgentProductMetadata,
    build_builtin_agent_product,
    build_custom_agent_product,
)
from app.gateway.capability_readiness import (
    get_agent_capability_readiness,
)
from app.gateway.deps import get_config
from vassilflow.config.agent_contract import (
    is_default_agent_alias,
    resolve_agent_identity,
)
from vassilflow.config.agents_api_config import get_agents_api_config
from vassilflow.config.agents_config import AgentConfig, list_custom_agents, load_agent_config, load_agent_soul
from vassilflow.config.app_config import AppConfig
from vassilflow.config.builtin_agents import (
    BuiltinAgentDefinition,
    get_builtin_agent,
    is_builtin_agent,
    list_builtin_agents,
)
from vassilflow.config.paths import get_paths
from vassilflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["agents"])


class AgentResponse(BaseModel):
    """Response model for one catalog Agent."""

    name: str = Field(..., description="Agent name (hyphen-case)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Optional skill whitelist (None=all, []=none)")
    soul: str | None = Field(default=None, description="SOUL.md content")
    product: AgentProductMetadata = Field(..., description="Product catalog and launch metadata")


class AgentsListResponse(BaseModel):
    """Response model for listing catalog Agents."""

    agents: list[AgentResponse]


class AgentCatalogResponse(BaseModel):
    """Read-safe product catalog separated from prompt management."""

    agents: list[AgentResponse]
    custom_agent_management_enabled: bool


class AgentCreateRequest(BaseModel):
    """Request body for creating a custom agent."""

    name: str = Field(..., description="Agent name (stored in canonical lowercase hyphen-case)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Optional skill whitelist (None=all enabled, []=none)")
    soul: str = Field(default="", description="SOUL.md content — agent personality and behavioral guardrails")


class AgentUpdateRequest(BaseModel):
    """Request body for updating a custom agent."""

    description: str | None = Field(default=None, description="Updated description")
    model: str | None = Field(default=None, description="Updated model override")
    tool_groups: list[str] | None = Field(default=None, description="Updated tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Updated skill whitelist (None=all, []=none)")
    soul: str | None = Field(default=None, description="Updated SOUL.md content")


def _normalize_agent_name(name: str) -> str:
    """Resolve one external name through the canonical Agent contract."""

    try:
        return resolve_agent_identity(name).assistant_id
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _is_reserved_agent_name(name: str) -> bool:
    """Keep default and built-in runtime identities out of personal storage."""

    return is_default_agent_alias(name) or is_builtin_agent(name)


def _require_agents_api_enabled() -> None:
    """Reject access unless the custom-agent management API is explicitly enabled."""
    if not get_agents_api_config().enabled:
        raise HTTPException(
            status_code=403,
            detail=("Custom-agent management API is disabled. Set agents_api.enabled=true to expose agent and user-profile routes over HTTP."),
        )


def _agent_config_to_response(
    agent_cfg: AgentConfig,
    include_soul: bool = False,
    *,
    user_id: str | None = None,
    management_enabled: bool = True,
) -> AgentResponse:
    """Convert AgentConfig to AgentResponse."""
    soul: str | None = None
    if include_soul:
        soul = load_agent_soul(agent_cfg.name, user_id=user_id) or ""

    return AgentResponse(
        name=agent_cfg.name,
        description=agent_cfg.description,
        model=agent_cfg.model,
        tool_groups=agent_cfg.tool_groups,
        skills=agent_cfg.skills,
        soul=soul,
        product=build_custom_agent_product(
            agent_cfg.name,
            management_enabled=management_enabled,
        ),
    )


async def _builtin_agent_to_response(
    definition: BuiltinAgentDefinition,
    app_config: AppConfig,
    *,
    user_id: str | None,
    include_soul: bool = True,
) -> AgentResponse:
    runtime_config = definition.to_runtime_config()
    readiness = await get_agent_capability_readiness(
        definition.capability_adapters,
        assistant_id=definition.name,
        agent_name=definition.name,
        user_id=user_id,
    )
    return AgentResponse(
        name=definition.name,
        description=definition.description,
        model=runtime_config.model,
        tool_groups=runtime_config.tool_groups,
        skills=runtime_config.skills,
        soul=definition.soul if include_soul else None,
        product=build_builtin_agent_product(
            definition,
            app_config,
            readiness=readiness,
        ),
    )


@router.get(
    "/agent-catalog",
    response_model=AgentCatalogResponse,
    summary="List Agent Catalog",
    description="List read-safe built-in and personal Agent metadata without exposing prompt content.",
)
async def list_agent_catalog(
    config: AppConfig = Depends(get_config),
) -> AgentCatalogResponse:
    """List discoverable Agents without exposing persisted prompt content."""

    management_enabled = get_agents_api_config().enabled
    user_id = get_effective_user_id()
    try:
        builtins = list(
            await asyncio.gather(
                *(
                    _builtin_agent_to_response(
                        definition,
                        config,
                        user_id=user_id,
                        include_soul=False,
                    )
                    for definition in list_builtin_agents()
                )
            )
        )
        custom_agents = [agent for agent in list_custom_agents(user_id=user_id) if not _is_reserved_agent_name(agent.name)]
        custom = [
            _agent_config_to_response(
                agent,
                include_soul=False,
                user_id=user_id,
                management_enabled=management_enabled,
            )
            for agent in custom_agents
        ]
        return AgentCatalogResponse(
            agents=[*builtins, *custom],
            custom_agent_management_enabled=management_enabled,
        )
    except Exception as e:
        logger.error(f"Failed to list Agent catalog: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list Agent catalog: {str(e)}",
        )


@router.get(
    "/agents",
    response_model=AgentsListResponse,
    summary="List Agents",
    description="List curated built-in Agents and the current user's custom Agents.",
)
async def list_agents(config: AppConfig = Depends(get_config)) -> AgentsListResponse:
    """List all catalog Agents.

    Returns:
        Curated built-in Agents followed by the current user's custom Agents.
    """
    _require_agents_api_enabled()

    user_id = get_effective_user_id()
    try:
        builtins = list(
            await asyncio.gather(
                *(
                    _builtin_agent_to_response(
                        definition,
                        config,
                        user_id=user_id,
                    )
                    for definition in list_builtin_agents()
                )
            )
        )
        custom_agents = [agent for agent in list_custom_agents(user_id=user_id) if not _is_reserved_agent_name(agent.name)]
        custom = [_agent_config_to_response(agent, include_soul=True, user_id=user_id) for agent in custom_agents]
        return AgentsListResponse(agents=[*builtins, *custom])
    except Exception as e:
        logger.error(f"Failed to list agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list agents: {str(e)}")


@router.get(
    "/agents/check",
    summary="Check Agent Name",
    description="Validate an agent name and check if it is available (case-insensitive).",
)
async def check_agent_name(name: str) -> dict:
    """Check whether an agent name is valid and not yet taken.

    Args:
        name: The agent name to check.

    Returns:
        ``{"available": true/false, "name": "<normalized>"}``

    Raises:
        HTTPException: 422 if the name is invalid.
    """
    _require_agents_api_enabled()
    normalized = _normalize_agent_name(name)
    if _is_reserved_agent_name(normalized):
        return {"available": False, "name": normalized}
    user_id = get_effective_user_id()
    paths = get_paths()
    # Treat the name as taken if either the per-user path or the legacy shared
    # path holds an agent — picking a name that collides with an unmigrated
    # legacy agent would shadow the legacy entry once migration runs.
    available = not paths.user_agent_dir(user_id, normalized).exists() and not paths.agent_dir(normalized).exists()
    return {"available": available, "name": normalized}


@router.get(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="Get Agent",
    description="Retrieve runtime and product details for a specific catalog Agent.",
)
async def get_agent(
    name: str,
    config: AppConfig = Depends(get_config),
) -> AgentResponse:
    """Get a specific built-in or custom Agent by name.

    Args:
        name: The agent name.

    Returns:
        Agent details including SOUL.md content.

    Raises:
        HTTPException: 404 if agent not found.
    """
    name = _normalize_agent_name(name)
    builtin = get_builtin_agent(name)
    if builtin is not None:
        return await _builtin_agent_to_response(
            builtin,
            config,
            user_id=get_effective_user_id(),
        )

    if is_default_agent_alias(name):
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    _require_agents_api_enabled()
    user_id = get_effective_user_id()

    try:
        agent_cfg = load_agent_config(name, user_id=user_id)
        return _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        logger.error(f"Failed to get agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get agent: {str(e)}")


@router.post(
    "/agents",
    response_model=AgentResponse,
    status_code=201,
    summary="Create Custom Agent",
    description="Create a new custom agent with its config and SOUL.md.",
)
async def create_agent_endpoint(request: AgentCreateRequest) -> AgentResponse:
    """Create a new custom agent.

    Args:
        request: The agent creation request.

    Returns:
        The created agent details.

    Raises:
        HTTPException: 409 if agent already exists, 422 if name is invalid.
    """
    _require_agents_api_enabled()
    normalized_name = _normalize_agent_name(request.name)
    if _is_reserved_agent_name(normalized_name):
        raise HTTPException(
            status_code=409,
            detail=f"Agent name '{normalized_name}' is reserved by the runtime",
        )
    user_id = get_effective_user_id()
    paths = get_paths()

    def _create_agent() -> AgentResponse | None:
        # Worker thread: base-dir resolution, existence checks, directory/file
        # creation, read-back, and failure cleanup are all blocking filesystem
        # IO that must stay off the event loop.
        agent_dir = paths.user_agent_dir(user_id, normalized_name)
        legacy_dir = paths.agent_dir(normalized_name)

        if legacy_dir.exists():
            return None  # signals 409 to the caller

        try:
            try:
                agent_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                return None  # signals 409 to the caller
            # Write config.yaml
            config_data: dict = {"name": normalized_name}
            if request.description:
                config_data["description"] = request.description
            if request.model is not None:
                config_data["model"] = request.model
            if request.tool_groups is not None:
                config_data["tool_groups"] = request.tool_groups
            if request.skills is not None:
                config_data["skills"] = request.skills

            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

            # Write SOUL.md
            soul_file = agent_dir / "SOUL.md"
            soul_file.write_text(request.soul, encoding="utf-8")

            logger.info(f"Created agent '{normalized_name}' at {agent_dir}")

            agent_cfg = load_agent_config(normalized_name, user_id=user_id)
            return _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id)
        except Exception:
            # Clean up partial state on failure before surfacing the error.
            if agent_dir.exists():
                shutil.rmtree(agent_dir)
            raise

    try:
        response = await asyncio.to_thread(_create_agent)
    except Exception as e:
        logger.error(f"Failed to create agent '{request.name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")

    if response is None:
        raise HTTPException(status_code=409, detail=f"Agent '{normalized_name}' already exists")

    return response


@router.put(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="Update Custom Agent",
    description="Update an existing custom agent's config and/or SOUL.md.",
)
async def update_agent(name: str, request: AgentUpdateRequest) -> AgentResponse:
    """Update an existing custom agent.

    Args:
        name: The agent name.
        request: The update request (all fields optional).

    Returns:
        The updated agent details.

    Raises:
        HTTPException: 404 if agent not found.
    """
    _require_agents_api_enabled()
    name = _normalize_agent_name(name)
    if _is_reserved_agent_name(name):
        raise HTTPException(
            status_code=403,
            detail=f"Reserved Agent '{name}' cannot be modified",
        )
    user_id = get_effective_user_id()

    try:
        agent_cfg = load_agent_config(name, user_id=user_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    paths = get_paths()
    agent_dir = paths.user_agent_dir(user_id, name)
    if not agent_dir.exists() and paths.agent_dir(name).exists():
        raise HTTPException(
            status_code=409,
            detail=(f"Agent '{name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before updating."),
        )

    try:
        # Update config if any config fields changed
        # Use model_fields_set to distinguish "field omitted" from "explicitly set to null".
        # This is critical for skills where None means "inherit all" (not "don't change").
        fields_set = request.model_fields_set
        config_changed = bool(fields_set & {"description", "model", "tool_groups", "skills"})

        if config_changed:
            updated: dict = {
                "name": agent_cfg.name,
                "description": request.description if "description" in fields_set else agent_cfg.description,
            }
            new_model = request.model if "model" in fields_set else agent_cfg.model
            if new_model is not None:
                updated["model"] = new_model

            new_tool_groups = request.tool_groups if "tool_groups" in fields_set else agent_cfg.tool_groups
            if new_tool_groups is not None:
                updated["tool_groups"] = new_tool_groups

            # skills: None = inherit all, [] = no skills, ["a","b"] = whitelist
            if "skills" in fields_set:
                new_skills = request.skills
            else:
                new_skills = agent_cfg.skills
            if new_skills is not None:
                updated["skills"] = new_skills

            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(updated, f, default_flow_style=False, allow_unicode=True)

        # Update SOUL.md if provided
        if request.soul is not None:
            soul_path = agent_dir / "SOUL.md"
            soul_path.write_text(request.soul, encoding="utf-8")

        logger.info(f"Updated agent '{name}'")

        refreshed_cfg = load_agent_config(name, user_id=user_id)
        return _agent_config_to_response(refreshed_cfg, include_soul=True, user_id=user_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")


class UserProfileResponse(BaseModel):
    """Response model for the global user profile (USER.md)."""

    content: str | None = Field(default=None, description="USER.md content, or null if not yet created")


class UserProfileUpdateRequest(BaseModel):
    """Request body for setting the global user profile."""

    content: str = Field(default="", description="USER.md content — describes the user's background and preferences")


@router.get(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="Get User Profile",
    description="Read the global USER.md file that is injected into all custom agents.",
)
async def get_user_profile() -> UserProfileResponse:
    """Return the current USER.md content.

    Returns:
        UserProfileResponse with content=None if USER.md does not exist yet.
    """
    _require_agents_api_enabled()

    try:
        user_md_path = get_paths().user_md_file
        if not user_md_path.exists():
            return UserProfileResponse(content=None)
        raw = user_md_path.read_text(encoding="utf-8").strip()
        return UserProfileResponse(content=raw or None)
    except Exception as e:
        logger.error(f"Failed to read user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read user profile: {str(e)}")


@router.put(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="Update User Profile",
    description="Write the global USER.md file that is injected into all custom agents.",
)
async def update_user_profile(request: UserProfileUpdateRequest) -> UserProfileResponse:
    """Create or overwrite the global USER.md.

    Args:
        request: The update request with the new USER.md content.

    Returns:
        UserProfileResponse with the saved content.
    """
    _require_agents_api_enabled()

    try:
        paths = get_paths()
        paths.base_dir.mkdir(parents=True, exist_ok=True)
        paths.user_md_file.write_text(request.content, encoding="utf-8")
        logger.info(f"Updated USER.md at {paths.user_md_file}")
        return UserProfileResponse(content=request.content or None)
    except Exception as e:
        logger.error(f"Failed to update user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update user profile: {str(e)}")


@router.delete(
    "/agents/{name}",
    status_code=204,
    summary="Delete Custom Agent",
    description="Delete a custom agent and all its files (config, SOUL.md, memory).",
)
async def delete_agent(name: str) -> None:
    """Delete a custom agent.

    Args:
        name: The agent name.

    Raises:
        HTTPException: 404 if no per-user copy exists; 409 if only a legacy
            shared copy exists (suggesting the migration script).
    """
    _require_agents_api_enabled()
    name = _normalize_agent_name(name)
    if _is_reserved_agent_name(name):
        raise HTTPException(
            status_code=403,
            detail=f"Reserved Agent '{name}' cannot be deleted",
        )
    user_id = get_effective_user_id()
    paths = get_paths()

    def _remove_agent_dir() -> tuple[str, str]:
        # Runs in a worker thread: resolving the base dir, probing the directory
        # (`exists`), and removing it (`rmtree`) are all blocking filesystem IO
        # that must stay off the event loop.
        agent_dir = paths.user_agent_dir(user_id, name)
        if not agent_dir.exists():
            outcome = "legacy" if paths.agent_dir(name).exists() else "missing"
            return outcome, str(agent_dir)
        shutil.rmtree(agent_dir)
        return "deleted", str(agent_dir)

    try:
        outcome, agent_dir = await asyncio.to_thread(_remove_agent_dir)
    except Exception as e:
        logger.error(f"Failed to delete agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")

    if outcome == "legacy":
        raise HTTPException(
            status_code=409,
            detail=(f"Agent '{name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before deleting."),
        )
    if outcome == "missing":
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    logger.info(f"Deleted agent '{name}' from {agent_dir}")

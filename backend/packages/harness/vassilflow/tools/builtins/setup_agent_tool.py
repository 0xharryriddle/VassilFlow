import logging

import yaml
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

from vassilflow.config.agent_contract import resolve_agent_identity
from vassilflow.config.builtin_agents import is_builtin_agent
from vassilflow.config.paths import get_paths
from vassilflow.runtime.user_context import resolve_runtime_user_id
from vassilflow.tools.types import Runtime

logger = logging.getLogger(__name__)


@tool(parse_docstring=True)
def setup_agent(
    soul: str,
    description: str,
    runtime: Runtime,
    skills: list[str] | None = None,
) -> Command:
    """Setup the custom VassilFlow agent.

    Args:
        soul: Full SOUL.md content defining the agent's personality and behavior.
        description: One-line description of what the agent does.
        skills: Optional list of skill ids (`category:name`) or unambiguous names this agent should use. None means use all enabled skills, empty list means no skills.
    """

    # Reject empty / whitespace-only soul before touching the filesystem.
    # Without this guard the tool would happily persist an empty SOUL.md and
    # still report success, which caused the frontend to enter the "agent
    # created" state for an unusable agent (issue #3549). Failing loud lets
    # the model retry instead of silently producing a broken artifact and,
    # It also prevents a bootstrap request from creating an unusable Agent.
    if not soul or not soul.strip():
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Error: soul content is empty; refusing to create agent with an empty SOUL.md",
                        tool_call_id=runtime.tool_call_id,
                    )
                ]
            }
        )

    raw_agent_name = runtime.context.get("bootstrap_agent_name") if runtime.context else None
    agent_name: str | None = None
    agent_dir = None
    is_new_dir = False

    try:
        try:
            identity = resolve_agent_identity(raw_agent_name)
        except ValueError as exc:
            raise ValueError(f"Invalid agent name: {exc}") from exc
        if identity.is_default or is_builtin_agent(identity.agent_name):
            raise ValueError("bootstrap_agent_name must identify a new personal Agent")
        agent_name = identity.agent_name
        paths = get_paths()
        # Custom agents are persisted under the current user's bucket so
        # different users do not see each other's agents.
        user_id = resolve_runtime_user_id(runtime)
        agent_dir = paths.user_agent_dir(user_id, agent_name)
        is_new_dir = not agent_dir.exists()
        agent_dir.mkdir(parents=True, exist_ok=True)

        config_data: dict = {"name": agent_name}
        if description:
            config_data["description"] = description
        if skills is not None:
            config_data["skills"] = skills

        config_file = agent_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

        soul_file = agent_dir / "SOUL.md"
        soul_file.write_text(soul, encoding="utf-8")

        logger.info(f"[agent_creator] Created agent '{agent_name}' at {agent_dir}")
        return Command(
            update={
                "created_agent_name": agent_name,
                "messages": [ToolMessage(content=f"Agent '{agent_name}' created successfully!", tool_call_id=runtime.tool_call_id)],
            }
        )

    except Exception as e:
        import shutil

        if agent_name and is_new_dir and agent_dir is not None and agent_dir.exists():
            # Cleanup the custom agent directory only if it was newly created during this call
            shutil.rmtree(agent_dir)
        logger.error(f"[agent_creator] Failed to create agent '{agent_name}': {e}", exc_info=True)
        return Command(update={"messages": [ToolMessage(content=f"Error: {e}", tool_call_id=runtime.tool_call_id)]})

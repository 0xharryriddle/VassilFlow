"""Discovery of operational repositories without domain imports in Gateway code."""

from __future__ import annotations

from vassilflow.actions import ActionJournalRepository
from vassilflow.capabilities import (
    CapabilityReadinessContext,
    capability_project_repositories,
)
from vassilflow.config.builtin_agents import list_builtin_agents
from vassilflow.config.paths import get_paths
from vassilflow.persistence.project_repository import (
    ProjectRepositoryRegistry,
)
from vassilflow.runtime.lifecycle_repository import (
    ThreadLifecycleJournalRepository,
)


def build_domain_repository_registry(
    *,
    user_id: str | None,
) -> ProjectRepositoryRegistry:
    """Discover core and capability-owned repositories for one scope."""

    repositories = [
        ActionJournalRepository(
            get_paths().base_dir,
            user_id=user_id,
        ),
        ThreadLifecycleJournalRepository(
            get_paths().base_dir,
            user_id=user_id,
        ),
    ]
    seen_adapter_paths: set[str] = set()
    for definition in list_builtin_agents():
        adapter_paths = tuple(adapter_path for adapter_path in definition.capability_adapters if adapter_path not in seen_adapter_paths)
        seen_adapter_paths.update(adapter_paths)
        if not adapter_paths:
            continue
        repositories.extend(
            capability_project_repositories(
                adapter_paths,
                context=CapabilityReadinessContext(
                    assistant_id=definition.name,
                    agent_name=definition.name,
                    user_id=user_id,
                ),
            )
        )
    return ProjectRepositoryRegistry(repositories)


__all__ = ["build_domain_repository_registry"]

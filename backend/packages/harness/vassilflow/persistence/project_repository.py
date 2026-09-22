"""Operational contract for domain-owned repositories.

The contract is intentionally narrower than domain CRUD. It gives the runtime
and operators one stable surface for readiness, schema inventory, and explicit
migrations while each domain continues to own its storage model. Project
repositories are the primary consumer; append-only domain journals can use the
same schema operations without pretending to expose project CRUD.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import islice
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

RepositoryReadinessStatus = Literal["ready", "degraded", "unavailable"]
RepositoryInventoryStatus = Literal[
    "current",
    "migration_required",
    "blocked",
]
RepositoryStorageKind = Literal["filesystem", "database", "object_store"]
RepositoryDeploymentMode = Literal[
    "process_local",
    "single_writer",
    "multi_writer",
]
RepositoryMigrationSafety = Literal[
    "maintenance_window",
    "transactional",
]
RepositoryScope = Literal["user", "workspace", "global"]

_MAX_REPOSITORIES = 64
_MAX_MIGRATION_PLANS = 256


class ProjectRepositorySchema(BaseModel):
    """One top-level persisted record kind owned by a repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    current_schema: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^vassilflow\.[a-z0-9_.-]+\.v[1-9][0-9]*$",
    )


class ProjectRepositoryDescriptor(BaseModel):
    """Code-owned deployment and schema identity for one repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    display_name: str = Field(min_length=1, max_length=100)
    storage_kind: RepositoryStorageKind
    deployment_mode: RepositoryDeploymentMode
    migration_safety: RepositoryMigrationSafety
    scope: RepositoryScope
    schemas: tuple[ProjectRepositorySchema, ...] = Field(
        min_length=1,
        max_length=64,
    )

    @model_validator(mode="after")
    def _validate_schema_kinds(self) -> ProjectRepositoryDescriptor:
        kinds = [schema.record_kind for schema in self.schemas]
        if len(kinds) != len(set(kinds)):
            raise ValueError("Repository schema record kinds must be unique")
        schema_ids = [schema.current_schema for schema in self.schemas]
        if len(schema_ids) != len(set(schema_ids)):
            raise ValueError("Repository current schema identities must be unique")
        if self.deployment_mode == "multi_writer" and self.migration_safety != "transactional":
            raise ValueError("Multi-writer repositories must provide transactional migrations")
        return self


class ProjectRepositoryReadiness(BaseModel):
    """Sanitized repository readiness suitable for public health projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    status: RepositoryReadinessStatus
    detail: str = Field(min_length=1, max_length=300)


class ProjectRepositorySchemaCount(BaseModel):
    """Observed count for one record-kind/schema pair."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    record_kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    schema_id: str = Field(
        alias="schema",
        min_length=1,
        max_length=160,
    )
    count: int = Field(ge=1)


class ProjectRepositoryIssue(BaseModel):
    """Aggregated, path-free issue discovered during inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    detail: str = Field(min_length=1, max_length=300)
    count: int = Field(default=1, ge=1)
    record_kind: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.-]{0,63}$",
    )


class ProjectRepositoryInventory(BaseModel):
    """Bounded schema inventory for one repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    status: RepositoryInventoryStatus
    record_count: int = Field(ge=0)
    schema_counts: tuple[ProjectRepositorySchemaCount, ...] = Field(default_factory=tuple)
    issues: tuple[ProjectRepositoryIssue, ...] = Field(default_factory=tuple)


class ProjectRepositoryMigrationPlan(BaseModel):
    """One explicit migration offered by a domain repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    migration_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,95}$")
    summary: str = Field(min_length=1, max_length=300)
    record_kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    source_schemas: tuple[str, ...] = Field(min_length=1, max_length=32)
    target_schemas: tuple[str, ...] = Field(min_length=1, max_length=32)
    affected_records: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_schema_sets(self) -> ProjectRepositoryMigrationPlan:
        if len(self.source_schemas) != len(set(self.source_schemas)):
            raise ValueError("Migration source schemas must be unique")
        if len(self.target_schemas) != len(set(self.target_schemas)):
            raise ValueError("Migration target schemas must be unique")
        if set(self.source_schemas) & set(self.target_schemas):
            raise ValueError("Migration source and target schemas must be distinct")
        return self


class ProjectRepositoryMigrationResult(BaseModel):
    """Validated result returned after one migration is applied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    migration_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,95}$")
    migrated_records: int = Field(ge=0)


class ProjectRepositoryError(RuntimeError):
    """Base error for repository registration or migration orchestration."""


def _bounded_tuple[T](
    values: Iterable[T],
    *,
    limit: int,
    label: str,
) -> tuple[T, ...]:
    resolved = tuple(islice(values, limit + 1))
    if len(resolved) > limit:
        raise ProjectRepositoryError(f"{label} exceeds the operational limit")
    return resolved


@runtime_checkable
class ProjectRepository(Protocol):
    """Operational interface implemented by domain repositories."""

    @property
    def descriptor(self) -> ProjectRepositoryDescriptor:
        """Return immutable storage and schema metadata."""

    def check_readiness(self) -> ProjectRepositoryReadiness:
        """Perform a bounded, non-mutating repository readiness check."""

    def inventory(self) -> ProjectRepositoryInventory:
        """Inspect persisted schema versions without changing repository data."""

    def plan_migrations(
        self,
        inventory: ProjectRepositoryInventory,
    ) -> Sequence[ProjectRepositoryMigrationPlan]:
        """Return migrations that can handle the supplied inventory."""

    def apply_migration(
        self,
        migration_id: str,
    ) -> ProjectRepositoryMigrationResult:
        """Apply one known migration by exact ID."""


class ProjectRepositoryRegistry:
    """Validate and orchestrate a bounded set of domain repositories."""

    def __init__(self, repositories: Iterable[ProjectRepository]) -> None:
        resolved = _bounded_tuple(
            repositories,
            limit=_MAX_REPOSITORIES,
            label="Repository registry",
        )
        seen: set[str] = set()
        for repository in resolved:
            if not isinstance(repository, ProjectRepository):
                raise ProjectRepositoryError("A project repository does not implement the operational repository contract")
            key = repository.descriptor.key
            if key in seen:
                raise ProjectRepositoryError(f"Project repository key {key!r} is duplicated")
            seen.add(key)
        self._repositories = resolved
        self._by_key = {repository.descriptor.key: repository for repository in resolved}

    @property
    def repositories(self) -> tuple[ProjectRepository, ...]:
        return self._repositories

    def readiness(self) -> tuple[ProjectRepositoryReadiness, ...]:
        checks: list[ProjectRepositoryReadiness] = []
        for repository in self._repositories:
            check = repository.check_readiness()
            if check.repository_key != repository.descriptor.key:
                raise ProjectRepositoryError("Repository readiness identity does not match its descriptor")
            checks.append(check)
        return tuple(checks)

    @staticmethod
    def _validate_inventory(
        repository: ProjectRepository,
        inventory: ProjectRepositoryInventory,
    ) -> dict[tuple[str, str], int]:
        descriptor = repository.descriptor
        if inventory.repository_key != descriptor.key:
            raise ProjectRepositoryError("Repository inventory identity does not match its descriptor")

        current_by_kind = {schema.record_kind: schema.current_schema for schema in descriptor.schemas}
        observed: dict[tuple[str, str], int] = {}
        for count in inventory.schema_counts:
            if count.record_kind not in current_by_kind:
                raise ProjectRepositoryError(f"Repository {descriptor.key!r} inventory contains an undeclared record kind")
            identity = (count.record_kind, count.schema_id)
            if identity in observed:
                raise ProjectRepositoryError(f"Repository {descriptor.key!r} inventory contains duplicate schema counts")
            observed[identity] = count.count

        counted_records = sum(observed.values())
        if counted_records > inventory.record_count:
            raise ProjectRepositoryError(f"Repository {descriptor.key!r} inventory count is inconsistent")
        outdated = {identity for identity in observed if identity[1] != current_by_kind[identity[0]]}
        has_issues = bool(inventory.issues)
        if inventory.status == "current":
            if has_issues or outdated or counted_records != inventory.record_count:
                raise ProjectRepositoryError(f"Repository {descriptor.key!r} has an invalid current inventory")
        elif inventory.status == "migration_required":
            if has_issues or not outdated or counted_records != inventory.record_count:
                raise ProjectRepositoryError(f"Repository {descriptor.key!r} has an invalid migration inventory")
        elif not has_issues:
            raise ProjectRepositoryError(f"Repository {descriptor.key!r} is blocked without an issue")
        return observed

    def inventory(self) -> tuple[ProjectRepositoryInventory, ...]:
        inventories: list[ProjectRepositoryInventory] = []
        for repository in self._repositories:
            result = repository.inventory()
            self._validate_inventory(repository, result)
            inventories.append(result)
        return tuple(inventories)

    def migration_plan(
        self,
        inventories: Sequence[ProjectRepositoryInventory] | None = None,
    ) -> tuple[ProjectRepositoryMigrationPlan, ...]:
        inventory_results = (
            self.inventory()
            if inventories is None
            else _bounded_tuple(
                inventories,
                limit=_MAX_REPOSITORIES,
                label="Migration inventory",
            )
        )
        inventory_keys = [inventory.repository_key for inventory in inventory_results]
        if len(inventory_keys) != len(set(inventory_keys)):
            raise ProjectRepositoryError("Migration inventory contains duplicate repository identities")
        by_key = {inventory.repository_key: inventory for inventory in inventory_results}
        if set(by_key) != set(self._by_key):
            raise ProjectRepositoryError("Migration inventory does not match the registered repositories")

        plans: list[ProjectRepositoryMigrationPlan] = []
        seen_ids: set[tuple[str, str]] = set()
        for key, repository in self._by_key.items():
            inventory = by_key[key]
            observed_counts = self._validate_inventory(
                repository,
                inventory,
            )
            repository_plans = _bounded_tuple(
                repository.plan_migrations(inventory),
                limit=_MAX_MIGRATION_PLANS,
                label=f"Repository {key!r} migration plan",
            )
            if inventory.status == "current" and repository_plans:
                raise ProjectRepositoryError(f"Current repository {key!r} returned a migration plan")
            if inventory.status == "migration_required" and not repository_plans:
                raise ProjectRepositoryError(f"Repository {key!r} requires migration but returned no plan")
            if inventory.status == "blocked" and repository_plans:
                raise ProjectRepositoryError(f"Blocked repository {key!r} returned a migration plan")

            current_by_kind = {schema.record_kind: schema.current_schema for schema in repository.descriptor.schemas}
            outdated_records = {identity for identity in observed_counts if identity[1] != current_by_kind[identity[0]]}
            planned_sources: set[tuple[str, str]] = set()
            for plan in repository_plans:
                if plan.repository_key != key:
                    raise ProjectRepositoryError("Migration plan identity does not match its repository")
                identity = (key, plan.migration_id)
                if identity in seen_ids:
                    raise ProjectRepositoryError(f"Repository migration {key}:{plan.migration_id} is duplicated")
                if plan.record_kind not in current_by_kind:
                    raise ProjectRepositoryError(f"Repository migration {key}:{plan.migration_id} references an undeclared record kind")
                source_records = {(plan.record_kind, schema) for schema in plan.source_schemas}
                if not source_records.issubset(outdated_records):
                    raise ProjectRepositoryError(f"Repository migration {key}:{plan.migration_id} references an unobserved source schema")
                if source_records & planned_sources:
                    raise ProjectRepositoryError(f"Repository migration {key}:{plan.migration_id} overlaps another migration")
                if plan.target_schemas != (current_by_kind[plan.record_kind],):
                    raise ProjectRepositoryError(f"Repository migration {key}:{plan.migration_id} does not target a current schema")
                expected_records = sum(observed_counts[record] for record in source_records)
                if plan.affected_records != expected_records:
                    raise ProjectRepositoryError(f"Repository migration {key}:{plan.migration_id} has an inconsistent record count")
                seen_ids.add(identity)
                planned_sources.update(source_records)
                plans.append(plan)
            if inventory.status == "migration_required" and planned_sources != outdated_records:
                raise ProjectRepositoryError(f"Repository {key!r} does not cover every outdated schema")
        return _bounded_tuple(
            plans,
            limit=_MAX_MIGRATION_PLANS,
            label="Combined migration plan",
        )

    def apply_migrations(
        self,
        plans: Sequence[ProjectRepositoryMigrationPlan],
    ) -> tuple[ProjectRepositoryMigrationResult, ...]:
        requested = _bounded_tuple(
            plans,
            limit=_MAX_MIGRATION_PLANS,
            label="Migration apply request",
        )
        identities = [(plan.repository_key, plan.migration_id) for plan in requested]
        if len(identities) != len(set(identities)):
            raise ProjectRepositoryError("Migration apply request contains duplicate plans")
        registered = self.migration_plan()
        if requested != registered:
            raise ProjectRepositoryError("Migration apply request is stale, incomplete, or does not match the registered plan")

        results: list[ProjectRepositoryMigrationResult] = []
        for plan in requested:
            repository = self._by_key.get(plan.repository_key)
            if repository is None:
                raise ProjectRepositoryError(f"Migration references unknown repository {plan.repository_key!r}")
            result = repository.apply_migration(plan.migration_id)
            if result.repository_key != plan.repository_key or result.migration_id != plan.migration_id:
                raise ProjectRepositoryError("Migration result identity does not match its plan")
            if result.migrated_records != plan.affected_records:
                raise ProjectRepositoryError("Migration result count does not match its plan")
            results.append(result)
        post_inventories = self.inventory()
        if any(inventory.status != "current" for inventory in post_inventories):
            raise ProjectRepositoryError("Migration apply did not leave every repository current")
        return tuple(results)


__all__ = [
    "ProjectRepository",
    "ProjectRepositoryDescriptor",
    "ProjectRepositoryError",
    "ProjectRepositoryInventory",
    "ProjectRepositoryIssue",
    "ProjectRepositoryMigrationPlan",
    "ProjectRepositoryMigrationResult",
    "ProjectRepositoryReadiness",
    "ProjectRepositoryRegistry",
    "ProjectRepositorySchema",
    "ProjectRepositorySchemaCount",
    "RepositoryDeploymentMode",
    "RepositoryInventoryStatus",
    "RepositoryMigrationSafety",
    "RepositoryReadinessStatus",
    "RepositoryScope",
    "RepositoryStorageKind",
]

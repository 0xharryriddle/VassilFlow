from __future__ import annotations

import json
from pathlib import Path

import pytest
from sample_agent_fixture import PROJECT_SCHEMA, REVISION_SCHEMA, TEMPLATE_SCHEMA, TEMPLATE_VERSION_SCHEMA, SampleProjectRepository, SampleTemplateRepository

from scripts.domain_repositories import _migrate
from vassilflow.actions.models import (
    ACTION_LEASE_SCHEMA,
    ACTION_OUTCOME_SCHEMA,
    ACTION_REPAIR_CLAIM_SCHEMA,
    ACTION_START_SCHEMA,
)
from vassilflow.actions.repository import ActionJournalRepository
from vassilflow.config.builtin_agents import list_builtin_agents
from vassilflow.config.paths import Paths
from vassilflow.persistence import (
    file_repository,
    project_repository,
    repository_registry,
)
from vassilflow.persistence.project_repository import (
    ProjectRepository,
    ProjectRepositoryDescriptor,
    ProjectRepositoryError,
    ProjectRepositoryInventory,
    ProjectRepositoryMigrationPlan,
    ProjectRepositoryMigrationResult,
    ProjectRepositoryReadiness,
    ProjectRepositoryRegistry,
    ProjectRepositorySchema,
    ProjectRepositorySchemaCount,
)
from vassilflow.runtime.lifecycle_journal import (
    LIFECYCLE_ATTEMPT_LEASE_SCHEMA,
    LIFECYCLE_EVENT_SCHEMA,
    LIFECYCLE_SOURCE_COMMIT_SCHEMA,
)
from vassilflow.runtime.lifecycle_repository import (
    ThreadLifecycleJournalRepository,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_sample_repository_readiness_does_not_create_storage(
    tmp_path: Path,
) -> None:
    projects = SampleProjectRepository(tmp_path, user_id="alice")
    templates = SampleTemplateRepository(tmp_path, user_id="alice")

    assert projects.check_readiness().status == "ready"
    assert templates.check_readiness().status == "ready"
    assert not (tmp_path / "users").exists()


def test_sample_repository_inventory_reports_current_schemas_without_paths(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "users" / "alice" / "sample"
    _write_json(
        sample / "projects" / "ofp_a" / "project.json",
        {"schema": PROJECT_SCHEMA},
    )
    _write_json(
        sample / "projects" / "ofp_a" / "revisions" / "ofr_a" / "revision.json",
        {"schema": REVISION_SCHEMA},
    )
    _write_json(
        sample / "templates" / "oft_a" / "template.json",
        {"schema": TEMPLATE_SCHEMA},
    )
    _write_json(
        sample / "templates" / "oft_a" / "versions" / "v0001" / "version.json",
        {"schema": TEMPLATE_VERSION_SCHEMA},
    )

    registry = ProjectRepositoryRegistry(
        (
            SampleProjectRepository(tmp_path, user_id=None),
            SampleTemplateRepository(tmp_path, user_id=None),
        )
    )
    projects, templates = registry.inventory()

    assert projects.status == "current"
    assert projects.record_count == 2
    assert {(entry.record_kind, entry.schema_id, entry.count) for entry in projects.schema_counts} == {
        ("project", PROJECT_SCHEMA, 1),
        ("revision", REVISION_SCHEMA, 1),
    }
    assert templates.status == "current"
    assert templates.record_count == 2
    serialized = json.dumps([item.model_dump(mode="json") for item in (projects, templates)])
    assert str(tmp_path) not in serialized
    assert "alice" not in serialized


def test_sample_repository_inventory_fails_closed_on_unknown_schema(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "users" / "alice" / "sample" / "projects" / "ofp_a" / "project.json",
        {"schema": "vassilflow.sample.project.v2"},
    )
    repository = SampleProjectRepository(tmp_path, user_id="alice")

    inventory = repository.inventory()

    assert inventory.status == "blocked"
    assert inventory.issues[0].code == "unsupported_schema"
    assert repository.plan_migrations(inventory) == ()


def test_file_repository_inventory_blocks_undeclared_json_records(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "users" / "alice" / "sample" / "projects" / "ofp_a"
    _write_json(
        project_dir / "project.json",
        {"schema": PROJECT_SCHEMA},
    )
    _write_json(
        project_dir / "future-record.json",
        {"schema": "vassilflow.sample.future.v1"},
    )

    inventory = SampleProjectRepository(
        tmp_path,
        user_id="alice",
    ).inventory()

    assert inventory.status == "blocked"
    assert [issue.code for issue in inventory.issues] == ["unknown_record_file"]


def test_file_repository_inventory_does_not_follow_directory_links(
    tmp_path: Path,
) -> None:
    collection = tmp_path / "users" / "alice" / "sample" / "projects"
    collection.mkdir(parents=True)
    outside = tmp_path / "outside"
    _write_json(
        outside / "project.json",
        {"schema": PROJECT_SCHEMA},
    )
    try:
        (collection / "linked").symlink_to(
            outside,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError):
        pytest.skip("Directory links are unavailable on this platform")

    inventory = SampleProjectRepository(
        tmp_path,
        user_id="alice",
    ).inventory()

    assert inventory.status == "blocked"
    assert inventory.record_count == 0
    assert [issue.code for issue in inventory.issues] == ["unsafe_link"]


def test_file_repository_inventory_rejects_link_in_collection_ancestor(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "users" / "alice"
    user_root.mkdir(parents=True)
    outside = tmp_path / "outside-sample"
    _write_json(
        outside / "projects" / "ofp_a" / "project.json",
        {"schema": PROJECT_SCHEMA},
    )
    try:
        (user_root / "sample").symlink_to(
            outside,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError):
        pytest.skip("Directory links are unavailable on this platform")

    inventory = SampleProjectRepository(
        tmp_path,
        user_id="alice",
    ).inventory()

    assert inventory.status == "blocked"
    assert inventory.record_count == 0
    assert [issue.code for issue in inventory.issues] == ["unsafe_link"]


def test_file_repository_inventory_rejects_hard_linked_records(
    tmp_path: Path,
) -> None:
    source = tmp_path / "outside" / "project.json"
    _write_json(source, {"schema": PROJECT_SCHEMA})
    target = tmp_path / "users" / "alice" / "sample" / "projects" / "ofp_a" / "project.json"
    target.parent.mkdir(parents=True)
    try:
        target.hardlink_to(source)
    except (NotImplementedError, OSError):
        pytest.skip("Hard links are unavailable on this platform")

    inventory = SampleProjectRepository(
        tmp_path,
        user_id="alice",
    ).inventory()

    assert inventory.status == "blocked"
    assert inventory.record_count == 1
    assert [issue.code for issue in inventory.issues] == ["unsafe_link"]


def test_file_repository_inventory_rejects_oversized_record(
    tmp_path: Path,
) -> None:
    record = tmp_path / "users" / "alice" / "sample" / "projects" / "ofp_a" / "project.json"
    record.parent.mkdir(parents=True)
    record.write_bytes(b"x" * (file_repository._MAX_RECORD_BYTES + 1))

    inventory = SampleProjectRepository(
        tmp_path,
        user_id="alice",
    ).inventory()

    assert inventory.status == "blocked"
    assert inventory.record_count == 1
    assert [issue.code for issue in inventory.issues] == ["record_size"]


def test_file_repository_scan_limit_counts_all_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = tmp_path / "users" / "alice" / "sample" / "projects"
    collection.mkdir(parents=True)
    for name in ("one.txt", "two.txt", "three.txt"):
        (collection / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(
        file_repository,
        "_MAX_SCAN_ENTRIES",
        2,
    )

    inventory = SampleProjectRepository(
        tmp_path,
        user_id="alice",
    ).inventory()

    assert inventory.status == "blocked"
    assert inventory.record_count == 0
    assert [issue.code for issue in inventory.issues] == ["inventory_limit"]


def test_file_repository_inventory_reports_walk_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = tmp_path / "users" / "alice" / "sample" / "projects"
    collection.mkdir(parents=True)

    def inaccessible_scandir(_root):
        raise PermissionError("private host path")

    monkeypatch.setattr(
        file_repository.os,
        "scandir",
        inaccessible_scandir,
    )

    inventory = SampleProjectRepository(
        tmp_path,
        user_id="alice",
    ).inventory()

    assert inventory.status == "blocked"
    assert inventory.record_count == 0
    assert inventory.issues[0].code == "inventory_unavailable"
    assert "private host path" not in inventory.issues[0].detail


def test_action_journal_uses_the_same_bounded_inventory_contract(
    tmp_path: Path,
) -> None:
    action_dir = tmp_path / "users" / "alice" / "actions" / "act_00000000000000000000000000000000"
    _write_json(
        action_dir / "started.json",
        {"schema": ACTION_START_SCHEMA},
    )
    _write_json(
        action_dir / "outcome.json",
        {"schema": ACTION_OUTCOME_SCHEMA},
    )
    _write_json(
        action_dir / "lease.json",
        {"schema": ACTION_LEASE_SCHEMA},
    )
    _write_json(
        action_dir / "repair_claim.json",
        {"schema": ACTION_REPAIR_CLAIM_SCHEMA},
    )
    repository = ActionJournalRepository(tmp_path, user_id=None)

    inventory = repository.inventory()

    assert inventory.status == "current"
    assert inventory.record_count == 4
    assert {(entry.record_kind, entry.schema_id) for entry in inventory.schema_counts} == {
        ("action_start", ACTION_START_SCHEMA),
        ("action_outcome", ACTION_OUTCOME_SCHEMA),
        ("action_lease", ACTION_LEASE_SCHEMA),
        (
            "action_repair_claim",
            ACTION_REPAIR_CLAIM_SCHEMA,
        ),
    }


def test_lifecycle_journal_has_operational_schema_inventory(
    tmp_path: Path,
) -> None:
    operation = tmp_path / "users" / "alice" / "lifecycle" / "lco_00000000000000000000000000000000"
    _write_json(
        operation / "event.json",
        {"schema": LIFECYCLE_EVENT_SCHEMA},
    )
    _write_json(
        operation / "source_committed.json",
        {"schema": LIFECYCLE_SOURCE_COMMIT_SCHEMA},
    )
    _write_json(
        operation / "attempts" / "sample.thread_links" / "lca_00000000000000000000000000000000" / "lease.json",
        {"schema": LIFECYCLE_ATTEMPT_LEASE_SCHEMA},
    )

    inventory = ThreadLifecycleJournalRepository(
        tmp_path,
        user_id=None,
    ).inventory()

    assert inventory.status == "current"
    assert inventory.record_count == 3
    assert {(entry.record_kind, entry.schema_id) for entry in inventory.schema_counts} == {
        (
            "lifecycle_attempt_lease",
            LIFECYCLE_ATTEMPT_LEASE_SCHEMA,
        ),
        ("lifecycle_event", LIFECYCLE_EVENT_SCHEMA),
        (
            "lifecycle_source_commit",
            LIFECYCLE_SOURCE_COMMIT_SCHEMA,
        ),
    }


def test_repository_discovery_reuses_shared_capability_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definitions = list_builtin_agents()
    assert len(definitions) == 1
    monkeypatch.setattr(
        repository_registry,
        "get_paths",
        lambda: Paths(tmp_path),
    )
    monkeypatch.setattr(
        repository_registry,
        "list_builtin_agents",
        lambda: (definitions[0], definitions[0]),
    )

    registry = repository_registry.build_domain_repository_registry(
        user_id="alice",
    )

    assert [repository.descriptor.key for repository in registry.repositories] == [
        "actions.journal",
        "lifecycle.journal",
        "sample.projects",
        "sample.templates",
    ]


class _ResearchProjectRepository:
    """Second project shape used to prove the contract has no Sample fields."""

    descriptor = ProjectRepositoryDescriptor(
        key="research.projects",
        display_name="Research Projects",
        storage_kind="database",
        deployment_mode="multi_writer",
        migration_safety="transactional",
        scope="user",
        schemas=(
            ProjectRepositorySchema(
                record_kind="research_project",
                current_schema="vassilflow.research.project.v2",
            ),
        ),
    )

    def __init__(self) -> None:
        self.schema = "vassilflow.research.project.v1"

    def check_readiness(self) -> ProjectRepositoryReadiness:
        return ProjectRepositoryReadiness(
            repository_key=self.descriptor.key,
            status="ready",
            detail="Research project storage is ready.",
        )

    def inventory(self) -> ProjectRepositoryInventory:
        current = self.schema == "vassilflow.research.project.v2"
        return ProjectRepositoryInventory(
            repository_key=self.descriptor.key,
            status="current" if current else "migration_required",
            record_count=3,
            schema_counts=(
                ProjectRepositorySchemaCount(
                    record_kind="research_project",
                    schema=self.schema,
                    count=3,
                ),
            ),
        )

    def plan_migrations(
        self,
        inventory: ProjectRepositoryInventory,
    ) -> tuple[ProjectRepositoryMigrationPlan, ...]:
        if inventory.status == "current":
            return ()
        return (
            ProjectRepositoryMigrationPlan(
                repository_key=self.descriptor.key,
                migration_id="research-project-v1-to-v2",
                summary="Upgrade research project metadata.",
                record_kind="research_project",
                source_schemas=("vassilflow.research.project.v1",),
                target_schemas=("vassilflow.research.project.v2",),
                affected_records=3,
            ),
        )

    def apply_migration(
        self,
        migration_id: str,
    ) -> ProjectRepositoryMigrationResult:
        assert migration_id == "research-project-v1-to-v2"
        self.schema = "vassilflow.research.project.v2"
        return ProjectRepositoryMigrationResult(
            repository_key=self.descriptor.key,
            migration_id=migration_id,
            migrated_records=3,
        )


def test_repository_contract_supports_a_second_project_domain(
    tmp_path: Path,
) -> None:
    sample = SampleProjectRepository(tmp_path, user_id=None)
    research = _ResearchProjectRepository()
    assert isinstance(sample, ProjectRepository)
    assert isinstance(research, ProjectRepository)
    registry = ProjectRepositoryRegistry((sample, research))

    inventories = registry.inventory()
    plans = registry.migration_plan(inventories)
    results = registry.apply_migrations(plans)

    assert [repository.descriptor.key for repository in registry.repositories] == [
        "sample.projects",
        "research.projects",
    ]
    assert [plan.migration_id for plan in plans] == ["research-project-v1-to-v2"]
    assert results[0].migrated_records == 3
    assert research.inventory().status == "current"


def test_repository_apply_command_reinventories_after_migration() -> None:
    registry = ProjectRepositoryRegistry((_ResearchProjectRepository(),))

    report, exit_code = _migrate(registry, apply=True)

    assert exit_code == 0
    assert report["results"][0]["migrated_records"] == 3
    assert report["post_inventories"][0]["status"] == "current"


def test_repository_registry_rejects_duplicate_inventory_identity() -> None:
    research = _ResearchProjectRepository()
    registry = ProjectRepositoryRegistry((research,))
    inventory = research.inventory()

    with pytest.raises(
        ProjectRepositoryError,
        match="duplicate repository identities",
    ):
        registry.migration_plan((inventory, inventory))


def test_repository_registry_rejects_tampered_apply_plan() -> None:
    research = _ResearchProjectRepository()
    registry = ProjectRepositoryRegistry((research,))
    plan = registry.migration_plan()[0]
    tampered = plan.model_copy(update={"affected_records": plan.affected_records - 1})

    with pytest.raises(
        ProjectRepositoryError,
        match="stale, incomplete",
    ):
        registry.apply_migrations((tampered,))

    assert research.schema == "vassilflow.research.project.v1"


class _UnplannedResearchProjectRepository(_ResearchProjectRepository):
    def plan_migrations(
        self,
        inventory: ProjectRepositoryInventory,
    ) -> tuple[ProjectRepositoryMigrationPlan, ...]:
        assert inventory.status == "migration_required"
        return ()


class _NoopResearchProjectRepository(_ResearchProjectRepository):
    def apply_migration(
        self,
        migration_id: str,
    ) -> ProjectRepositoryMigrationResult:
        return ProjectRepositoryMigrationResult(
            repository_key=self.descriptor.key,
            migration_id=migration_id,
            migrated_records=3,
        )


class _CrossKindResearchProjectRepository(_ResearchProjectRepository):
    descriptor = ProjectRepositoryDescriptor(
        key="research.projects",
        display_name="Research Projects",
        storage_kind="database",
        deployment_mode="multi_writer",
        migration_safety="transactional",
        scope="user",
        schemas=(
            ProjectRepositorySchema(
                record_kind="research_project",
                current_schema="vassilflow.research.project.v2",
            ),
            ProjectRepositorySchema(
                record_kind="research_note",
                current_schema="vassilflow.research.note.v1",
            ),
        ),
    )

    def plan_migrations(
        self,
        inventory: ProjectRepositoryInventory,
    ) -> tuple[ProjectRepositoryMigrationPlan, ...]:
        assert inventory.status == "migration_required"
        return (
            ProjectRepositoryMigrationPlan(
                repository_key=self.descriptor.key,
                migration_id="wrong-kind",
                summary="Invalid cross-kind migration.",
                record_kind="research_note",
                source_schemas=("vassilflow.research.project.v1",),
                target_schemas=("vassilflow.research.note.v1",),
                affected_records=3,
            ),
        )


class _DishonestCurrentResearchRepository(_ResearchProjectRepository):
    def inventory(self) -> ProjectRepositoryInventory:
        return super().inventory().model_copy(update={"status": "current"})


def test_repository_registry_requires_complete_migration_plan() -> None:
    registry = ProjectRepositoryRegistry((_UnplannedResearchProjectRepository(),))

    with pytest.raises(
        ProjectRepositoryError,
        match="requires migration but returned no plan",
    ):
        registry.migration_plan()


def test_repository_registry_verifies_apply_postcondition() -> None:
    repository = _NoopResearchProjectRepository()
    registry = ProjectRepositoryRegistry((repository,))
    plans = registry.migration_plan()

    with pytest.raises(
        ProjectRepositoryError,
        match="did not leave every repository current",
    ):
        registry.apply_migrations(plans)

    assert repository.schema == "vassilflow.research.project.v1"


def test_repository_registry_preserves_record_kind_during_planning() -> None:
    registry = ProjectRepositoryRegistry((_CrossKindResearchProjectRepository(),))

    with pytest.raises(
        ProjectRepositoryError,
        match="unobserved source schema",
    ):
        registry.migration_plan()


def test_repository_registry_rejects_inconsistent_current_inventory() -> None:
    registry = ProjectRepositoryRegistry((_DishonestCurrentResearchRepository(),))

    with pytest.raises(
        ProjectRepositoryError,
        match="invalid current inventory",
    ):
        registry.inventory()


def test_repository_registry_enforces_repository_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        project_repository,
        "_MAX_REPOSITORIES",
        2,
    )

    with pytest.raises(
        ProjectRepositoryError,
        match="operational limit",
    ):
        ProjectRepositoryRegistry(_ResearchProjectRepository() for _ in range(3))


def test_multi_writer_repository_requires_transactional_migrations() -> None:
    with pytest.raises(
        ValueError,
        match="transactional migrations",
    ):
        ProjectRepositoryDescriptor(
            key="unsafe.projects",
            display_name="Unsafe Projects",
            storage_kind="database",
            deployment_mode="multi_writer",
            migration_safety="maintenance_window",
            scope="user",
            schemas=(
                ProjectRepositorySchema(
                    record_kind="unsafe_project",
                    current_schema="vassilflow.unsafe.project.v1",
                ),
            ),
        )


pytestmark = pytest.mark.usefixtures("sample_builtin_registry")

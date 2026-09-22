"""Operational repository adapter for the append-only Action journal."""

from __future__ import annotations

from vassilflow.persistence.file_repository import (
    UserScopedFileRecordRepository,
)
from vassilflow.persistence.project_repository import (
    ProjectRepositoryDescriptor,
    ProjectRepositorySchema,
)

from .models import (
    ACTION_LEASE_SCHEMA,
    ACTION_OUTCOME_SCHEMA,
    ACTION_REPAIR_CLAIM_SCHEMA,
    ACTION_START_SCHEMA,
)


class ActionJournalRepository(UserScopedFileRecordRepository):
    """Expose Action journal readiness and schema inventory."""

    descriptor = ProjectRepositoryDescriptor(
        key="actions.journal",
        display_name="Action Journal",
        storage_kind="filesystem",
        deployment_mode="single_writer",
        migration_safety="maintenance_window",
        scope="user",
        schemas=(
            ProjectRepositorySchema(
                record_kind="action_start",
                current_schema=ACTION_START_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="action_outcome",
                current_schema=ACTION_OUTCOME_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="action_lease",
                current_schema=ACTION_LEASE_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="action_repair_claim",
                current_schema=ACTION_REPAIR_CLAIM_SCHEMA,
            ),
        ),
    )
    relative_collection = ("actions",)
    record_files = {
        "started.json": "action_start",
        "outcome.json": "action_outcome",
        "lease.json": "action_lease",
        "repair_claim.json": "action_repair_claim",
    }


__all__ = ["ActionJournalRepository"]

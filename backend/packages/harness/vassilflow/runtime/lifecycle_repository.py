"""Operational repository adapter for the thread lifecycle journal."""

from __future__ import annotations

from vassilflow.persistence.file_repository import (
    UserScopedFileRecordRepository,
)
from vassilflow.persistence.project_repository import (
    ProjectRepositoryDescriptor,
    ProjectRepositorySchema,
)

from .lifecycle_journal import (
    LIFECYCLE_ATTEMPT_LEASE_SCHEMA,
    LIFECYCLE_ATTEMPT_OUTCOME_SCHEMA,
    LIFECYCLE_ATTEMPT_START_SCHEMA,
    LIFECYCLE_EVENT_SCHEMA,
    LIFECYCLE_SOURCE_ABORT_SCHEMA,
    LIFECYCLE_SOURCE_COMMIT_SCHEMA,
    LIFECYCLE_SOURCE_PREPARE_SCHEMA,
)


class ThreadLifecycleJournalRepository(UserScopedFileRecordRepository):
    """Expose lifecycle projection schemas and storage readiness."""

    descriptor = ProjectRepositoryDescriptor(
        key="lifecycle.journal",
        display_name="Thread Lifecycle Journal",
        storage_kind="filesystem",
        deployment_mode="single_writer",
        migration_safety="maintenance_window",
        scope="user",
        schemas=(
            ProjectRepositorySchema(
                record_kind="lifecycle_event",
                current_schema=LIFECYCLE_EVENT_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="lifecycle_source_prepare",
                current_schema=LIFECYCLE_SOURCE_PREPARE_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="lifecycle_source_commit",
                current_schema=LIFECYCLE_SOURCE_COMMIT_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="lifecycle_source_abort",
                current_schema=LIFECYCLE_SOURCE_ABORT_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="lifecycle_attempt_start",
                current_schema=LIFECYCLE_ATTEMPT_START_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="lifecycle_attempt_lease",
                current_schema=LIFECYCLE_ATTEMPT_LEASE_SCHEMA,
            ),
            ProjectRepositorySchema(
                record_kind="lifecycle_attempt_outcome",
                current_schema=LIFECYCLE_ATTEMPT_OUTCOME_SCHEMA,
            ),
        ),
    )
    relative_collection = ("lifecycle",)
    record_files = {
        "event.json": "lifecycle_event",
        "source_prepared.json": "lifecycle_source_prepare",
        "source_committed.json": "lifecycle_source_commit",
        "source_aborted.json": "lifecycle_source_abort",
        "started.json": "lifecycle_attempt_start",
        "lease.json": "lifecycle_attempt_lease",
        "outcome.json": "lifecycle_attempt_outcome",
    }


__all__ = ["ThreadLifecycleJournalRepository"]

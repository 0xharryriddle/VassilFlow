"""Composition root for project-backed domain lifecycle adapters."""

from __future__ import annotations

from vassilflow.config.paths import Paths, get_paths
from vassilflow.runtime.lifecycle_journal import FileThreadLifecycleJournal
from vassilflow.runtime.thread_lifecycle import ThreadLifecycleDispatcher


def build_thread_lifecycle_dispatcher(
    paths: Paths | None = None,
) -> ThreadLifecycleDispatcher:
    """Build lifecycle adapters enabled in this Gateway process."""

    paths = paths or get_paths()
    return ThreadLifecycleDispatcher(
        (),
        journal_factory=lambda user_id: FileThreadLifecycleJournal(
            paths.user_lifecycle_dir(user_id),
            owner_user_id=user_id,
        ),
    )

"""Bounded operational adapter for user-scoped JSON record repositories."""

from __future__ import annotations

import json
import os
import re
import stat
from collections import Counter
from pathlib import Path

from vassilflow.config.paths import Paths
from vassilflow.persistence.project_repository import (
    ProjectRepositoryDescriptor,
    ProjectRepositoryInventory,
    ProjectRepositoryIssue,
    ProjectRepositoryMigrationPlan,
    ProjectRepositoryMigrationResult,
    ProjectRepositoryReadiness,
    ProjectRepositorySchemaCount,
)

_MAX_USER_ROOTS = 10_000
_MAX_RECORDS = 100_000
_MAX_SCAN_ENTRIES = 200_000
_MAX_RECORD_BYTES = 2 * 1024 * 1024
_COLLECTION_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class _UnsafeFilesystemEntryError(OSError):
    pass


class _UnsupportedRecordSizeError(OSError):
    pass


def _is_link_like(path: Path) -> bool:
    """Reject symbolic links and Windows junctions during repository scans."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _path_state(path: Path) -> str:
    """Inspect one path without collapsing access errors into missing state."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "missing"
    if _is_link_like(path):
        return "link"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    return "other"


def _has_link_like_component(base: Path, target: Path) -> bool:
    """Check every existing component from a trusted root to a target."""

    relative = target.relative_to(base)
    current = base
    for segment in (None, *relative.parts):
        if segment is not None:
            current /= segment
        state = _path_state(current)
        if state == "missing":
            return False
        if state == "link":
            return True
    return False


def _directory_identity(path: Path) -> tuple[int, int, int]:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or _is_link_like(path):
        raise _UnsafeFilesystemEntryError("Repository directory is not stable")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mtime_ns,
    )


def _read_bounded_json_record(path: Path) -> object:
    """Read one stable regular file without following links or over-reading."""

    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or _is_link_like(path) or getattr(before, "st_nlink", 1) != 1:
        raise _UnsafeFilesystemEntryError("Repository record is not an independent regular file")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        after = os.fstat(descriptor)
        if not stat.S_ISREG(after.st_mode) or getattr(after, "st_nlink", 1) != 1 or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise _UnsafeFilesystemEntryError("Repository record changed during inspection")
        if after.st_size < 2 or after.st_size > _MAX_RECORD_BYTES:
            raise _UnsupportedRecordSizeError("Repository record has an unsupported size")

        chunks: list[bytes] = []
        remaining = _MAX_RECORD_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        final = os.fstat(descriptor)
        if (after.st_dev, after.st_ino) != (final.st_dev, final.st_ino) or after.st_size != final.st_size or after.st_mtime_ns != final.st_mtime_ns:
            raise _UnsafeFilesystemEntryError("Repository record changed during inspection")
    finally:
        os.close(descriptor)

    if len(raw) < 2 or len(raw) > _MAX_RECORD_BYTES:
        raise _UnsupportedRecordSizeError("Repository record has an unsupported size")
    return json.loads(raw.decode("utf-8"))


class UserScopedFileRecordRepository:
    """Read-only operational view over a user-scoped JSON collection."""

    descriptor: ProjectRepositoryDescriptor
    relative_collection: tuple[str, ...]
    record_files: dict[str, str]

    def __init__(
        self,
        state_root: str | Path,
        *,
        user_id: str | None,
    ) -> None:
        if not self.relative_collection or any(_COLLECTION_SEGMENT_RE.fullmatch(segment) is None for segment in self.relative_collection):
            raise ValueError("Repository collection path is invalid")
        if not self.record_files:
            raise ValueError("Repository record map cannot be empty")
        self._state_root = Path(state_root).absolute()
        self._user_id = user_id
        self._schema_by_kind = {schema.record_kind: schema.current_schema for schema in self.descriptor.schemas}
        if set(self.record_files.values()) - set(self._schema_by_kind):
            raise ValueError("Repository record map references an undeclared record kind")

    def _user_collection_root(self) -> Path:
        if self._user_id is None:
            raise RuntimeError("A user-scoped collection requires a user ID")
        return Paths(self._state_root).user_dir(self._user_id).joinpath(*self.relative_collection)

    def _readiness_target(self) -> Path:
        if self._user_id is not None:
            return self._user_collection_root()
        return self._state_root / "users"

    def check_readiness(self) -> ProjectRepositoryReadiness:
        """Check storage shape and permissions without creating any files."""

        try:
            target = self._readiness_target()
            candidate = target
            candidate_state = _path_state(candidate)
            while candidate_state == "missing" and candidate.parent != candidate:
                candidate = candidate.parent
                candidate_state = _path_state(candidate)
            if candidate_state != "directory":
                return ProjectRepositoryReadiness(
                    repository_key=self.descriptor.key,
                    status="unavailable",
                    detail=(f"{self.descriptor.display_name} storage has no usable directory anchor."),
                )
            if not os.access(
                candidate,
                os.R_OK | os.W_OK | os.X_OK,
            ):
                return ProjectRepositoryReadiness(
                    repository_key=self.descriptor.key,
                    status="unavailable",
                    detail=(f"{self.descriptor.display_name} storage is not readable and writable."),
                )
            target_state = _path_state(target)
            if target_state not in {"missing", "directory"}:
                return ProjectRepositoryReadiness(
                    repository_key=self.descriptor.key,
                    status="unavailable",
                    detail=(f"{self.descriptor.display_name} storage has an unsupported filesystem shape."),
                )
            if _has_link_like_component(
                self._state_root,
                target,
            ):
                return ProjectRepositoryReadiness(
                    repository_key=self.descriptor.key,
                    status="unavailable",
                    detail=(f"{self.descriptor.display_name} storage crosses an unsupported filesystem link."),
                )
        except OSError:
            return ProjectRepositoryReadiness(
                repository_key=self.descriptor.key,
                status="unavailable",
                detail=(f"{self.descriptor.display_name} storage could not be checked."),
            )

        return ProjectRepositoryReadiness(
            repository_key=self.descriptor.key,
            status="ready",
            detail=f"{self.descriptor.display_name} storage is ready.",
        )

    def _collection_roots(
        self,
    ) -> tuple[list[Path], Counter[tuple[str, str, str | None]]]:
        issues: Counter[tuple[str, str, str | None]] = Counter()
        if self._user_id is not None:
            root = self._user_collection_root()
            try:
                state = _path_state(root)
                crosses_link = _has_link_like_component(
                    self._state_root,
                    root,
                )
            except OSError:
                issues[
                    (
                        "inventory_unavailable",
                        "A repository collection could not be inspected.",
                        None,
                    )
                ] += 1
                return [], issues
            if state == "missing":
                return [], issues
            if crosses_link:
                issues[
                    (
                        "unsafe_link",
                        "Repository inventory skipped a filesystem link.",
                        None,
                    )
                ] += 1
                return [], issues
            if state != "directory":
                issues[
                    (
                        "unsupported_storage_shape",
                        "A repository collection is not a regular directory.",
                        None,
                    )
                ] += 1
                return [], issues
            return [root], issues

        users_root = self._state_root / "users"
        try:
            users_state = _path_state(users_root)
            users_cross_link = _has_link_like_component(
                self._state_root,
                users_root,
            )
        except OSError:
            issues[
                (
                    "inventory_unavailable",
                    "The user repository root could not be inspected.",
                    None,
                )
            ] += 1
            return [], issues
        if users_state == "missing":
            return [], issues
        if users_cross_link:
            issues[
                (
                    "unsafe_link",
                    "Repository inventory skipped a filesystem link.",
                    None,
                )
            ] += 1
            return [], issues
        if users_state != "directory":
            issues[
                (
                    "unsupported_storage_shape",
                    "The user repository root is not a regular directory.",
                    None,
                )
            ] += 1
            return [], issues

        roots: list[Path] = []
        try:
            entries: list[Path] = []
            with os.scandir(users_root) as iterator:
                for index, entry in enumerate(iterator):
                    if index >= _MAX_USER_ROOTS:
                        issues[
                            (
                                "inventory_limit",
                                "Repository inventory exceeded the bounded user limit.",
                                None,
                            )
                        ] += 1
                        break
                    entries.append(Path(entry.path))
        except OSError:
            issues[
                (
                    "inventory_unavailable",
                    "Repository user collections could not be listed.",
                    None,
                )
            ] += 1
            return roots, issues

        for user_root in sorted(
            entries,
            key=lambda entry: entry.name,
        ):
            try:
                user_state = _path_state(user_root)
                if user_state == "link":
                    issues[
                        (
                            "unsafe_link",
                            "Repository inventory skipped a filesystem link.",
                            None,
                        )
                    ] += 1
                    continue
                if user_state != "directory":
                    continue
                collection = user_root.joinpath(*self.relative_collection)
                collection_state = _path_state(collection)
                if collection_state == "missing":
                    continue
                if _has_link_like_component(
                    user_root,
                    collection,
                ):
                    issues[
                        (
                            "unsafe_link",
                            "Repository inventory skipped a filesystem link.",
                            None,
                        )
                    ] += 1
                    continue
                if collection_state != "directory":
                    issues[
                        (
                            "unsupported_storage_shape",
                            "A repository collection is not a regular directory.",
                            None,
                        )
                    ] += 1
                    continue
                roots.append(collection)
            except OSError:
                issues[
                    (
                        "inventory_unavailable",
                        "A repository collection could not be inspected.",
                        None,
                    )
                ] += 1
        return roots, issues

    def inventory(self) -> ProjectRepositoryInventory:
        """Inventory current top-level schemas with bounded filesystem reads."""

        roots, issue_counts = self._collection_roots()
        schema_counts: Counter[tuple[str, str]] = Counter()
        record_count = 0
        scan_entries = 0
        limit_reached = False
        directories = sorted(
            roots,
            key=str,
            reverse=True,
        )

        while directories and not limit_reached:
            current_dir = directories.pop()
            try:
                directory_identity = _directory_identity(current_dir)
                entries: list[Path] = []
                with os.scandir(current_dir) as iterator:
                    for entry in iterator:
                        scan_entries += 1
                        if scan_entries > _MAX_SCAN_ENTRIES:
                            issue_counts[
                                (
                                    "inventory_limit",
                                    "Repository inventory exceeded the bounded entry limit.",
                                    None,
                                )
                            ] += 1
                            limit_reached = True
                            break
                        entries.append(Path(entry.path))
                if _directory_identity(current_dir) != directory_identity:
                    raise _UnsafeFilesystemEntryError("Repository directory changed during inspection")
            except _UnsafeFilesystemEntryError:
                issue_counts[
                    (
                        "unsafe_link",
                        "Repository inventory skipped an unstable directory.",
                        None,
                    )
                ] += 1
                continue
            except OSError:
                issue_counts[
                    (
                        "inventory_unavailable",
                        "A repository directory could not be listed.",
                        None,
                    )
                ] += 1
                continue
            if limit_reached:
                break

            child_directories: list[Path] = []
            for child in sorted(
                entries,
                key=lambda entry: entry.name,
            ):
                record_kind = self.record_files.get(child.name)
                try:
                    child_state = _path_state(child)
                except OSError:
                    issue_counts[
                        (
                            "inventory_unavailable",
                            "A repository entry could not be inspected.",
                            record_kind,
                        )
                    ] += 1
                    continue
                if child_state == "link":
                    issue_counts[
                        (
                            "unsafe_link",
                            "Repository inventory skipped a filesystem link.",
                            record_kind,
                        )
                    ] += 1
                    continue
                if child_state == "directory":
                    child_directories.append(child)
                    continue
                if child_state != "file":
                    continue
                if record_kind is None:
                    if child.name.lower().endswith(".json"):
                        issue_counts[
                            (
                                "unknown_record_file",
                                "Repository inventory found an undeclared JSON record.",
                                None,
                            )
                        ] += 1
                    continue
                if record_count >= _MAX_RECORDS:
                    issue_counts[
                        (
                            "inventory_limit",
                            "Repository inventory exceeded the bounded record limit.",
                            None,
                        )
                    ] += 1
                    limit_reached = True
                    break
                record_count += 1

                try:
                    payload = _read_bounded_json_record(child)
                except _UnsafeFilesystemEntryError:
                    issue_counts[
                        (
                            "unsafe_link",
                            "Repository inventory skipped an unsafe record link.",
                            record_kind,
                        )
                    ] += 1
                    continue
                except _UnsupportedRecordSizeError:
                    issue_counts[
                        (
                            "record_size",
                            "A repository record has an unsupported size.",
                            record_kind,
                        )
                    ] += 1
                    continue
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ):
                    issue_counts[
                        (
                            "invalid_record",
                            "A repository record could not be decoded.",
                            record_kind,
                        )
                    ] += 1
                    continue

                if not isinstance(payload, dict):
                    issue_counts[
                        (
                            "invalid_record",
                            "A repository record is not a JSON object.",
                            record_kind,
                        )
                    ] += 1
                    continue
                schema = payload.get("schema")
                if not isinstance(schema, str) or not schema:
                    issue_counts[
                        (
                            "missing_schema",
                            "A repository record has no valid schema identity.",
                            record_kind,
                        )
                    ] += 1
                    continue
                schema_counts[(record_kind, schema)] += 1
                if schema != self._schema_by_kind[record_kind]:
                    issue_counts[
                        (
                            "unsupported_schema",
                            "A repository record requires an explicit migration path.",
                            record_kind,
                        )
                    ] += 1

            try:
                if _directory_identity(current_dir) != directory_identity:
                    issue_counts[
                        (
                            "inventory_unavailable",
                            "A repository directory changed during inventory.",
                            None,
                        )
                    ] += 1
            except OSError:
                issue_counts[
                    (
                        "inventory_unavailable",
                        "A repository directory could not be rechecked.",
                        None,
                    )
                ] += 1
            if not limit_reached:
                directories.extend(reversed(child_directories))

        issues = tuple(
            ProjectRepositoryIssue(
                code=code,
                detail=detail,
                count=count,
                record_kind=record_kind,
            )
            for (code, detail, record_kind), count in sorted(
                issue_counts.items(),
                key=lambda item: (
                    item[0][0],
                    item[0][2] or "",
                    item[0][1],
                ),
            )
        )
        observed = tuple(
            ProjectRepositorySchemaCount(
                record_kind=record_kind,
                schema=schema,
                count=count,
            )
            for (record_kind, schema), count in sorted(schema_counts.items())
        )
        return ProjectRepositoryInventory(
            repository_key=self.descriptor.key,
            status="blocked" if issues else "current",
            record_count=min(record_count, _MAX_RECORDS),
            schema_counts=observed,
            issues=issues,
        )

    def plan_migrations(
        self,
        inventory: ProjectRepositoryInventory,
    ) -> tuple[ProjectRepositoryMigrationPlan, ...]:
        if inventory.repository_key != self.descriptor.key:
            raise ValueError("Repository inventory identity does not match")
        return ()

    def apply_migration(
        self,
        migration_id: str,
    ) -> ProjectRepositoryMigrationResult:
        raise ValueError(f"Repository {self.descriptor.key!r} has no migration {migration_id!r}")


__all__ = ["UserScopedFileRecordRepository"]

"""OPC package preservation checks shared by structured Office editors."""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Collection
from dataclasses import dataclass

from .errors import OfficePackageError


@dataclass(frozen=True, slots=True)
class _OpcEntry:
    info: zipfile.ZipInfo
    payload_digest: bytes


@dataclass(frozen=True, slots=True)
class _OpcPackage:
    comment: bytes
    ordered_names: tuple[str, ...]
    entries: dict[str, _OpcEntry]


def _read_package(data: bytes, *, label: str) -> _OpcPackage:
    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            entries: dict[str, _OpcEntry] = {}
            ordered_names: list[str] = []
            for info in archive.infolist():
                if info.filename in entries:
                    raise OfficePackageError(f"{label} contains a duplicate package entry: {info.filename}")
                ordered_names.append(info.filename)
                entries[info.filename] = _OpcEntry(
                    info=info,
                    payload_digest=hashlib.sha256(archive.read(info)).digest(),
                )
            return _OpcPackage(
                comment=archive.comment,
                ordered_names=tuple(ordered_names),
                entries=entries,
            )
    except OfficePackageError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise OfficePackageError(f"Invalid {label} package: {exc}") from exc


def _stable_metadata(info: zipfile.ZipInfo) -> tuple[object, ...]:
    # Bit 3 only records whether CRC and sizes followed the payload in a data
    # descriptor. Deflate bits 1-2 are encoder tuning hints. Python's ZIP
    # writer clears all three when repacking to a seekable stream.
    ignored_flag_bits = 0x08
    if info.compress_type == zipfile.ZIP_DEFLATED:
        ignored_flag_bits |= 0x06
    semantic_flag_bits = info.flag_bits & ~ignored_flag_bits

    # For DOS-created entries only the lower 16 bits carry DOS attributes.
    # zipfile supplies Unix permissions in the unused upper half when the
    # source value is zero, as is common in PowerPoint-authored packages.
    semantic_external_attr = info.external_attr
    if info.create_system == 0:
        semantic_external_attr &= 0xFFFF
    return (
        info.date_time,
        info.compress_type,
        info.comment,
        info.extra,
        info.create_system,
        info.create_version,
        info.extract_version,
        semantic_flag_bits,
        info.volume,
        info.internal_attr,
        semantic_external_attr,
    )


def enforce_package_preservation(
    before: bytes,
    after: bytes,
    *,
    changed_parts: Collection[str],
    added_parts: Collection[str] = (),
    removed_parts: Collection[str] = (),
    label: str,
) -> None:
    """Reject package changes outside an explicit OPC part allowlist."""
    changed = frozenset(changed_parts)
    added = frozenset(added_parts)
    removed = frozenset(removed_parts)
    if (changed & added) or (changed & removed) or (added & removed):
        raise OfficePackageError(f"{label} preservation policy contains overlapping part sets")

    source = _read_package(before, label=label)
    result = _read_package(after, label=label)
    source_names = frozenset(source.entries)
    result_names = frozenset(result.entries)
    actual_added = result_names - source_names
    actual_removed = source_names - result_names
    if actual_added != added:
        raise OfficePackageError(f"{label} edit changed the unexpected added-part set")
    if actual_removed != removed:
        raise OfficePackageError(f"{label} edit changed the unexpected removed-part set")
    if changed - (source_names & result_names):
        raise OfficePackageError(f"{label} preservation policy names a missing changed part")
    if source.comment != result.comment:
        raise OfficePackageError(f"{label} edit changed the package comment")

    common_source_order = tuple(name for name in source.ordered_names if name not in removed)
    common_result_order = tuple(name for name in result.ordered_names if name not in added)
    if common_source_order != common_result_order:
        raise OfficePackageError(f"{label} edit changed the relative package entry order")

    for part_name in source_names & result_names:
        source_entry = source.entries[part_name]
        result_entry = result.entries[part_name]
        if _stable_metadata(source_entry.info) != _stable_metadata(result_entry.info):
            raise OfficePackageError(f"{label} edit changed ZIP metadata for {part_name}")
        if part_name not in changed and source_entry.payload_digest != result_entry.payload_digest:
            raise OfficePackageError(f"{label} edit changed an unapproved package part: {part_name}")

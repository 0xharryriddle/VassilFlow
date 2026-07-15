"""Presentation-time visual review enforcement for Office artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from vassilflow.tools.types import Runtime

_OFFICE_FORMATS = {
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_MANIFESTS = 512
_MAX_PAGE_COUNT = 10_000


@dataclass(frozen=True)
class OfficeVisualReviewDecision:
    status: str
    blocked: bool
    message: str | None = None


def _has_view_image(runtime: Runtime) -> bool:
    tools = getattr(runtime, "tools", ()) or ()
    return any(getattr(candidate, "name", None) == "view_image" for candidate in tools)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_paths(runtime: Runtime) -> Iterator[Path]:
    state = getattr(runtime, "state", None)
    if not isinstance(state, Mapping):
        return
    thread_data = state.get("thread_data")
    if not isinstance(thread_data, Mapping):
        return

    seen: set[Path] = set()
    yielded = 0
    for key in ("workspace_path", "outputs_path"):
        root_value = thread_data.get(key)
        if not isinstance(root_value, str) or not root_value:
            continue
        root = Path(root_value).resolve()
        if not root.is_dir():
            continue
        try:
            candidates = root.rglob("render-manifest.json")
            for candidate in candidates:
                if yielded >= _MAX_MANIFESTS:
                    return
                resolved = candidate.resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    continue
                if resolved in seen or not resolved.is_file():
                    continue
                seen.add(resolved)
                yielded += 1
                yield resolved
        except OSError:
            continue


def _load_manifest(path: Path) -> dict | None:
    try:
        if path.stat().st_size > _MAX_MANIFEST_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalized_sha256(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        return None
    return normalized


def _resolve_gateway_page(runtime: Runtime, virtual_path: str) -> Path | None:
    state = getattr(runtime, "state", None)
    if not isinstance(state, Mapping):
        return None
    thread_data = state.get("thread_data")
    if not isinstance(thread_data, Mapping):
        return None
    prefixes = {
        "/mnt/user-data/workspace": "workspace_path",
        "/mnt/user-data/outputs": "outputs_path",
    }
    for prefix, key in prefixes.items():
        if virtual_path != prefix and not virtual_path.startswith(f"{prefix}/"):
            continue
        root_value = thread_data.get(key)
        if not isinstance(root_value, str) or not root_value:
            return None
        root = Path(root_value).resolve()
        relative = virtual_path[len(prefix) :].lstrip("/")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate
    return None


def _blocked(message: str, *, status: str = "render_required") -> OfficeVisualReviewDecision:
    return OfficeVisualReviewDecision(status=status, blocked=True, message=message)


def evaluate_office_visual_review(
    runtime: Runtime,
    *,
    virtual_path: str,
    actual_path: Path,
) -> OfficeVisualReviewDecision | None:
    """Evaluate whether an Office output is ready for ``present_files``."""
    office_format = _OFFICE_FORMATS.get(actual_path.suffix.lower())
    if office_format is None:
        return None

    try:
        source_sha256 = _sha256_file(actual_path)
    except OSError:
        return _blocked(f"Office output could not be read before presentation: {virtual_path}")

    source_manifests: list[dict] = []
    current_manifests: list[dict] = []
    for manifest_path in _manifest_paths(runtime):
        manifest = _load_manifest(manifest_path)
        if manifest is None or manifest.get("format") != office_format or manifest.get("source_path") != virtual_path:
            continue
        source_manifests.append(manifest)
        if _normalized_sha256(manifest.get("source_sha256")) == source_sha256:
            current_manifests.append(manifest)

    if not source_manifests:
        return _blocked(f"Render the complete Office output before presenting it: {virtual_path}. Use office_render and cover every page in the current file.")
    if not current_manifests:
        return _blocked(
            f"The Office render is stale for {virtual_path}. Render the current file again before presenting it.",
            status="stale",
        )

    page_counts = {manifest.get("page_count") for manifest in current_manifests if isinstance(manifest.get("page_count"), int) and not isinstance(manifest.get("page_count"), bool) and 0 < manifest["page_count"] <= _MAX_PAGE_COUNT}
    if len(page_counts) != 1:
        return _blocked(
            f"Office render manifests disagree on page count for {virtual_path}. Re-render every page into new directories.",
            status="incomplete",
        )
    page_count = page_counts.pop()

    pages: dict[int, tuple[str, str, bool]] = {}
    external_review_required = False
    for manifest in current_manifests:
        if manifest.get("complete") is not True:
            continue
        status = manifest.get("visual_review_status")
        if status not in {"pending", "reviewed", "external_review_required"}:
            return _blocked(
                f"Office render has an unknown visual review status for {virtual_path}. Re-render the current file.",
                status="incomplete",
            )
        if status == "external_review_required" or manifest.get("gateway_page_access") != "available":
            external_review_required = True
        records = manifest.get("pages")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, Mapping):
                continue
            page = record.get("page")
            page_path = record.get("path")
            page_sha256 = _normalized_sha256(record.get("sha256"))
            if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= page_count:
                continue
            if not isinstance(page_path, str) or not page_path.startswith("/mnt/user-data/") or page_sha256 is None:
                continue
            page_record = (page_path, page_sha256)
            gateway_available = manifest.get("gateway_page_access") == "available"
            if page in pages and pages[page][:2] != page_record:
                return _blocked(
                    f"Office render manifests conflict on page {page} for {virtual_path}. Re-render every page into new directories.",
                    status="incomplete",
                )
            previous_gateway_available = pages[page][2] if page in pages else False
            pages[page] = (*page_record, gateway_available or previous_gateway_available)

    missing_pages = sorted(set(range(1, page_count + 1)) - pages.keys())
    if missing_pages:
        preview = ", ".join(str(page) for page in missing_pages[:12])
        suffix = "..." if len(missing_pages) > 12 else ""
        return _blocked(
            f"Office render is incomplete for {virtual_path}; render missing pages {preview}{suffix} before presenting it.",
            status="incomplete",
        )

    for page_path, page_sha256, gateway_available in pages.values():
        if not gateway_available:
            continue
        gateway_page = _resolve_gateway_page(runtime, page_path)
        try:
            valid_page = gateway_page is not None and gateway_page.is_file() and _sha256_file(gateway_page) == page_sha256
        except OSError:
            valid_page = False
        if not valid_page:
            return _blocked(
                f"Rendered page data is missing or stale for {virtual_path}: {page_path}. Re-render the current file.",
                status="stale",
            )

    if external_review_required or not _has_view_image(runtime):
        return OfficeVisualReviewDecision(
            status="external_review_required",
            blocked=False,
            message=(f"Automated visual QA is not complete for {virtual_path}. Review every rendered page externally and explicitly report visual_review_status=external_review_required; do not claim that visual QA passed."),
        )

    state = getattr(runtime, "state", None)
    reviewed = state.get("visual_reviewed_images", {}) if isinstance(state, Mapping) else {}
    if not isinstance(reviewed, Mapping):
        reviewed = {}
    missing_paths = [page_path for page_path, page_sha256, _ in pages.values() if reviewed.get(page_path) != page_sha256]
    if missing_paths:
        preview = ", ".join(missing_paths[:4])
        suffix = f" (+{len(missing_paths) - 4} more)" if len(missing_paths) > 4 else ""
        return _blocked(
            f"Visual review is incomplete for {virtual_path}. Call view_image for every rendered page in a prior model step, then call present_files. Missing: {preview}{suffix}",
            status="pending",
        )

    return OfficeVisualReviewDecision(status="reviewed", blocked=False)

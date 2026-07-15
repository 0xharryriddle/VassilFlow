"""Path and capability policy for VassilFlow Office operations."""

from pathlib import PurePosixPath

from .errors import OfficePathError, UnsupportedOfficeFormatError

_READ_ROOTS = (
    "/mnt/user-data/uploads",
    "/mnt/user-data/workspace",
    "/mnt/user-data/outputs",
)
_WRITE_ROOTS = (
    "/mnt/user-data/workspace",
    "/mnt/user-data/outputs",
)
_SUPPORTED_SUFFIXES = frozenset({".docx", ".pptx", ".xlsx"})
_SUPPORTED_IMAGE_SUFFIXES = frozenset({".jpeg", ".jpg", ".png"})


def _normalize_thread_path(path: str, *, roots: tuple[str, ...], kind: str) -> str:
    if not isinstance(path, str) or not path:
        raise OfficePathError(f"{kind} must be a non-empty string")
    if "\x00" in path:
        raise OfficePathError(f"{kind} contains a null byte")

    normalized = path.replace("\\", "/")
    if not normalized.startswith("/") or normalized.startswith("//"):
        raise OfficePathError(f"{kind} must be an absolute /mnt/user-data path")

    parts = normalized.split("/")[1:]
    if any(part in {"", ".", ".."} for part in parts):
        raise OfficePathError(f"{kind} contains an unsafe segment")

    canonical = "/" + "/".join(parts)
    if not any(canonical.startswith(f"{root}/") for root in roots):
        raise OfficePathError(f"{kind} is outside the allowed thread workspace")
    return canonical


def normalize_office_path(path: str, *, writable: bool = False) -> str:
    """Validate and normalize a thread-scoped virtual Office document path."""
    roots = _WRITE_ROOTS if writable else _READ_ROOTS
    try:
        canonical = _normalize_thread_path(path, roots=roots, kind="Office document path")
    except OfficePathError as exc:
        access = "Office documents may be written only under workspace or outputs" if writable else "Office documents may be read only under thread user-data"
        if "outside the allowed thread workspace" in str(exc):
            raise OfficePathError(access) from exc
        raise

    suffix = PurePosixPath(canonical).suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(_SUPPORTED_SUFFIXES))
        raise UnsupportedOfficeFormatError(f"Unsupported Office format '{suffix or '(none)'}'; supported formats: {supported}")
    return canonical


def normalize_office_output_dir(path: str) -> str:
    """Validate a new directory used for Office render QA artifacts."""
    canonical = _normalize_thread_path(
        path,
        roots=_WRITE_ROOTS,
        kind="Office render output directory",
    )
    if PurePosixPath(canonical).suffix:
        raise OfficePathError("Office render output directory must be a directory path without a file suffix")
    return canonical


def normalize_office_image_path(path: str) -> str:
    """Validate a read-only PNG or baseline JPEG asset path used by an Office edit."""
    canonical = _normalize_thread_path(
        path,
        roots=_READ_ROOTS,
        kind="Office image path",
    )
    suffix = PurePosixPath(canonical).suffix.lower()
    if suffix not in _SUPPORTED_IMAGE_SUFFIXES:
        raise OfficePathError("PPTX image fills require a .png, .jpg, or .jpeg source image")
    return canonical

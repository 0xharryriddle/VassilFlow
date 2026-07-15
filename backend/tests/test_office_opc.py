from __future__ import annotations

import copy
import io
import zipfile

import pytest

from vassilflow.community.office.errors import OfficePackageError
from vassilflow.community.office.opc import _stable_metadata, enforce_package_preservation


class _UnseekableBuffer(io.BytesIO):
    def seekable(self) -> bool:
        return False

    def seek(self, *args, **kwargs):
        raise io.UnsupportedOperation("seek")


def _package(*, streaming: bool = False) -> bytes:
    output = _UnseekableBuffer() if streaming else io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        archive.comment = b"package-note"
        for name, payload in (
            ("[Content_Types].xml", b"types"),
            ("ppt/presentation.xml", b"presentation"),
            ("ppt/slides/slide1.xml", b"before"),
        ):
            info = zipfile.ZipInfo(name, date_time=(2026, 7, 14, 1, 2, 4))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    return output.getvalue()


def _rewrite(
    source: bytes,
    *,
    replacements: dict[str, bytes] | None = None,
    metadata_drift_part: str | None = None,
    reverse_order: bool = False,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source), mode="r") as original:
        entries = [(info, original.read(info)) for info in original.infolist()]
        if reverse_order:
            entries.reverse()
        with zipfile.ZipFile(output, mode="w") as result:
            result.comment = original.comment
            for original_info, payload in entries:
                info = copy.copy(original_info)
                if info.filename == metadata_drift_part:
                    info.date_time = (2026, 7, 14, 1, 2, 6)
                result.writestr(
                    info,
                    (replacements or {}).get(info.filename, payload),
                )
    return output.getvalue()


def test_enforce_package_preservation_allows_only_declared_payload_changes() -> None:
    source = _package()
    result = _rewrite(
        source,
        replacements={"ppt/slides/slide1.xml": b"after"},
    )

    enforce_package_preservation(
        source,
        result,
        changed_parts={"ppt/slides/slide1.xml"},
        label="PPTX",
    )

    with pytest.raises(
        OfficePackageError,
        match="changed an unapproved package part",
    ):
        enforce_package_preservation(
            source,
            result,
            changed_parts=set(),
            label="PPTX",
        )


def test_enforce_package_preservation_accepts_data_descriptor_repacking() -> None:
    source = _package(streaming=True)
    result = _rewrite(source)

    enforce_package_preservation(
        source,
        result,
        changed_parts=set(),
        label="PPTX",
    )


def test_stable_metadata_accepts_powerpoint_deflate_repacking() -> None:
    powerpoint = zipfile.ZipInfo("ppt/slides/slide1.xml")
    powerpoint.compress_type = zipfile.ZIP_DEFLATED
    powerpoint.create_system = 0
    powerpoint.flag_bits = 0x06
    powerpoint.external_attr = 0

    python_repacked = copy.copy(powerpoint)
    python_repacked.flag_bits = 0
    python_repacked.external_attr = 0o600 << 16

    assert _stable_metadata(powerpoint) == _stable_metadata(python_repacked)


def test_stable_metadata_keeps_meaningful_zip_flags_and_dos_attributes() -> None:
    source = zipfile.ZipInfo("ppt/slides/slide1.xml")
    source.compress_type = zipfile.ZIP_DEFLATED
    source.create_system = 0

    encrypted = copy.copy(source)
    encrypted.flag_bits = 0x01
    assert _stable_metadata(source) != _stable_metadata(encrypted)

    read_only = copy.copy(source)
    read_only.external_attr = 0x01
    assert _stable_metadata(source) != _stable_metadata(read_only)


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (
            lambda source: _rewrite(
                source,
                metadata_drift_part="ppt/presentation.xml",
            ),
            "changed ZIP metadata",
        ),
        (
            lambda source: _rewrite(source, reverse_order=True),
            "relative package entry order",
        ),
    ],
)
def test_enforce_package_preservation_rejects_container_drift(
    result,
    message: str,
) -> None:
    source = _package()

    with pytest.raises(OfficePackageError, match=message):
        enforce_package_preservation(
            source,
            result(source),
            changed_parts=set(),
            label="PPTX",
        )

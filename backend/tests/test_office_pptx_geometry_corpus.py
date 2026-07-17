from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest

from scripts.build_pptx_geometry_seed import build_geometry_image, build_geometry_seed
from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.pptx import inspect_pptx, validate_pptx

_CORPUS_DIR = Path(__file__).parent / "fixtures" / "office" / "pptx" / "geometry"
_APP_PROPERTIES_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((_CORPUS_DIR / name).read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _package_application(data: bytes) -> tuple[str | None, str | None]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("docProps/app.xml"))
    namespace = f"{{{_APP_PROPERTIES_NAMESPACE}}}"
    return (
        root.findtext(f"{namespace}Application"),
        root.findtext(f"{namespace}AppVersion"),
    )


def _assert_numeric_mapping(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    assert actual.keys() >= expected.keys()
    for key, value in expected.items():
        assert actual[key] == pytest.approx(value, abs=0.001)


def _assert_geometry_contract(
    data: bytes,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    validation = validate_pptx(data)
    assert validation["valid"] is True
    assert validation["risky_features"] == []
    inspection = inspect_pptx(data, max_slides=10, include_formatting=False)
    contract = manifest["semantic_contract"]
    assert inspection["slide_count"] == contract["slide_count"]
    assert abs(inspection["slide_size"]["width_emu"] - manifest["seed"]["slide_size_emu"]["width"]) <= contract["max_native_width_drift_emu"]
    assert inspection["slide_size"]["height_emu"] == manifest["seed"]["slide_size_emu"]["height"]

    objects = {item["name"]: item for slide in inspection["slides"] for item in slide["objects"]}
    assert len(objects) == contract["object_count"]
    for expected in contract["required_objects"]:
        actual = objects[expected["name"]]
        assert actual["identity_source"] == "cNvPr.id"
        assert actual["path"] == expected["path"]
        assert actual["kind"] == expected["kind"]
        if "alt_text" in expected:
            assert actual["alt_text"] == expected["alt_text"]

    preflight = office_engine.preflight(data, suffix=".pptx")
    assert preflight["source_sha256"] == _sha256(data)
    assert preflight["summary"]["object_count"] == contract["object_count"]
    assert preflight["summary"]["picture_count"] == contract["picture_count"]
    assert preflight["summary"]["findings_truncated"] is False
    assert preflight["image_quality"]["assessments_truncated"] is False
    assert preflight["geometry_quality"]["assessments_truncated"] is False
    images = {item["path"]: item for item in preflight["image_quality"]["assessments"]}
    geometry = {item["path"]: item for item in preflight["geometry_quality"]["assessments"]}
    for expected in contract["picture_measurements"]:
        path = objects[expected["name"]]["path"]
        image = images[path]
        frame = geometry[path]
        assert image["status"] == "measured"
        assert frame["status"] == "measured"
        assert image["group_depth"] == expected["group_depth"]
        assert frame["group_depth"] == expected["group_depth"]
        _assert_numeric_mapping(image["display_inches"], expected["display_inches"])
        _assert_numeric_mapping(image["effective_ppi"], expected["effective_ppi"])
        _assert_numeric_mapping(frame["bounds_emu"], expected["bounds_emu"])
        _assert_numeric_mapping(frame["slide_intersection"], expected["slide_intersection"])

    expected_findings = {code: {objects[name]["path"] for name in names} for code, names in contract["expected_findings"].items()}
    actual_findings = {code: {finding["path"] for finding in preflight["findings"] if finding["code"] == code} for code in expected_findings}
    assert actual_findings == expected_findings
    return inspection, preflight


def test_geometry_corpus_seed_and_preflight_rebuild_byte_exact() -> None:
    manifest = _load_json("manifest.json")
    artifact, image, preflight = build_geometry_seed()
    expected = {
        manifest["seed"]["file"]: artifact,
        manifest["seed"]["asset"]["file"]: build_geometry_image(),
        manifest["seed"]["preflight"]["file"]: (json.dumps(preflight, indent=2, sort_keys=True) + "\n").encode(),
    }
    records = {
        manifest["seed"]["file"]: manifest["seed"],
        manifest["seed"]["asset"]["file"]: manifest["seed"]["asset"],
        manifest["seed"]["preflight"]["file"]: manifest["seed"]["preflight"],
    }
    for name, rebuilt in expected.items():
        stored = (_CORPUS_DIR / name).read_bytes()
        assert rebuilt == stored
        assert _sha256(stored) == records[name]["sha256"]
    assert image == build_geometry_image()
    assert validate_pptx(artifact)["entry_count"] == manifest["seed"]["entry_count"]
    _assert_geometry_contract(artifact, manifest)


def test_geometry_corpus_tracks_verified_native_producers() -> None:
    manifest = _load_json("manifest.json")
    assert manifest["schema_version"] == 1
    assert {lane["producer"] for lane in manifest["lanes"]} == set(manifest["required_producers"])
    seed = (_CORPUS_DIR / manifest["seed"]["file"]).read_bytes()
    seed_hash = _sha256(seed)

    for lane in manifest["lanes"]:
        assert lane["status"] == "verified"
        fixture = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        receipt_payload = (_CORPUS_DIR / lane["receipt"]).read_bytes()
        receipt = json.loads(receipt_payload)
        assert _sha256(fixture) == lane["sha256"]
        assert _sha256(receipt_payload) == lane["receipt_sha256"]
        assert receipt["producer"] == lane["producer"]
        assert receipt["input_file"] == manifest["seed"]["file"]
        assert receipt["input_sha256"] == seed_hash
        assert receipt["output_file"] == lane["fixture"]
        assert receipt["output_sha256"] == lane["sha256"]
        assert _package_application(fixture) == (
            receipt["package_application"],
            receipt["package_app_version"],
        )
        inspection, _ = _assert_geometry_contract(fixture, manifest)
        observation = lane["native_observation"]
        assert validate_pptx(fixture)["entry_count"] == observation["entry_count"]
        assert inspection["slide_size"]["width_emu"] == observation["slide_size_emu"]["width"]
        assert inspection["slide_size"]["height_emu"] == observation["slide_size_emu"]["height"]


def test_geometry_corpus_records_complete_visual_review_evidence() -> None:
    evidence = _load_json("manifest.json")["render_evidence"]
    assert evidence["review_status"] == "passed"
    assert evidence["dpi"] == 120
    assert evidence["renderer"] == "libreoffice-pdfium"
    assert len(evidence["pipeline_fingerprint"]) == 64
    lanes = evidence["lanes"]
    assert set(lanes) == {"seed", "microsoft_powerpoint", "wps_presentation"}
    for pages in lanes.values():
        assert [page["page"] for page in pages] == [1, 2, 3]
        assert all(page["height"] == 900 and len(page["sha256"]) == 64 for page in pages)
    assert lanes["microsoft_powerpoint"] == lanes["seed"]
    assert [page["width"] for page in lanes["wps_presentation"]] == [1600, 1600, 1600]

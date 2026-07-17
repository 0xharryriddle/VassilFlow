from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from scripts.build_pptx_generation_seed import (
    build_generation_image,
    build_generation_seed,
)
from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.generation import validate_generation_evidence
from vassilflow.community.office.models import PptxTextReplacement
from vassilflow.community.office.pptx import edit_pptx, inspect_pptx, validate_pptx

_CORPUS_DIR = Path(__file__).parent / "fixtures" / "office" / "pptx" / "generation"
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


def _object_text(item: dict[str, Any]) -> str | None:
    text_body = item.get("text_body")
    if text_body is None:
        return None
    return "\n".join(paragraph["text"] for paragraph in text_body["paragraphs"])


def _assert_semantic_contract(
    data: bytes,
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    validation = validate_pptx(data)
    assert validation["valid"] is True
    assert validation["risky_features"] == []
    inspected = inspect_pptx(data, max_slides=20, include_formatting=True)
    contract = manifest["semantic_contract"]
    expected_size = contract["slide_size_emu"]
    actual_size = inspected["slide_size"]
    assert (
        abs(actual_size["width_emu"] - expected_size["baseline_width"])
        <= expected_size["max_native_width_drift"]
    )
    assert (
        abs(actual_size["height_emu"] - expected_size["baseline_height"])
        <= expected_size["max_native_height_drift"]
    )
    assert inspected["slide_count"] == contract["slide_count"]

    objects = {
        item["name"]: item
        for slide in inspected["slides"]
        for item in slide["objects"]
    }
    assert len(objects) == contract["object_count"]
    for expected in contract["required_objects"]:
        actual = objects[expected["name"]]
        assert actual["identity_source"] == "cNvPr.id"
        assert actual["path"] == expected["path"]
        assert actual["kind"] == expected["kind"]
        if "text" in expected:
            assert _object_text(actual) == expected["text"]
        if "alt_text" in expected:
            assert actual["alt_text"] == expected["alt_text"]
            assert actual["source"]["relationship_id"]
            assert actual["source"]["sha256"]
    return objects


def test_generation_corpus_seed_and_evidence_rebuild_byte_exact() -> None:
    manifest = _load_json("manifest.json")
    seed = manifest["seed"]
    artifact, intent, receipt, preflight = build_generation_seed()
    expected = {
        seed["file"]: artifact,
        seed["intent"]["file"]: (json.dumps(intent, indent=2, sort_keys=True) + "\n").encode(),
        seed["asset"]["file"]: build_generation_image(),
        seed["generation_receipt"]["file"]: (
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        ).encode(),
        seed["preflight"]["file"]: (
            json.dumps(preflight, indent=2, sort_keys=True) + "\n"
        ).encode(),
    }
    manifest_records = {
        seed["file"]: seed,
        seed["intent"]["file"]: seed["intent"],
        seed["asset"]["file"]: seed["asset"],
        seed["generation_receipt"]["file"]: seed["generation_receipt"],
        seed["preflight"]["file"]: seed["preflight"],
    }
    for name, rebuilt in expected.items():
        stored = (_CORPUS_DIR / name).read_bytes()
        assert rebuilt == stored
        assert _sha256(stored) == manifest_records[name]["sha256"]

    validate_generation_evidence(
        artifact=artifact,
        intent=intent,
        receipt=receipt,
        preflight=preflight,
    )
    _assert_semantic_contract(artifact, manifest)


def test_generation_corpus_tracks_verified_native_producers() -> None:
    manifest = _load_json("manifest.json")
    assert manifest["schema_version"] == 1
    assert manifest["generation_readiness"] == {
        "ready": True,
        "verified_producers": ["microsoft_powerpoint", "wps_presentation"],
        "blocked_by": [],
    }
    assert {lane["producer"] for lane in manifest["lanes"]} == set(
        manifest["required_producers"]
    )

    seed_path = _CORPUS_DIR / manifest["seed"]["file"]
    seed_hash = _sha256(seed_path.read_bytes())
    for lane in manifest["lanes"]:
        assert lane["status"] == "verified"
        fixture_path = _CORPUS_DIR / lane["fixture"]
        receipt = _load_json(lane["receipt"])
        fixture = fixture_path.read_bytes()
        assert receipt["producer"] == lane["producer"]
        assert receipt["input_file"] == seed_path.name
        assert receipt["input_sha256"] == seed_hash
        assert receipt["output_file"] == fixture_path.name
        assert receipt["output_sha256"] == _sha256(fixture)
        assert _package_application(fixture) == (
            receipt["package_application"],
            receipt["package_app_version"],
        )
        if lane["producer"] == "microsoft_powerpoint":
            assert receipt["prog_id"] == "PowerPoint.Application"
            assert receipt["package_application"] == "Microsoft Office PowerPoint"
        else:
            assert receipt["prog_id"].startswith("KWPP.Application")
            assert "WPS" in receipt["package_application"] or "Kingsoft" in receipt["package_application"]

        objects = _assert_semantic_contract(fixture, manifest)
        observation = lane["native_observation"]
        assert validate_pptx(fixture)["entry_count"] == observation["entry_count"]
        slide_size = inspect_pptx(fixture, max_slides=1)["slide_size"]
        assert slide_size["width_emu"] == observation["slide_size_emu"]["width"]
        assert slide_size["height_emu"] == observation["slide_size_emu"]["height"]

        preflight = office_engine.preflight(fixture, suffix=".pptx")
        assert preflight["summary"]["findings_truncated"] is False
        assert preflight["summary"]["findings_by_severity"].get("error", 0) == 0
        image_source = objects["VFGEN:evidence:evidence-image"]["source"]
        assert image_source["part_name"].startswith("ppt/media/")
        assert image_source["content_type"] == "image/png"


def test_generated_native_roundtrips_remain_editable() -> None:
    manifest = _load_json("manifest.json")
    for lane in manifest["lanes"]:
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        objects = _assert_semantic_contract(source, manifest)
        subtitle = objects["VFGEN:opening:opening-subtitle"]
        edited, reports = edit_pptx(
            source,
            [
                PptxTextReplacement(
                    paths=[subtitle["path"]],
                    find="Editable",
                    replace="Revisable",
                )
            ],
        )
        assert reports[0]["match_count"] == 1
        assert validate_pptx(edited)["valid"] is True
        inspected = inspect_pptx(edited, max_slides=1, include_formatting=True)
        edited_subtitle = next(
            item
            for item in inspected["slides"][0]["objects"]
            if item.get("name") == "VFGEN:opening:opening-subtitle"
        )
        assert _object_text(edited_subtitle) == "Revisable objects across native producers"

        with (
            zipfile.ZipFile(io.BytesIO(source)) as before,
            zipfile.ZipFile(io.BytesIO(edited)) as after,
        ):
            changed = [
                name
                for name in before.namelist()
                if before.read(name) != after.read(name)
            ]
        assert changed == ["ppt/slides/slide1.xml"]

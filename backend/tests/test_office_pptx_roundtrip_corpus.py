from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pydantic import TypeAdapter

from scripts.build_pptx_roundtrip_seed import (
    build_image_fill_replacement_jpeg,
    build_image_fill_replacement_png,
    build_seed,
)
from vassilflow.community.office.models import (
    PptxEditOperation,
    PptxGradientRectangleFormatting,
    PptxGradientStopFormatting,
    PptxImageCropFormatting,
    PptxImageTileFormatting,
    PptxLinearGradientFormatting,
    PptxLineEndFormatting,
    PptxLineFormatOperation,
    PptxLineFormatting,
    PptxLineSelector,
    PptxLineTarget,
    PptxParagraphFormatOperation,
    PptxParagraphFormatting,
    PptxParagraphSelector,
    PptxParagraphTarget,
    PptxPathGradientFormatting,
    PptxPictureSelector,
    PptxPictureSourceReplacementOperation,
    PptxPictureTarget,
    PptxPresetGeometryFormatting,
    PptxRunFormatOperation,
    PptxRunFormatting,
    PptxRunSelector,
    PptxRunTarget,
    PptxShapeFillFormatting,
    PptxShapeFormatOperation,
    PptxShapeFormatting,
    PptxShapeLineFormatting,
    PptxShapeSelector,
    PptxShapeTarget,
    PptxSlideBackgroundFormatOperation,
    PptxSlideBackgroundFormatting,
    PptxSlideSelector,
    PptxSlideTarget,
    PptxTextBoxFormatting,
    PptxTextReplacement,
)
from vassilflow.community.office.pptx import edit_pptx, inspect_pptx, validate_pptx

_CORPUS_DIR = Path(__file__).parent / "fixtures" / "office" / "pptx" / "roundtrip"
_APP_PROPERTIES_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"


def _load_manifest() -> dict[str, Any]:
    return json.loads((_CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))


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


def _run_font_slots(data: bytes, part_name: str) -> list[tuple[str, dict[str, str]]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read(part_name))
    slots: list[tuple[str, dict[str, str]]] = []
    for element in root.iter():
        local_name = element.tag.rpartition("}")[2]
        if local_name in {"latin", "ea", "cs"}:
            slots.append((local_name, dict(element.attrib)))
    return slots


def _objects_by_name(inspected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for slide in inspected["slides"]:
        for item in slide["objects"]:
            name = item.get("name")
            if not name or name == "VF_RT_TITLE":
                continue
            if name in objects:
                raise AssertionError(f"Duplicate round-trip shape name: {name}")
            objects[name] = item
    return objects


def _object_text(item: dict[str, Any]) -> str | None:
    text_body = item.get("text_body")
    if text_body is None:
        return None
    return "\n".join(paragraph["text"] for paragraph in text_body["paragraphs"])


def _assert_run(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    assert actual["kind"] == "run"
    assert actual["text"] == expected["text"]
    formatting = actual["formatting"]
    assert formatting["fonts"]["latin"] == expected["font"]
    assert formatting["font_size_points"] == expected["font_size_points"]
    for property_name in ("bold", "italic"):
        if property_name in expected:
            assert formatting[property_name] is expected[property_name]
    if "color" in expected:
        assert formatting["fill"]["color"]["value"] == expected["color"]


def _assert_mapping_subset(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    for key, expected_value in expected.items():
        assert key in actual
        if isinstance(expected_value, dict):
            assert isinstance(actual[key], dict)
            _assert_mapping_subset(actual[key], expected_value)
        else:
            assert actual[key] == expected_value


def _picture_preservation_view(item: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(item)
    result.pop("source", None)
    result["relationship_ids"] = ["__PICTURE_SOURCE__"]
    picture_style = result["style"]["picture"]
    picture_style["relationship_ids"] = ["__PICTURE_SOURCE__"]
    return result


def _assert_object_contract(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    assert actual["identity_source"] == "cNvPr.id"
    assert "[@id=" in actual["path"]
    assert actual["kind"] == expected["kind"]
    if "text" in expected:
        assert _object_text(actual) == expected["text"]
    style = actual.get("style", {})
    text_box = style.get("text_box", {})
    if "vertical_anchor" in expected:
        assert text_box["vertical_anchor"] == expected["vertical_anchor"]
    if "geometry" in expected:
        assert style["geometry"]["preset"] == expected["geometry"]
    if "fill_color" in expected:
        assert style["fill"]["color"]["value"] == expected["fill_color"]
    if "fill" in expected:
        assert style["fill"] == expected["fill"]
    if "image_fill" in expected:
        actual_fill = style["fill"]
        expected_fill = expected["image_fill"]
        for property_name, expected_value in expected_fill.items():
            assert actual_fill[property_name] == expected_value
        assert len(actual_fill["relationship_ids"]) == 1
        assert actual_fill["relationship_ids"][0]
    if "line_color" in expected:
        assert style["line"]["fill"]["color"]["value"] == expected["line_color"]
    if "line_width_emu" in expected:
        assert style["line"]["width_emu"] == expected["line_width_emu"]
    if "margins_emu" in expected:
        assert text_box["margins"] == expected["margins_emu"]
    if "line" in expected:
        line = style["line"]
        expected_line = expected["line"]
        for property_name in ("width_emu", "compound", "alignment", "head_end", "tail_end"):
            if property_name in expected_line:
                assert line[property_name] == expected_line[property_name]
        if "fill_color" in expected_line:
            assert line["fill"]["color"]["value"] == expected_line["fill_color"]
        if "fill" in expected_line:
            assert line["fill"] == expected_line["fill"]
    if "alt_text" in expected:
        assert actual["alt_text"] == expected["alt_text"]
    if "geometry_emu" in expected:
        assert actual["geometry"] == expected["geometry_emu"]
    if "source" in expected:
        _assert_mapping_subset(actual["source"], expected["source"])
    if "picture" in expected:
        _assert_mapping_subset(style["picture"], expected["picture"])
        assert len(style["picture"]["relationship_ids"]) == 1

    expected_paragraphs = expected.get("paragraphs")
    if expected_paragraphs is None:
        return
    actual_paragraphs = actual["text_body"]["paragraphs"]
    assert len(actual_paragraphs) == len(expected_paragraphs)
    for actual_paragraph, expected_paragraph in zip(
        actual_paragraphs,
        expected_paragraphs,
        strict=True,
    ):
        assert actual_paragraph["text"] == expected_paragraph["text"]
        formatting = actual_paragraph["formatting"]
        assert formatting["alignment"] == expected_paragraph["alignment"]
        if "space_after_points" in expected_paragraph:
            assert formatting["space_after"] == {
                "unit": "points",
                "value": expected_paragraph["space_after_points"],
            }
        runs = [segment for segment in actual_paragraph["segments"] if segment["kind"] == "run"]
        expected_runs = expected_paragraph.get("runs")
        if expected_runs is not None:
            assert len(runs) == len(expected_runs)
            for actual_run, expected_run in zip(runs, expected_runs, strict=True):
                _assert_run(actual_run, expected_run)
        elif "font_size_points" in expected_paragraph:
            assert len(runs) == 1
            assert runs[0]["formatting"]["font_size_points"] == expected_paragraph["font_size_points"]


def _assert_background_contract(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    assert actual["path"] == expected["path"]
    assert actual["part_name"] == expected["part_name"]
    background = actual["background"]
    expected_background = expected["background"]
    for property_name, expected_value in expected_background.items():
        assert background[property_name] == expected_value
    if expected_background["type"] == "image":
        assert len(background["relationship_ids"]) == 1
        assert background["relationship_ids"][0]


def _assert_semantic_contract(data: bytes, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validation = validate_pptx(data)
    assert validation["valid"] is True
    assert validation["risky_features"] == []
    inspected = inspect_pptx(
        data,
        max_slides=20,
        include_formatting=True,
    )
    contract = manifest["semantic_contract"]
    expected_size = contract["slide_size_emu"]
    actual_size = inspected["slide_size"]
    assert abs(actual_size["width_emu"] - expected_size["baseline_width"]) <= expected_size["max_native_width_drift"]
    assert abs(actual_size["height_emu"] - expected_size["baseline_height"]) <= expected_size["max_native_height_drift"]
    assert inspected["slide_count"] == contract["slide_count"]
    assert sum(len(slide["objects"]) for slide in inspected["slides"]) == contract["object_count"]
    slides = {slide["path"]: slide for slide in inspected["slides"]}
    for expected in contract["required_backgrounds"]:
        _assert_background_contract(slides[expected["path"]], expected)
    objects = _objects_by_name(inspected)
    for expected in contract["required_objects"]:
        _assert_object_contract(objects[expected["name"]], expected)
    return objects


def test_pptx_native_roundtrip_manifest_tracks_required_producers() -> None:
    manifest = _load_manifest()
    assert manifest["schema_version"] == 1
    required = set(manifest["required_producers"])
    lanes = {lane["producer"]: lane for lane in manifest["lanes"]}
    assert required == {"microsoft_powerpoint", "wps_presentation"}
    assert set(lanes) == required

    verified = {producer for producer, lane in lanes.items() if lane["status"] == "verified"}
    blocked = required - verified
    readiness = manifest["formatting_readiness"]
    assert readiness["ready"] is (not blocked)
    assert set(readiness["verified_producers"]) == verified
    assert set(readiness["blocked_by"]) == blocked

    for producer in blocked:
        lane = lanes[producer]
        assert lane["status"] == "pending"
        assert lane["fixture"] is None
        assert lane["receipt"] is None
        assert lane["blocker_code"] == "native_application_unavailable"


def test_pptx_native_roundtrip_seed_and_verified_lanes_match_manifest() -> None:
    manifest = _load_manifest()
    seed_path = _CORPUS_DIR / manifest["seed"]["file"]
    seed = seed_path.read_bytes()
    assert _sha256(seed) == manifest["seed"]["sha256"]
    _assert_semantic_contract(seed, manifest)

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        fixture_path = _CORPUS_DIR / lane["fixture"]
        receipt_path = _CORPUS_DIR / lane["receipt"]
        assert fixture_path.parent == _CORPUS_DIR
        assert receipt_path.parent == _CORPUS_DIR
        fixture = fixture_path.read_bytes()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["schema_version"] == 1
        assert receipt["producer"] == lane["producer"]
        assert receipt["input_file"] == seed_path.name
        assert receipt["input_sha256"] == _sha256(seed)
        assert receipt["output_file"] == fixture_path.name
        assert receipt["output_sha256"] == _sha256(fixture)
        assert _package_application(fixture) == (
            receipt["package_application"],
            receipt["package_app_version"],
        )
        if lane["producer"] == "microsoft_powerpoint":
            assert receipt["prog_id"] == "PowerPoint.Application"
            assert receipt["package_application"] == "Microsoft Office PowerPoint"
        elif lane["producer"] == "wps_presentation":
            assert receipt["prog_id"].startswith("KWPP.Application")
            assert "WPS" in receipt["package_application"] or "Kingsoft" in receipt["package_application"]
        _assert_semantic_contract(fixture, manifest)
        observation = lane["native_observation"]
        assert validate_pptx(fixture)["entry_count"] == observation["entry_count"]
        slide_size = inspect_pptx(fixture, max_slides=1)["slide_size"]
        assert slide_size["width_emu"] == observation["slide_size_emu"]["width"]
        assert slide_size["height_emu"] == observation["slide_size_emu"]["height"]


def test_pptx_native_roundtrip_seed_rebuilds_byte_exact() -> None:
    manifest = _load_manifest()
    expected = (_CORPUS_DIR / manifest["seed"]["file"]).read_bytes()
    assert build_seed() == expected


def test_verified_native_roundtrip_fixtures_remain_editable() -> None:
    manifest = _load_manifest()
    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        objects = _assert_semantic_contract(source, manifest)
        sentinel = objects["VF_RT_EDIT_SENTINEL"]
        edited, reports = edit_pptx(
            source,
            [
                PptxTextReplacement(
                    paths=[sentinel["path"]],
                    find="Final",
                    replace="Ready",
                )
            ],
        )
        assert reports[0]["match_count"] == 1
        assert validate_pptx(edited)["valid"] is True
        with (
            zipfile.ZipFile(io.BytesIO(source)) as before,
            zipfile.ZipFile(io.BytesIO(edited)) as after,
        ):
            assert before.namelist() == after.namelist()
            changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed == ["ppt/slides/slide1.xml"]


def test_verified_native_roundtrip_fixtures_support_typed_formatting() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        split_run = before["VF_RT_SPLIT_RUN"]
        paragraphs = before["VF_RT_PARAGRAPHS"]
        run = split_run["text_body"]["paragraphs"][0]["segments"][0]
        metadata_run = split_run["text_body"]["paragraphs"][0]["segments"][1]
        paragraph = paragraphs["text_body"]["paragraphs"][1]

        edited, reports = edit_pptx(
            source,
            [
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path=run["path"],
                                expected_text=run["text"],
                            )
                        ]
                    ),
                    formatting=PptxRunFormatting(
                        bold=False,
                        italic=True,
                        color="#1F4E79",
                        font_latin=run["formatting"]["fonts"]["latin"],
                        font_size=26,
                    ),
                ),
                PptxParagraphFormatOperation(
                    paragraphs=PptxParagraphSelector(
                        targets=[
                            PptxParagraphTarget(
                                path=paragraph["path"],
                                expected_text=paragraph["text"],
                            )
                        ]
                    ),
                    formatting=PptxParagraphFormatting(
                        alignment="justify",
                        space_before=4,
                        space_after=10,
                        line_spacing_percent=120,
                    ),
                ),
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path=metadata_run["path"],
                                expected_text=metadata_run["text"],
                            )
                        ]
                    ),
                    formatting=PptxRunFormatting(
                        font_latin=metadata_run["formatting"]["fonts"]["latin"],
                    ),
                ),
            ],
        )

        assert [report["type"] for report in reports] == [
            "format_pptx_runs",
            "format_pptx_paragraphs",
            "format_pptx_runs",
        ]
        assert [report["match_count"] for report in reports] == [1, 1, 1]
        assert validate_pptx(edited)["valid"] is True
        inspected = inspect_pptx(
            edited,
            max_slides=20,
            include_formatting=True,
        )
        after = _objects_by_name(inspected)

        for name in before.keys() - {"VF_RT_SPLIT_RUN", "VF_RT_PARAGRAPHS"}:
            assert after[name] == before[name]
        after_run = after["VF_RT_SPLIT_RUN"]["text_body"]["paragraphs"][0]["segments"][0]
        assert after_run["text"] == run["text"]
        assert after_run["formatting"]["fonts"] == run["formatting"]["fonts"]
        assert after_run["formatting"]["font_size_points"] == 26
        assert after_run["formatting"]["bold"] is False
        assert after_run["formatting"]["italic"] is True
        assert after_run["formatting"]["fill"]["color"]["value"] == "#1F4E79"
        assert after["VF_RT_SPLIT_RUN"]["text_body"]["paragraphs"][0]["segments"][1:] == split_run["text_body"]["paragraphs"][0]["segments"][1:]
        after_paragraphs = after["VF_RT_PARAGRAPHS"]["text_body"]["paragraphs"]
        assert after_paragraphs[0] == paragraphs["text_body"]["paragraphs"][0]
        assert after_paragraphs[2] == paragraphs["text_body"]["paragraphs"][2]
        assert after_paragraphs[1]["text"] == paragraph["text"]
        assert after_paragraphs[1]["segments"] == paragraph["segments"]
        assert after_paragraphs[1]["formatting"] == {
            "alignment": "justify",
            "line_spacing": {"unit": "percent", "value": 120.0},
            "space_before": {"unit": "points", "value": 4.0},
            "space_after": {"unit": "points", "value": 10.0},
        }
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            changed = [name for name in source_archive.namelist() if source_archive.read(name) != edited_archive.read(name)]
        assert changed == ["ppt/slides/slide1.xml"]
        assert _run_font_slots(
            edited,
            "ppt/slides/slide1.xml",
        ) == _run_font_slots(
            source,
            "ppt/slides/slide1.xml",
        )


def test_verified_native_roundtrip_fixtures_support_typed_shape_formatting() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        style_shape = before["VF_RT_STYLE"]
        margin_shape = before["VF_RT_MARGINS"]

        edited, reports = edit_pptx(
            source,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path=style_shape["path"],
                                expected_name=style_shape["name"],
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(
                        fill=PptxShapeFillFormatting(type="solid", color="#5B9BD5"),
                        line=PptxShapeLineFormatting(
                            fill=PptxShapeFillFormatting(type="solid", color="#A5A5A5"),
                            width_points=4.25,
                            cap="square",
                            dash="large_dash",
                            join="miter",
                            miter_limit_percent=800,
                        ),
                    ),
                ),
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path=margin_shape["path"],
                                expected_name=margin_shape["name"],
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(
                        text_box=PptxTextBoxFormatting(
                            margin_left=30,
                            margin_top=18,
                            margin_right=12,
                            margin_bottom=6,
                            vertical_anchor="top",
                        )
                    ),
                ),
            ],
        )

        assert [report["type"] for report in reports] == [
            "format_pptx_shapes",
            "format_pptx_shapes",
        ]
        assert [report["match_count"] for report in reports] == [1, 1]
        assert validate_pptx(edited)["valid"] is True
        after = _objects_by_name(
            inspect_pptx(
                edited,
                max_slides=20,
                include_formatting=True,
            )
        )

        for name in before.keys() - {"VF_RT_STYLE", "VF_RT_MARGINS"}:
            assert after[name] == before[name]
        assert after["VF_RT_STYLE"]["text_body"] == style_shape["text_body"]
        assert after["VF_RT_STYLE"]["style"]["geometry"] == style_shape["style"]["geometry"]
        assert after["VF_RT_STYLE"]["style"]["fill"] == {
            "type": "solid",
            "color": {"type": "rgb", "value": "#5B9BD5"},
        }
        assert after["VF_RT_STYLE"]["style"]["line"] == {
            "width_emu": 53_975,
            "cap": "square",
            "fill": {
                "type": "solid",
                "color": {"type": "rgb", "value": "#A5A5A5"},
            },
            "dash": "large_dash",
            "join": "miter",
            "miter_limit_percent": 800.0,
        }
        assert after["VF_RT_MARGINS"]["text_body"] == margin_shape["text_body"]
        expected_text_box = dict(margin_shape["style"]["text_box"])
        expected_text_box.update(
            {
                "margins": {
                    "left_emu": 381_000,
                    "top_emu": 228_600,
                    "right_emu": 152_400,
                    "bottom_emu": 76_200,
                },
                "vertical_anchor": "top",
            }
        )
        assert after["VF_RT_MARGINS"]["style"]["text_box"] == expected_text_box
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            changed = [name for name in source_archive.namelist() if source_archive.read(name) != edited_archive.read(name)]
        assert changed == ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml"]


def test_verified_native_roundtrip_fixtures_support_typed_connector_line_formatting() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        connector = before["VF_RT_CONNECTOR"]

        edited, reports = edit_pptx(
            source,
            [
                PptxLineFormatOperation(
                    lines=PptxLineSelector(
                        targets=[
                            PptxLineTarget(
                                path=connector["path"],
                                expected_name=connector["name"],
                            )
                        ]
                    ),
                    formatting=PptxLineFormatting(
                        cap="square",
                        dash="large_dash",
                        join="miter",
                        miter_limit_percent=800,
                        compound="triple",
                        alignment="inset",
                        head_end=PptxLineEndFormatting(
                            type="stealth",
                            width="large",
                            length="small",
                        ),
                        tail_end=PptxLineEndFormatting(
                            type="oval",
                            width="medium",
                            length="large",
                        ),
                    ),
                )
            ],
        )

        assert reports == [
            {
                "operation": 1,
                "type": "format_pptx_lines",
                "match_count": 1,
                "matched_paths": [connector["path"]],
                "matched_paths_truncated": False,
            }
        ]
        assert validate_pptx(edited)["valid"] is True
        after = _objects_by_name(
            inspect_pptx(
                edited,
                max_slides=20,
                include_formatting=True,
            )
        )
        for name in before.keys() - {"VF_RT_CONNECTOR"}:
            assert after[name] == before[name]
        assert after["VF_RT_CONNECTOR"]["geometry"] == connector["geometry"]
        assert after["VF_RT_CONNECTOR"]["style"]["geometry"] == connector["style"]["geometry"]
        assert after["VF_RT_CONNECTOR"]["style"]["line"] == {
            "width_emu": 38_100,
            "cap": "square",
            "compound": "triple",
            "alignment": "inset",
            "fill": {
                "type": "solid",
                "color": {"type": "rgb", "value": "#4472C4"},
            },
            "dash": "large_dash",
            "join": "miter",
            "miter_limit_percent": 800.0,
            "head_end": {
                "type": "stealth",
                "width": "large",
                "length": "small",
            },
            "tail_end": {
                "type": "oval",
                "width": "medium",
                "length": "large",
            },
        }
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            changed = [name for name in source_archive.namelist() if source_archive.read(name) != edited_archive.read(name)]
        assert changed == ["ppt/slides/slide2.xml"]


def test_verified_native_roundtrip_fixtures_support_typed_gradient_formatting() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        shape = before["VF_RT_GRADIENT"]
        connector = before["VF_RT_GRADIENT_CONNECTOR"]
        shape_fill = PptxShapeFillFormatting(
            type="gradient",
            stops=[
                PptxGradientStopFormatting(
                    position_percent=0,
                    color="#7F6000",
                ),
                PptxGradientStopFormatting(
                    position_percent=42.5,
                    color="#ED7D31",
                    opacity_percent=70,
                ),
                PptxGradientStopFormatting(
                    position_percent=100,
                    color="#A5A5A5",
                ),
            ],
            geometry=PptxLinearGradientFormatting(
                angle_degrees=125,
                scaled=False,
            ),
            rotate_with_shape=False,
        )
        line_fill = PptxShapeFillFormatting(
            type="gradient",
            stops=[
                PptxGradientStopFormatting(
                    position_percent=0,
                    color="#5B9BD5",
                ),
                PptxGradientStopFormatting(
                    position_percent=30,
                    color="#ED7D31",
                ),
                PptxGradientStopFormatting(
                    position_percent=100,
                    color="#7030A0",
                ),
            ],
            geometry=PptxLinearGradientFormatting(
                angle_degrees=180,
                scaled=True,
            ),
            rotate_with_shape=True,
        )

        edited, reports = edit_pptx(
            source,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path=shape["path"],
                                expected_name=shape["name"],
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(fill=shape_fill),
                ),
                PptxLineFormatOperation(
                    lines=PptxLineSelector(
                        targets=[
                            PptxLineTarget(
                                path=connector["path"],
                                expected_name=connector["name"],
                            )
                        ]
                    ),
                    formatting=PptxLineFormatting(fill=line_fill),
                ),
            ],
        )

        assert [report["type"] for report in reports] == [
            "format_pptx_shapes",
            "format_pptx_lines",
        ]
        assert validate_pptx(edited)["valid"] is True
        after = _objects_by_name(
            inspect_pptx(
                edited,
                max_slides=20,
                include_formatting=True,
            )
        )
        for name in before.keys() - {
            "VF_RT_GRADIENT",
            "VF_RT_GRADIENT_CONNECTOR",
        }:
            assert after[name] == before[name]
        assert after["VF_RT_GRADIENT"]["text_body"] == shape["text_body"]
        assert after["VF_RT_GRADIENT"]["geometry"] == shape["geometry"]
        assert after["VF_RT_GRADIENT"]["style"]["geometry"] == shape["style"]["geometry"]
        assert after["VF_RT_GRADIENT"]["style"]["line"] == shape["style"]["line"]
        assert after["VF_RT_GRADIENT"]["style"]["fill"] == {
            "type": "gradient",
            "rotate_with_shape": False,
            "stops": [
                {
                    "position_percent": 0.0,
                    "color": {"type": "rgb", "value": "#7F6000"},
                },
                {
                    "position_percent": 42.5,
                    "color": {
                        "type": "rgb",
                        "value": "#ED7D31",
                        "opacity_percent": 70.0,
                    },
                },
                {
                    "position_percent": 100.0,
                    "color": {"type": "rgb", "value": "#A5A5A5"},
                },
            ],
            "geometry": "linear",
            "angle_degrees": 125.0,
            "scaled": False,
        }
        assert after["VF_RT_GRADIENT_CONNECTOR"]["geometry"] == connector["geometry"]
        expected_line = dict(connector["style"]["line"])
        expected_line["fill"] = {
            "type": "gradient",
            "rotate_with_shape": True,
            "stops": [
                {
                    "position_percent": 0.0,
                    "color": {"type": "rgb", "value": "#5B9BD5"},
                },
                {
                    "position_percent": 30.0,
                    "color": {"type": "rgb", "value": "#ED7D31"},
                },
                {
                    "position_percent": 100.0,
                    "color": {"type": "rgb", "value": "#7030A0"},
                },
            ],
            "geometry": "linear",
            "angle_degrees": 180.0,
            "scaled": True,
        }
        assert after["VF_RT_GRADIENT_CONNECTOR"]["style"]["line"] == expected_line
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            changed = [name for name in source_archive.namelist() if source_archive.read(name) != edited_archive.read(name)]
        assert changed == ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml"]


def test_verified_native_roundtrip_fixtures_support_radial_gradient_and_preset_geometry() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        radial_shape = before["VF_RT_PATH_GRADIENT"]
        geometry_shape = before["VF_RT_PRESET_GEOMETRY"]

        edited, reports = edit_pptx(
            source,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path=radial_shape["path"],
                                expected_name=radial_shape["name"],
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(
                        fill=PptxShapeFillFormatting(
                            type="gradient",
                            stops=[
                                PptxGradientStopFormatting(
                                    position_percent=0,
                                    color="#FFF2CC",
                                ),
                                PptxGradientStopFormatting(
                                    position_percent=45,
                                    color="#ED7D31",
                                    opacity_percent=80,
                                ),
                                PptxGradientStopFormatting(
                                    position_percent=100,
                                    color="#7F6000",
                                ),
                            ],
                            geometry=PptxPathGradientFormatting(
                                fill_to_rectangle=PptxGradientRectangleFormatting(
                                    left_percent=20,
                                    top_percent=40,
                                    right_percent=80,
                                    bottom_percent=60,
                                )
                            ),
                            rotate_with_shape=True,
                        )
                    ),
                ),
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path=geometry_shape["path"],
                                expected_name=geometry_shape["name"],
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(geometry=PptxPresetGeometryFormatting(preset="hexagon")),
                ),
            ],
        )

        assert [report["type"] for report in reports] == [
            "format_pptx_shapes",
            "format_pptx_shapes",
        ]
        assert validate_pptx(edited)["valid"] is True
        after = _objects_by_name(
            inspect_pptx(
                edited,
                max_slides=20,
                include_formatting=True,
            )
        )
        for name in before.keys() - {
            "VF_RT_PATH_GRADIENT",
            "VF_RT_PRESET_GEOMETRY",
        }:
            assert after[name] == before[name]
        assert after["VF_RT_PATH_GRADIENT"]["text_body"] == radial_shape["text_body"]
        assert after["VF_RT_PATH_GRADIENT"]["geometry"] == radial_shape["geometry"]
        assert after["VF_RT_PATH_GRADIENT"]["style"]["geometry"] == radial_shape["style"]["geometry"]
        assert after["VF_RT_PATH_GRADIENT"]["style"]["line"] == radial_shape["style"]["line"]
        assert after["VF_RT_PATH_GRADIENT"]["style"]["fill"] == {
            "type": "gradient",
            "rotate_with_shape": True,
            "stops": [
                {
                    "position_percent": 0.0,
                    "color": {"type": "rgb", "value": "#FFF2CC"},
                },
                {
                    "position_percent": 45.0,
                    "color": {
                        "type": "rgb",
                        "value": "#ED7D31",
                        "opacity_percent": 80.0,
                    },
                },
                {
                    "position_percent": 100.0,
                    "color": {"type": "rgb", "value": "#7F6000"},
                },
            ],
            "geometry": "path",
            "path": "circle",
            "fill_to_rectangle": {
                "left_percent": 20.0,
                "top_percent": 40.0,
                "right_percent": 80.0,
                "bottom_percent": 60.0,
            },
        }
        assert after["VF_RT_PRESET_GEOMETRY"]["geometry"] == geometry_shape["geometry"]
        expected_style = dict(geometry_shape["style"])
        expected_style["geometry"] = {"type": "preset", "preset": "hexagon"}
        assert after["VF_RT_PRESET_GEOMETRY"]["style"] == expected_style
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            changed = [name for name in source_archive.namelist() if source_archive.read(name) != edited_archive.read(name)]
        assert changed == ["ppt/slides/slide3.xml"]


def test_verified_native_roundtrip_fixtures_support_direct_rgb_pattern_fill() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        pattern_shape = before["VF_RT_PATTERN_FILL"]

        edited, reports = edit_pptx(
            source,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path=pattern_shape["path"],
                                expected_name=pattern_shape["name"],
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(
                        fill=PptxShapeFillFormatting(
                            type="pattern",
                            preset="weave",
                            foreground_color="#C00000",
                            background_color="#FFF2CC",
                        )
                    ),
                )
            ],
        )

        assert reports[0]["type"] == "format_pptx_shapes"
        assert reports[0]["match_count"] == 1
        assert validate_pptx(edited)["valid"] is True
        after = _objects_by_name(
            inspect_pptx(
                edited,
                max_slides=20,
                include_formatting=True,
            )
        )
        for name in before.keys() - {"VF_RT_PATTERN_FILL"}:
            assert after[name] == before[name]
        assert after["VF_RT_PATTERN_FILL"]["text_body"] == pattern_shape["text_body"]
        assert after["VF_RT_PATTERN_FILL"]["geometry"] == pattern_shape["geometry"]
        assert after["VF_RT_PATTERN_FILL"]["style"]["geometry"] == pattern_shape["style"]["geometry"]
        assert after["VF_RT_PATTERN_FILL"]["style"]["line"] == pattern_shape["style"]["line"]
        assert after["VF_RT_PATTERN_FILL"]["style"]["fill"] == {
            "type": "pattern",
            "preset": "weave",
            "foreground_color": {"type": "rgb", "value": "#C00000"},
            "background_color": {"type": "rgb", "value": "#FFF2CC"},
        }
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            changed = [name for name in source_archive.namelist() if source_archive.read(name) != edited_archive.read(name)]
        assert changed == ["ppt/slides/slide4.xml"]


def test_verified_native_roundtrip_fixtures_support_embedded_png_shape_fill() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True
    image_path = "/mnt/user-data/uploads/image-fill-replacement-v1.png"
    image = build_image_fill_replacement_png()

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        image_shape = before["VF_RT_IMAGE_FILL"]
        operation = PptxShapeFormatOperation(
            shapes=PptxShapeSelector(
                targets=[
                    PptxShapeTarget(
                        path=image_shape["path"],
                        expected_name=image_shape["name"],
                    )
                ]
            ),
            formatting=PptxShapeFormatting(
                fill=PptxShapeFillFormatting(
                    type="image",
                    image_path=image_path,
                    rotate_with_shape=True,
                    crop=PptxImageCropFormatting(
                        left_percent=5,
                        top_percent=12.5,
                        right_percent=15,
                        bottom_percent=7.5,
                    ),
                )
            ),
        )

        edited, reports = edit_pptx(
            source,
            [operation],
            image_assets={image_path: image},
        )

        assert reports[0]["type"] == "format_pptx_shapes"
        assert reports[0]["match_count"] == 1
        assert validate_pptx(edited)["valid"] is True
        after = _objects_by_name(
            inspect_pptx(
                edited,
                max_slides=20,
                include_formatting=True,
            )
        )
        for name in before.keys() - {"VF_RT_IMAGE_FILL"}:
            assert after[name] == before[name]
        assert after["VF_RT_IMAGE_FILL"]["text_body"] == image_shape["text_body"]
        assert after["VF_RT_IMAGE_FILL"]["geometry"] == image_shape["geometry"]
        assert after["VF_RT_IMAGE_FILL"]["style"]["geometry"] == image_shape["style"]["geometry"]
        assert after["VF_RT_IMAGE_FILL"]["style"]["line"] == image_shape["style"]["line"]
        actual_fill = after["VF_RT_IMAGE_FILL"]["style"]["fill"]
        assert {key: value for key, value in actual_fill.items() if key != "relationship_ids"} == {
            "type": "image",
            "rotate_with_shape": True,
            "crop": {
                "left_percent": 5.0,
                "top_percent": 12.5,
                "right_percent": 15.0,
                "bottom_percent": 7.5,
            },
            "fill_mode": "stretch",
            "fill_rectangle": {},
        }
        assert len(actual_fill["relationship_ids"]) == 1
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            source_names = set(source_archive.namelist())
            edited_names = set(edited_archive.namelist())
            added = edited_names - source_names
            assert added == {"ppt/media/image10.png"}
            assert edited_archive.read("ppt/media/image10.png") == image
            changed = sorted(name for name in source_names & edited_names if source_archive.read(name) != edited_archive.read(name))
        assert changed == [
            "ppt/slides/_rels/slide5.xml.rels",
            "ppt/slides/slide5.xml",
        ]

        no_op, _ = edit_pptx(
            edited,
            [operation],
            image_assets={image_path: image},
        )
        assert no_op == edited


def test_verified_native_roundtrip_fixtures_support_embedded_baseline_jpeg_shape_fill() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True
    image_path = "/mnt/user-data/uploads/image-fill-replacement-v1.jpeg"
    image = build_image_fill_replacement_jpeg()

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        image_shape = before["VF_RT_JPEG_FILL"]
        operation = PptxShapeFormatOperation(
            shapes=PptxShapeSelector(
                targets=[
                    PptxShapeTarget(
                        path=image_shape["path"],
                        expected_name=image_shape["name"],
                    )
                ]
            ),
            formatting=PptxShapeFormatting(
                fill=PptxShapeFillFormatting(
                    type="image",
                    image_path=image_path,
                    rotate_with_shape=False,
                    crop=PptxImageCropFormatting(
                        left_percent=8,
                        top_percent=6,
                        right_percent=4,
                        bottom_percent=11,
                    ),
                )
            ),
        )

        edited, reports = edit_pptx(
            source,
            [operation],
            image_assets={image_path: image},
        )

        assert reports[0]["type"] == "format_pptx_shapes"
        assert reports[0]["match_count"] == 1
        assert validate_pptx(edited)["valid"] is True
        inspected = inspect_pptx(
            edited,
            max_slides=20,
            include_formatting=True,
        )
        after = _objects_by_name(inspected)
        for name in before.keys() - {"VF_RT_JPEG_FILL"}:
            assert after[name] == before[name]
        assert after["VF_RT_JPEG_FILL"]["text_body"] == image_shape["text_body"]
        assert after["VF_RT_JPEG_FILL"]["geometry"] == image_shape["geometry"]
        assert after["VF_RT_JPEG_FILL"]["style"]["geometry"] == image_shape["style"]["geometry"]
        assert after["VF_RT_JPEG_FILL"]["style"]["line"] == image_shape["style"]["line"]
        actual_fill = after["VF_RT_JPEG_FILL"]["style"]["fill"]
        assert {key: value for key, value in actual_fill.items() if key != "relationship_ids"} == {
            "type": "image",
            "rotate_with_shape": False,
            "crop": {
                "left_percent": 8.0,
                "top_percent": 6.0,
                "right_percent": 4.0,
                "bottom_percent": 11.0,
            },
            "fill_mode": "stretch",
            "fill_rectangle": {},
        }
        assert len(actual_fill["relationship_ids"]) == 1
        jpeg_assets = [part for part in inspected["image_asset_inventory"]["parts"] if part["part_name"].startswith("ppt/media/") and part["content_type"] == "image/jpeg"]
        assert len(jpeg_assets) == 4
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            source_names = set(source_archive.namelist())
            edited_names = set(edited_archive.namelist())
            assert edited_names - source_names == {"ppt/media/image10.jpg"}
            assert edited_archive.read("ppt/media/image10.jpg") == image
            changed = sorted(name for name in source_names & edited_names if source_archive.read(name) != edited_archive.read(name))
        expected_changed = [
            "ppt/slides/_rels/slide6.xml.rels",
            "ppt/slides/slide6.xml",
        ]
        if lane["producer"] == "wps_presentation":
            expected_changed.insert(0, "[Content_Types].xml")
        assert changed == expected_changed

        no_op, _ = edit_pptx(
            edited,
            [operation],
            image_assets={image_path: image},
        )
        assert no_op == edited


def test_verified_native_roundtrip_fixtures_support_typed_tile_and_center_framing() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True
    tile_path = "/mnt/user-data/uploads/native-tile.png"
    center_path = "/mnt/user-data/uploads/native-center.png"

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            image_assets = {
                tile_path: archive.read("ppt/media/image3.png"),
                center_path: archive.read("ppt/media/image4.png"),
            }
        tile_shape = before["VF_RT_IMAGE_TILE"]
        center_shape = before["VF_RT_IMAGE_CENTER"]
        operations = [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path=tile_shape["path"],
                            expected_name=tile_shape["name"],
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=PptxShapeFillFormatting(
                        type="image",
                        image_path=tile_path,
                        rotate_with_shape=True,
                        mode="tile",
                        tile=PptxImageTileFormatting(
                            offset_x_emu=-254_000,
                            offset_y_emu=190_500,
                            scale_x_percent=72.5,
                            scale_y_percent=38.25,
                            alignment="top_left",
                            flip="both",
                        ),
                    )
                ),
            ),
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path=center_shape["path"],
                            expected_name=center_shape["name"],
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=PptxShapeFillFormatting(
                        type="image",
                        image_path=center_path,
                        rotate_with_shape=False,
                        mode="center",
                    )
                ),
            ),
        ]

        edited, reports = edit_pptx(
            source,
            operations,
            image_assets=image_assets,
        )

        assert [report["match_count"] for report in reports] == [1, 1]
        assert validate_pptx(edited)["valid"] is True
        after = _objects_by_name(
            inspect_pptx(
                edited,
                max_slides=20,
                include_formatting=True,
            )
        )
        for name in before.keys() - {"VF_RT_IMAGE_TILE", "VF_RT_IMAGE_CENTER"}:
            assert after[name] == before[name]
        assert after["VF_RT_IMAGE_TILE"]["style"]["fill"] == {
            "type": "image",
            "rotate_with_shape": True,
            "fill_mode": "tile",
            "tile": {
                "offset_x_emu": -254_000,
                "offset_y_emu": 190_500,
                "scale_x_percent": 72.5,
                "scale_y_percent": 38.25,
                "alignment": "top_left",
                "flip": "both",
            },
            "relationship_ids": [tile_shape["style"]["fill"]["relationship_ids"][0]],
        }
        assert after["VF_RT_IMAGE_CENTER"]["style"]["fill"] == {
            "type": "image",
            "rotate_with_shape": False,
            "fill_mode": "center",
            "relationship_ids": [center_shape["style"]["fill"]["relationship_ids"][0]],
        }
        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            assert source_archive.namelist() == edited_archive.namelist()
            changed = [name for name in source_archive.namelist() if source_archive.read(name) != edited_archive.read(name)]
        assert changed == ["ppt/slides/slide7.xml"]

        no_op, _ = edit_pptx(
            edited,
            operations,
            image_assets=image_assets,
        )
        assert no_op == edited


def test_verified_native_roundtrip_fixtures_have_clean_media_gc_baselines() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()

        plan = inspect_pptx(
            source,
            max_slides=1,
            include_media_gc_plan=True,
        )["media_gc_plan"]

        assert plan["contract_version"] == 2
        assert plan["mode"] == "dry_run"
        assert plan["destructive"] is False
        assert plan["deletion_supported"] is False
        assert plan["analysis_complete"] is True
        assert plan["package_xml_integrity_complete"] is True
        assert plan["undeclared_relationship_reference_count"] == 0
        assert plan["image_part_count"] == 9
        assert plan["image_relationship_count"] == 9
        assert plan["live_relationship_count"] == 9
        assert plan["unreferenced_relationship_count"] == 0
        assert plan["blocked_relationship_count"] == 0
        assert plan["relationship_candidate_count"] == 0
        assert plan["part_candidate_count"] == 0
        assert plan["blocker_count"] == 0
        assert plan["root_reachable_scoped_image_part_count"] == 9
        assert plan["projected_root_reachable_scoped_image_part_count"] == 9


def test_verified_native_roundtrip_fixtures_support_source_only_picture_replacement() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True
    jpeg_path = "/mnt/user-data/uploads/picture-replacement.jpeg"
    png_path = "/mnt/user-data/uploads/picture-replacement.png"
    jpeg = build_image_fill_replacement_jpeg()
    png = build_image_fill_replacement_png()
    image_assets = {jpeg_path: jpeg, png_path: png}

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before = _assert_semantic_contract(source, manifest)
        effect_picture = before["VF_RT_PICTURE_EFFECT"]
        shared_picture = before["VF_RT_PICTURE_SHARED"]
        jpeg_picture = before["VF_RT_PICTURE_JPEG"]
        operations = [
            PptxPictureSourceReplacementOperation(
                pictures=PptxPictureSelector(
                    targets=[
                        PptxPictureTarget(
                            path=effect_picture["path"],
                            expected_name=effect_picture["name"],
                            expected_source_sha256=effect_picture["source"]["sha256"],
                        )
                    ]
                ),
                image_path=jpeg_path,
            ),
            PptxPictureSourceReplacementOperation(
                pictures=PptxPictureSelector(
                    targets=[
                        PptxPictureTarget(
                            path=jpeg_picture["path"],
                            expected_name=jpeg_picture["name"],
                            expected_source_sha256=jpeg_picture["source"]["sha256"],
                        )
                    ]
                ),
                image_path=png_path,
            ),
        ]

        edited, reports = edit_pptx(
            source,
            operations,
            image_assets=image_assets,
        )

        assert [report["type"] for report in reports] == [
            "replace_pptx_picture_sources",
            "replace_pptx_picture_sources",
        ]
        assert [report["match_count"] for report in reports] == [1, 1]
        assert validate_pptx(edited)["valid"] is True
        after = _objects_by_name(
            inspect_pptx(
                edited,
                max_slides=20,
                include_formatting=True,
            )
        )
        for name in before.keys() - {
            "VF_RT_PICTURE_EFFECT",
            "VF_RT_PICTURE_JPEG",
        }:
            assert after[name] == before[name]
        assert after["VF_RT_PICTURE_SHARED"] == shared_picture
        assert _picture_preservation_view(after["VF_RT_PICTURE_EFFECT"]) == _picture_preservation_view(effect_picture)
        assert _picture_preservation_view(after["VF_RT_PICTURE_JPEG"]) == _picture_preservation_view(jpeg_picture)
        assert after["VF_RT_PICTURE_EFFECT"]["source"] == {
            "relationship_id": after["VF_RT_PICTURE_EFFECT"]["relationship_ids"][0],
            "part_name": "ppt/media/image10.jpg",
            "content_type": "image/jpeg",
            "size_bytes": len(jpeg),
            "sha256": _sha256(jpeg),
        }
        assert after["VF_RT_PICTURE_JPEG"]["source"] == {
            "relationship_id": after["VF_RT_PICTURE_JPEG"]["relationship_ids"][0],
            "part_name": "ppt/media/image11.png",
            "content_type": "image/png",
            "size_bytes": len(png),
            "sha256": _sha256(png),
        }
        assert after["VF_RT_PICTURE_SHARED"]["source"] == shared_picture["source"]

        plan = inspect_pptx(
            edited,
            max_slides=1,
            include_media_gc_plan=True,
        )["media_gc_plan"]
        assert plan["contract_version"] == 2
        assert plan["analysis_complete"] is True
        assert plan["package_xml_integrity_complete"] is True
        assert plan["undeclared_relationship_reference_count"] == 0
        assert plan["blocked_relationship_count"] == 0
        assert plan["relationship_candidate_count"] == 1
        candidate = plan["relationship_candidates"][0]
        assert candidate["source_part"] == "ppt/slides/slide13.xml"
        assert candidate["relationship_part"] == ("ppt/slides/_rels/slide13.xml.rels")
        assert candidate["relationship_id"] == jpeg_picture["source"]["relationship_id"]
        assert candidate["part_name"] == jpeg_picture["source"]["part_name"]
        assert candidate["content_type"] == jpeg_picture["source"]["content_type"]
        assert candidate["size_bytes"] == jpeg_picture["source"]["size_bytes"]
        assert candidate["target_part_sha256"] == jpeg_picture["source"]["sha256"]
        assert candidate["xml_reference_count"] == 0
        assert candidate["source_root_reachable"] is True
        assert candidate["target_root_reachable_before_zero_ref_filter"] is True
        assert candidate["target_root_reachable_after_zero_ref_filter"] is False
        assert candidate["part_all_incoming_relationships_have_zero_xml_references"] is True
        assert plan["part_candidate_count"] == 1
        assert plan["part_candidates"][0]["part_name"] == jpeg_picture["source"]["part_name"]
        assert plan["part_candidates"][0]["status"] == ("all_incoming_relationships_have_zero_xml_references")
        assert plan["part_candidates"][0]["root_reachable_before_zero_ref_filter"] is True
        assert plan["part_candidates"][0]["root_reachable_after_zero_ref_filter"] is False
        assert plan["estimated_reclaimable_uncompressed_bytes"] == jpeg_picture["source"]["size_bytes"]
        assert plan["root_reachable_scoped_image_part_count"] == 11
        assert plan["projected_root_reachable_scoped_image_part_count"] == 10

        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            source_names = set(source_archive.namelist())
            edited_names = set(edited_archive.namelist())
            assert edited_names - source_names == {
                "ppt/media/image10.jpg",
                "ppt/media/image11.png",
            }
            assert edited_archive.read("ppt/media/image10.jpg") == jpeg
            assert edited_archive.read("ppt/media/image11.png") == png
            changed = {name for name in source_names & edited_names if source_archive.read(name) != edited_archive.read(name)}
        assert {
            "ppt/slides/_rels/slide13.xml.rels",
            "ppt/slides/slide13.xml",
        } <= changed
        assert changed <= {
            "[Content_Types].xml",
            "ppt/slides/_rels/slide13.xml.rels",
            "ppt/slides/slide13.xml",
        }

        refreshed_operations = [
            PptxPictureSourceReplacementOperation(
                pictures=PptxPictureSelector(
                    targets=[
                        PptxPictureTarget(
                            path=after[name]["path"],
                            expected_name=after[name]["name"],
                            expected_source_sha256=after[name]["source"]["sha256"],
                        )
                    ]
                ),
                image_path=image_path,
            )
            for name, image_path in (
                ("VF_RT_PICTURE_EFFECT", jpeg_path),
                ("VF_RT_PICTURE_JPEG", png_path),
            )
        ]
        no_op, _ = edit_pptx(
            edited,
            refreshed_operations,
            image_assets=image_assets,
        )
        assert no_op == edited


def test_verified_native_roundtrip_fixtures_support_typed_slide_backgrounds() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True
    jpeg_path = "/mnt/user-data/uploads/native-background.jpeg"
    png_path = "/mnt/user-data/uploads/native-background.png"
    jpeg = build_image_fill_replacement_jpeg()
    png = build_image_fill_replacement_png()
    image_assets = {
        jpeg_path: jpeg,
        png_path: png,
    }

    operations = [
        PptxSlideBackgroundFormatOperation(
            slides=PptxSlideSelector(
                targets=[
                    PptxSlideTarget(
                        path="/slide[8]",
                        expected_part_name="ppt/slides/slide8.xml",
                    )
                ]
            ),
            formatting=PptxSlideBackgroundFormatting(
                type="solid",
                color="#A9D18E",
            ),
        ),
        PptxSlideBackgroundFormatOperation(
            slides=PptxSlideSelector(
                targets=[
                    PptxSlideTarget(
                        path="/slide[9]",
                        expected_part_name="ppt/slides/slide9.xml",
                    )
                ]
            ),
            formatting=PptxSlideBackgroundFormatting(
                type="gradient",
                stops=[
                    PptxGradientStopFormatting(
                        position_percent=0,
                        color="#203864",
                    ),
                    PptxGradientStopFormatting(
                        position_percent=37.5,
                        color="#ED7D31",
                        opacity_percent=80,
                    ),
                    PptxGradientStopFormatting(
                        position_percent=100,
                        color="#FFF2CC",
                    ),
                ],
                geometry=PptxLinearGradientFormatting(
                    angle_degrees=47.5,
                    scaled=False,
                ),
            ),
        ),
        PptxSlideBackgroundFormatOperation(
            slides=PptxSlideSelector(
                targets=[
                    PptxSlideTarget(
                        path="/slide[10]",
                        expected_part_name="ppt/slides/slide10.xml",
                    )
                ]
            ),
            formatting=PptxSlideBackgroundFormatting(
                type="image",
                image_path=jpeg_path,
                mode="stretch",
            ),
        ),
        PptxSlideBackgroundFormatOperation(
            slides=PptxSlideSelector(
                targets=[
                    PptxSlideTarget(
                        path="/slide[11]",
                        expected_part_name="ppt/slides/slide11.xml",
                    )
                ]
            ),
            formatting=PptxSlideBackgroundFormatting(
                type="image",
                image_path=png_path,
                mode="tile",
                tile=PptxImageTileFormatting(
                    offset_x_emu=-254_000,
                    offset_y_emu=190_500,
                    scale_x_percent=72.5,
                    scale_y_percent=38.25,
                    alignment="bottom_right",
                    flip="both",
                ),
            ),
        ),
        PptxSlideBackgroundFormatOperation(
            slides=PptxSlideSelector(
                targets=[
                    PptxSlideTarget(
                        path="/slide[12]",
                        expected_part_name="ppt/slides/slide12.xml",
                    )
                ]
            ),
            formatting=PptxSlideBackgroundFormatting(
                type="image",
                image_path=png_path,
                mode="center",
            ),
        ),
    ]

    for lane in manifest["lanes"]:
        if lane["status"] != "verified":
            continue
        source = (_CORPUS_DIR / lane["fixture"]).read_bytes()
        before_objects = _assert_semantic_contract(source, manifest)

        edited, reports = edit_pptx(
            source,
            operations,
            image_assets=image_assets,
        )

        assert [report["type"] for report in reports] == [
            "format_pptx_slide_backgrounds",
        ] * 5
        assert [report["match_count"] for report in reports] == [1] * 5
        assert [report["matched_paths"] for report in reports] == [[f"/slide[{index}]"] for index in range(8, 13)]
        assert validate_pptx(edited)["valid"] is True
        inspected = inspect_pptx(
            edited,
            max_slides=20,
            include_formatting=True,
        )
        assert _objects_by_name(inspected) == before_objects
        slides = {slide["path"]: slide for slide in inspected["slides"]}
        assert slides["/slide[8]"]["background"] == {
            "scope": "direct",
            "type": "solid",
            "color": {"type": "rgb", "value": "#A9D18E"},
        }
        assert slides["/slide[9]"]["background"] == {
            "scope": "direct",
            "type": "gradient",
            "rotate_with_shape": False,
            "stops": [
                {
                    "position_percent": 0.0,
                    "color": {"type": "rgb", "value": "#203864"},
                },
                {
                    "position_percent": 37.5,
                    "color": {
                        "type": "rgb",
                        "value": "#ED7D31",
                        "opacity_percent": 80.0,
                    },
                },
                {
                    "position_percent": 100.0,
                    "color": {"type": "rgb", "value": "#FFF2CC"},
                },
            ],
            "geometry": "linear",
            "angle_degrees": 47.5,
            "scaled": False,
        }
        stretch = slides["/slide[10]"]["background"]
        assert {key: value for key, value in stretch.items() if key != "relationship_ids"} == {
            "scope": "direct",
            "type": "image",
            "fill_mode": "stretch",
            "fill_rectangle": {},
        }
        tile = slides["/slide[11]"]["background"]
        assert {key: value for key, value in tile.items() if key != "relationship_ids"} == {
            "scope": "direct",
            "type": "image",
            "fill_mode": "tile",
            "tile": {
                "offset_x_emu": -254_000,
                "offset_y_emu": 190_500,
                "scale_x_percent": 72.5,
                "scale_y_percent": 38.25,
                "alignment": "bottom_right",
                "flip": "both",
            },
        }
        center = slides["/slide[12]"]["background"]
        assert {key: value for key, value in center.items() if key != "relationship_ids"} == {
            "scope": "direct",
            "type": "image",
            "fill_mode": "center",
        }
        assert all(len(background["relationship_ids"]) == 1 for background in (stretch, tile, center))

        with (
            zipfile.ZipFile(io.BytesIO(source)) as source_archive,
            zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
        ):
            source_names = set(source_archive.namelist())
            edited_names = set(edited_archive.namelist())
            assert source_names <= edited_names
            added_media = sorted(name for name in edited_names - source_names if name.startswith("ppt/media/"))
            assert len(added_media) == 2
            assert {edited_archive.read(name) for name in added_media} == {jpeg, png}
            changed = sorted(name for name in source_names if source_archive.read(name) != edited_archive.read(name))
        expected_changed = [
            "ppt/slides/_rels/slide10.xml.rels",
            "ppt/slides/_rels/slide11.xml.rels",
            "ppt/slides/_rels/slide12.xml.rels",
            "ppt/slides/slide10.xml",
            "ppt/slides/slide11.xml",
            "ppt/slides/slide12.xml",
            "ppt/slides/slide8.xml",
            "ppt/slides/slide9.xml",
        ]
        if lane["producer"] == "wps_presentation":
            expected_changed.insert(0, "[Content_Types].xml")
        assert changed == expected_changed

        no_op, _ = edit_pptx(
            edited,
            operations,
            image_assets=image_assets,
        )
        assert no_op == edited


def test_pptx_formatting_operations_open_only_after_native_corpus_is_ready() -> None:
    manifest = _load_manifest()
    assert manifest["formatting_readiness"]["ready"] is True
    schema = TypeAdapter(PptxEditOperation).json_schema()
    assert set(schema["discriminator"]["mapping"]) == {
        "format_pptx_paragraphs",
        "format_pptx_runs",
        "format_pptx_lines",
        "format_pptx_shapes",
        "format_pptx_slide_backgrounds",
        "replace_pptx_picture_sources",
        "replace_pptx_text",
    }
    definitions = schema["$defs"]
    background_properties = definitions["PptxSlideBackgroundFormatting"]["properties"]
    assert set(background_properties["type"]["enum"]) == {
        "none",
        "solid",
        "gradient",
        "image",
    }
    assert set(background_properties) == {
        "type",
        "color",
        "stops",
        "geometry",
        "image_path",
        "mode",
        "tile",
    }
    assert set(background_properties["mode"]["anyOf"][0]["enum"]) == {
        "stretch",
        "tile",
        "center",
    }
    assert definitions["PptxSlideTarget"]["required"] == [
        "path",
        "expected_part_name",
    ]
    assert definitions["PptxPictureTarget"]["required"] == [
        "path",
        "expected_name",
        "expected_source_sha256",
    ]
    picture_operation = definitions["PptxPictureSourceReplacementOperation"]
    assert set(picture_operation["properties"]) == {
        "type",
        "pictures",
        "image_path",
    }
    fill_properties = definitions["PptxShapeFillFormatting"]["properties"]
    assert set(fill_properties["type"]["enum"]) == {
        "solid",
        "none",
        "gradient",
        "pattern",
        "image",
    }
    pattern_presets = set(fill_properties["preset"]["anyOf"][0]["enum"])
    assert len(pattern_presets) == 54
    assert {
        "pct25",
        "diagCross",
        "weave",
        "solidDmnd",
    } <= pattern_presets
    geometry_union = definitions["PptxShapeFillFormatting"]["properties"]["geometry"]["anyOf"][0]
    assert set(geometry_union["discriminator"]["mapping"]) == {
        "linear",
        "path",
    }
    assert set(definitions["PptxGradientRectangleFormatting"]["required"]) == {
        "left_percent",
        "top_percent",
        "right_percent",
        "bottom_percent",
    }
    assert set(definitions["PptxImageCropFormatting"]["required"]) == {
        "left_percent",
        "top_percent",
        "right_percent",
        "bottom_percent",
    }
    assert fill_properties["image_path"]["anyOf"][0]["maxLength"] == 1_024
    assert set(fill_properties["mode"]["anyOf"][0]["enum"]) == {
        "stretch",
        "tile",
        "center",
    }
    assert set(definitions["PptxImageTileFormatting"]["required"]) == {
        "offset_x_emu",
        "offset_y_emu",
        "scale_x_percent",
        "scale_y_percent",
        "alignment",
        "flip",
    }
    assert definitions["PptxPathGradientFormatting"]["properties"]["path"]["const"] == "circle"
    assert set(definitions["PptxPresetGeometryFormatting"]["properties"]["preset"]["enum"]) == {
        "rect",
        "roundRect",
        "ellipse",
        "triangle",
        "rtTriangle",
        "diamond",
        "parallelogram",
        "trapezoid",
        "pentagon",
        "hexagon",
        "heptagon",
        "octagon",
    }

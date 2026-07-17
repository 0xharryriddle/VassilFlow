from __future__ import annotations

import hashlib
import io
import struct
import zipfile
import zlib
from pathlib import Path

from vassilflow.community.office.pptx_preflight import preflight_pptx

_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_RELATIONSHIP_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_EMU_PER_INCH = 914_400
_ROUNDTRIP_CORPUS = Path(__file__).parent / "fixtures" / "office" / "pptx" / "roundtrip"


def _png(width: int, height: int) -> bytes:
    rows = b"".join(b"\x00" + bytes((68, 114, 196, 255)) * width for _ in range(height))

    def chunk(chunk_type: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _shape(
    text: str,
    *,
    object_id: int = 2,
    title: bool = False,
    run_properties: str = "",
    run_property_children: str = "",
) -> str:
    placeholder = '<p:ph type="title"/>' if title else ""
    properties = ""
    if run_properties or run_property_children:
        properties = f"<a:rPr {run_properties}>{run_property_children}</a:rPr>"
    return f"""<p:sp>
      <p:nvSpPr><p:cNvPr id="{object_id}" name="Text"/><p:cNvSpPr/><p:nvPr>{placeholder}</p:nvPr></p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>{properties}<a:t>{text}</a:t></a:r></a:p></p:txBody>
    </p:sp>"""


def _picture(
    *,
    object_id: int,
    relationship_id: str | None = None,
    alt_text: str | None = None,
    x_emu: int = 0,
    y_emu: int = 0,
    width_emu: int | None = None,
    height_emu: int | None = None,
    rotation_degrees: int = 0,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
    crop: tuple[int, int, int, int] | None = None,
    framing: str = "<a:stretch><a:fillRect/></a:stretch>",
) -> str:
    description = "" if alt_text is None else f' descr="{alt_text}"'
    blip = "" if relationship_id is None else f'<a:blip r:embed="{relationship_id}"/>'
    source_rectangle = "" if crop is None else (f'<a:srcRect l="{crop[0]}" t="{crop[1]}" r="{crop[2]}" b="{crop[3]}"/>')
    transform = ""
    if width_emu is not None and height_emu is not None:
        transform_attributes = ""
        if rotation_degrees:
            transform_attributes += f' rot="{rotation_degrees * 60_000}"'
        if flip_horizontal:
            transform_attributes += ' flipH="1"'
        if flip_vertical:
            transform_attributes += ' flipV="1"'
        transform = f'<a:xfrm{transform_attributes}><a:off x="{x_emu}" y="{y_emu}"/><a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm>'
    return f"""<p:pic>
      <p:nvPicPr><p:cNvPr id="{object_id}" name="Image"{description}/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
      <p:blipFill>{blip}{source_rectangle}{framing}</p:blipFill>
      <p:spPr>{transform}</p:spPr>
    </p:pic>"""


def _group(
    body: str,
    *,
    object_id: int = 20,
    x_emu: int = 0,
    y_emu: int = 0,
    width_emu: int = 1_000_000,
    height_emu: int = 1_000_000,
    child_x_emu: int = 0,
    child_y_emu: int = 0,
    child_width_emu: int = 1_000_000,
    child_height_emu: int = 1_000_000,
    rotation_degrees: int = 0,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
) -> str:
    transform_attributes = ""
    if rotation_degrees:
        transform_attributes += f' rot="{rotation_degrees * 60_000}"'
    if flip_horizontal:
        transform_attributes += ' flipH="1"'
    if flip_vertical:
        transform_attributes += ' flipV="1"'
    transform = f'<a:xfrm{transform_attributes}><a:off x="{x_emu}" y="{y_emu}"/><a:ext cx="{width_emu}" cy="{height_emu}"/><a:chOff x="{child_x_emu}" y="{child_y_emu}"/><a:chExt cx="{child_width_emu}" cy="{child_height_emu}"/></a:xfrm>'
    return f"""<p:grpSp>
      <p:nvGrpSpPr><p:cNvPr id="{object_id}" name="Group"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr>{transform}</p:grpSpPr>
      {body}
    </p:grpSp>"""


def _pptx(
    body: str,
    *,
    slide_relationships: str | None = None,
    extra_parts: dict[str, bytes] | None = None,
) -> bytes:
    content_types = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
      <Default Extension="xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
      <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
      <Default Extension="png" ContentType="image/png"/>
      <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
    </Types>"""
    root_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rId1" Type="{_RELATIONSHIP_NS}/officeDocument" Target="ppt/presentation.xml"/>
    </Relationships>"""
    presentation = f"""<p:presentation xmlns:p="{_PRESENTATION_NS}" xmlns:r="{_RELATIONSHIP_NS}">
      <p:sldIdLst><p:sldId id="256" r:id="rIdSlide"/></p:sldIdLst>
      <p:sldSz cx="12192000" cy="6858000"/>
    </p:presentation>"""
    presentation_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdSlide" Type="{_RELATIONSHIP_NS}/slide" Target="slides/slide1.xml"/>
    </Relationships>"""
    slide = f"""<p:sld xmlns:p="{_PRESENTATION_NS}" xmlns:a="{_DRAWING_NS}" xmlns:r="{_RELATIONSHIP_NS}">
      <p:cSld><p:spTree>
        <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
        {body}
      </p:spTree></p:cSld>
    </p:sld>"""

    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            presentation_relationships,
        )
        archive.writestr("ppt/slides/slide1.xml", slide)
        if slide_relationships is not None:
            archive.writestr(
                "ppt/slides/_rels/slide1.xml.rels",
                slide_relationships,
            )
        for part_name, payload in (extra_parts or {}).items():
            archive.writestr(part_name, payload)
    return output.getvalue()


def _finding_codes(report: dict[str, object]) -> list[str]:
    findings = report["findings"]
    assert isinstance(findings, list)
    return [str(finding["code"]) for finding in findings]


def test_preflight_is_source_bound_read_only_and_distinguishes_title_evidence() -> None:
    image_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdImage" Type="{_RELATIONSHIP_NS}/image" Target="../media/image1.png"/>
    </Relationships>"""
    image = _png(4, 3)
    empty_title = _pptx(
        _shape("", title=True)
        + _picture(
            object_id=3,
            relationship_id="rIdImage",
            alt_text=None,
        ),
        slide_relationships=image_relationships,
        extra_parts={"ppt/media/image1.png": image},
    )
    original = bytes(empty_title)

    report = preflight_pptx(empty_title)

    assert empty_title == original
    assert report["schema"] == "vassilflow.office.pptx.quality_preflight.v1"
    assert report["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["mode"] == "read_only"
    assert report["mutated"] is False
    assert report["visual_review_status"] == "not_performed"
    assert report["limits"] == {
        "package_bytes": 50 * 1024 * 1024,
        "slides": 1_000,
        "objects": 100_000,
        "objects_per_slide": 5_000,
        "text_nodes": 100_000,
        "text_characters": 5_000_000,
        "findings": 200,
        "image_assessments": 200,
        "geometry_assessments": 200,
        "census_values_per_kind": 64,
        "group_depth": 64,
        "absolute_geometry_emu": 1_000_000_000_000,
        "absolute_transform_value": 1_000_000_000_000_000,
        "absolute_percentage": 1_000.0,
    }
    assert "empty_title_placeholder" in _finding_codes(report)
    assert "missing_slide_title_evidence" not in _finding_codes(report)
    assert "missing_picture_alt_text" in _finding_codes(report)
    missing_alt = next(finding for finding in report["findings"] if finding["code"] == "missing_picture_alt_text")
    assert missing_alt["evidence"]["relationship"] == {
        "relationship_id": "rIdImage",
        "target_part_name": "ppt/media/image1.png",
        "content_type": "image/png",
        "source_sha256": hashlib.sha256(image).hexdigest(),
    }

    no_title_report = preflight_pptx(_pptx(_shape("Regular heading")))
    assert "missing_slide_title_evidence" in _finding_codes(no_title_report)
    missing_title = next(finding for finding in no_title_report["findings"] if finding["code"] == "missing_slide_title_evidence")
    assert "does not prove" in missing_title["message"]


def test_preflight_reports_tiny_direct_text_and_bounded_formatting_census() -> None:
    shape = _shape(
        "Fine print",
        run_properties='sz="800"',
        run_property_children=('<a:solidFill><a:srgbClr val="1f4e79"/></a:solidFill><a:latin typeface="Georgia"/>'),
    )

    report = preflight_pptx(_pptx(shape))

    tiny = next(finding for finding in report["findings"] if finding["code"] == "tiny_direct_text")
    assert tiny["path"] == "/slide[1]/shape[@id=2]/paragraph[1]/run[1]"
    assert tiny["evidence"]["direct_font_size_points"] == 8
    census = report["direct_formatting_census"]
    assert {item["value"] for item in census["font_faces"]["values"]} == {"latin:Georgia"}
    assert {item["value"] for item in census["font_sizes"]["values"]} == {"8pt"}
    assert {item["value"] for item in census["colors"]["values"]} == {"rgb:#1F4E79"}


def test_preflight_measures_crop_aware_ppi_and_group_geometry() -> None:
    image_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdImage" Type="{_RELATIONSHIP_NS}/image" Target="../media/image1.png"/>
    </Relationships>"""
    top_level = _picture(
        object_id=3,
        relationship_id="rIdImage",
        alt_text="Top-level image",
        width_emu=4 * _EMU_PER_INCH,
        height_emu=2 * _EMU_PER_INCH,
        crop=(10_000, 0, 10_000, 0),
    )
    grouped = _group(
        _picture(
            object_id=5,
            relationship_id="rIdImage",
            alt_text="Grouped image",
            width_emu=2 * _EMU_PER_INCH,
            height_emu=_EMU_PER_INCH,
        )
    )
    tiled = _picture(
        object_id=6,
        relationship_id="rIdImage",
        alt_text="Tiled image",
        width_emu=2 * _EMU_PER_INCH,
        height_emu=_EMU_PER_INCH,
        framing='<a:tile sx="100000" sy="100000" algn="ctr" flip="none"/>',
    )
    data = _pptx(
        _shape("Title", title=True) + top_level + grouped + tiled,
        slide_relationships=image_relationships,
        extra_parts={"ppt/media/image1.png": _png(200, 100)},
    )

    report = preflight_pptx(data)

    assessments = {assessment["path"]: assessment for assessment in report["image_quality"]["assessments"]}
    measured = assessments["/slide[1]/picture[@id=3]"]
    assert measured["status"] == "measured"
    assert measured["effective_ppi"] == {
        "horizontal": 40.0,
        "vertical": 50.0,
        "minimum": 40.0,
    }
    assert measured["crop"]["left_percent"] == 10
    grouped_assessment = assessments["/slide[1]/group[@id=20]/picture[@id=5]"]
    assert grouped_assessment["status"] == "measured"
    assert grouped_assessment["group_depth"] == 1
    assert grouped_assessment["effective_ppi"] == {
        "horizontal": 100.0,
        "vertical": 100.0,
        "minimum": 100.0,
    }
    tiled_assessment = assessments["/slide[1]/picture[@id=6]"]
    assert tiled_assessment["status"] == "unknown"
    assert tiled_assessment["reason"] == "unsupported_picture_framing"
    low_ppi = [finding for finding in report["findings"] if finding["code"] == "low_effective_ppi"]
    assert [finding["path"] for finding in low_ppi] == ["/slide[1]/picture[@id=3]"]


def test_preflight_measures_destination_fill_rectangle_for_effective_ppi() -> None:
    image_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdImage" Type="{_RELATIONSHIP_NS}/image" Target="../media/image1.png"/>
    </Relationships>"""
    picture = _picture(
        object_id=3,
        relationship_id="rIdImage",
        alt_text="Inset destination image",
        width_emu=4 * _EMU_PER_INCH,
        height_emu=2 * _EMU_PER_INCH,
        framing='<a:stretch><a:fillRect r="25000"/></a:stretch>',
    )
    report = preflight_pptx(
        _pptx(
            _shape("Title", title=True) + picture,
            slide_relationships=image_relationships,
            extra_parts={"ppt/media/image1.png": _png(300, 200)},
        )
    )

    image = report["image_quality"]["assessments"][0]
    assert image["status"] == "measured"
    assert image["frame_inches"] == {"width": 4.0, "height": 2.0}
    assert image["display_inches"] == {"width": 3.0, "height": 2.0}
    assert image["fill_rectangle"] == {
        "left_percent": 0.0,
        "top_percent": 0.0,
        "right_percent": 25.0,
        "bottom_percent": 0.0,
    }
    assert image["effective_ppi"] == {
        "horizontal": 100.0,
        "vertical": 100.0,
        "minimum": 100.0,
    }
    assert "low_effective_ppi" not in _finding_codes(report)


def test_preflight_resolves_nested_group_scale_rotation_and_flip() -> None:
    image_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdImage" Type="{_RELATIONSHIP_NS}/image" Target="../media/image1.png"/>
    </Relationships>"""
    picture = _picture(
        object_id=7,
        relationship_id="rIdImage",
        alt_text="Nested transformed image",
        width_emu=2 * _EMU_PER_INCH,
        height_emu=_EMU_PER_INCH,
    )
    inner = _group(
        picture,
        object_id=6,
        width_emu=4 * _EMU_PER_INCH,
        height_emu=2 * _EMU_PER_INCH,
        child_width_emu=2 * _EMU_PER_INCH,
        child_height_emu=_EMU_PER_INCH,
        flip_vertical=True,
    )
    outer = _group(
        inner,
        object_id=5,
        x_emu=2 * _EMU_PER_INCH,
        y_emu=_EMU_PER_INCH,
        width_emu=8 * _EMU_PER_INCH,
        height_emu=4 * _EMU_PER_INCH,
        child_width_emu=4 * _EMU_PER_INCH,
        child_height_emu=2 * _EMU_PER_INCH,
        rotation_degrees=90,
        flip_horizontal=True,
    )
    report = preflight_pptx(
        _pptx(
            _shape("Title", title=True) + outer,
            slide_relationships=image_relationships,
            extra_parts={"ppt/media/image1.png": _png(200, 100)},
        )
    )

    image = report["image_quality"]["assessments"][0]
    assert image["status"] == "measured"
    assert image["group_depth"] == 2
    assert image["display_inches"] == {"width": 8.0, "height": 4.0}
    assert image["effective_ppi"] == {
        "horizontal": 25.0,
        "vertical": 25.0,
        "minimum": 25.0,
    }
    geometry = next(assessment for assessment in report["geometry_quality"]["assessments"] if assessment["path"] == "/slide[1]/group[@id=5]/group[@id=6]/picture[@id=7]")
    assert geometry["status"] == "measured"
    assert geometry["group_depth"] == 2
    assert geometry["display_axes_emu"] == {
        "horizontal": 8 * _EMU_PER_INCH,
        "vertical": 4 * _EMU_PER_INCH,
    }
    assert geometry["slide_intersection"] == {
        "visible_frame_percent": 87.5,
        "outside_frame_percent": 12.5,
    }
    findings = {finding["code"]: finding for finding in report["findings"] if finding["path"] == geometry["path"]}
    assert findings["low_effective_ppi"]["severity"] == "warning"
    assert findings["picture_frame_materially_clipped"]["severity"] == "info"


def test_preflight_resolves_noncommuting_group_scale_child_offset_and_flips() -> None:
    image_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdImage" Type="{_RELATIONSHIP_NS}/image" Target="../media/image1.png"/>
    </Relationships>"""
    picture = _picture(
        object_id=5,
        relationship_id="rIdImage",
        alt_text="Asymmetric transformed image",
        x_emu=3 * _EMU_PER_INCH // 2,
        y_emu=2 * _EMU_PER_INCH,
        width_emu=_EMU_PER_INCH // 2,
        height_emu=_EMU_PER_INCH,
        flip_vertical=True,
    )
    group = _group(
        picture,
        object_id=4,
        x_emu=3 * _EMU_PER_INCH,
        y_emu=2 * _EMU_PER_INCH,
        width_emu=6 * _EMU_PER_INCH,
        height_emu=2 * _EMU_PER_INCH,
        child_x_emu=_EMU_PER_INCH,
        child_y_emu=_EMU_PER_INCH,
        child_width_emu=3 * _EMU_PER_INCH,
        child_height_emu=4 * _EMU_PER_INCH,
        rotation_degrees=90,
        flip_horizontal=True,
    )
    report = preflight_pptx(
        _pptx(
            _shape("Title", title=True) + group,
            slide_relationships=image_relationships,
            extra_parts={"ppt/media/image1.png": _png(100, 50)},
        )
    )

    path = "/slide[1]/group[@id=4]/picture[@id=5]"
    image = next(item for item in report["image_quality"]["assessments"] if item["path"] == path)
    assert image["group_depth"] == 1
    assert image["display_inches"] == {"width": 1.0, "height": 0.5}
    assert image["effective_ppi"] == {
        "horizontal": 100.0,
        "vertical": 100.0,
        "minimum": 100.0,
    }
    geometry = next(item for item in report["geometry_quality"]["assessments"] if item["path"] == path)
    assert geometry["bounds_emu"] == {
        "left": 6 * _EMU_PER_INCH,
        "top": 4 * _EMU_PER_INCH,
        "right": 13 * _EMU_PER_INCH / 2,
        "bottom": 5 * _EMU_PER_INCH,
    }
    assert geometry["intersection_evidence"]["frame_polygon_emu"] == [
        {"x": 6 * _EMU_PER_INCH, "y": 5 * _EMU_PER_INCH},
        {"x": 6 * _EMU_PER_INCH, "y": 4 * _EMU_PER_INCH},
        {"x": 13 * _EMU_PER_INCH / 2, "y": 4 * _EMU_PER_INCH},
        {"x": 13 * _EMU_PER_INCH / 2, "y": 5 * _EMU_PER_INCH},
    ]


def test_preflight_reports_outside_and_materially_clipped_picture_frames() -> None:
    image_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdImage" Type="{_RELATIONSHIP_NS}/image" Target="../media/image1.png"/>
    </Relationships>"""
    outside = _picture(
        object_id=3,
        relationship_id="rIdImage",
        alt_text="Outside image",
        x_emu=-2 * _EMU_PER_INCH,
        y_emu=_EMU_PER_INCH,
        width_emu=_EMU_PER_INCH,
        height_emu=_EMU_PER_INCH,
    )
    clipped = _picture(
        object_id=4,
        relationship_id="rIdImage",
        alt_text="Clipped image",
        x_emu=-_EMU_PER_INCH // 2,
        y_emu=3 * _EMU_PER_INCH,
        width_emu=2 * _EMU_PER_INCH,
        height_emu=_EMU_PER_INCH,
    )
    report = preflight_pptx(
        _pptx(
            _shape("Title", title=True) + outside + clipped,
            slide_relationships=image_relationships,
            extra_parts={"ppt/media/image1.png": _png(400, 200)},
        )
    )

    geometry = {item["path"]: item for item in report["geometry_quality"]["assessments"]}
    assert geometry["/slide[1]/picture[@id=3]"]["slide_intersection"] == {
        "visible_frame_percent": 0.0,
        "outside_frame_percent": 100.0,
    }
    assert geometry["/slide[1]/picture[@id=4]"]["slide_intersection"] == {
        "visible_frame_percent": 75.0,
        "outside_frame_percent": 25.0,
    }
    findings = {(finding["code"], finding["path"]): finding for finding in report["findings"]}
    assert findings[("object_frame_outside_slide", "/slide[1]/picture[@id=3]")]["severity"] == "warning"
    assert findings[("picture_frame_materially_clipped", "/slide[1]/picture[@id=4]")]["evidence"]["outside_frame_percent"] == 25.0
    geometry_check = next(check for check in report["checks"] if check["id"] == "geometry_bounds_and_overlap")
    assert geometry_check["status"] == "partial"
    assert geometry_check["finding_count"] == 2


def test_preflight_does_not_call_a_huge_frame_covering_the_slide_fully_outside() -> None:
    path = "/slide[1]/picture[@id=3]"
    report = preflight_pptx(
        _pptx(
            _shape("Title", title=True)
            + _picture(
                object_id=3,
                alt_text="Huge frame covering the slide",
                x_emu=-500_000_000_000,
                y_emu=-500_000_000_000,
                width_emu=1_000_000_000_000,
                height_emu=1_000_000_000_000,
            )
        )
    )

    geometry = next(item for item in report["geometry_quality"]["assessments"] if item["path"] == path)
    assert geometry["slide_intersection"]["visible_frame_percent"] == 0.0
    assert geometry["intersection_evidence"]["intersection_area_square_emu"] > 0
    findings = {finding["code"] for finding in report["findings"] if finding["path"] == path}
    assert "object_frame_outside_slide" not in findings
    assert "picture_frame_materially_clipped" in findings


def test_preflight_fails_closed_for_invalid_group_child_extents() -> None:
    image_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdImage" Type="{_RELATIONSHIP_NS}/image" Target="../media/image1.png"/>
    </Relationships>"""
    grouped = _group(
        _picture(
            object_id=5,
            relationship_id="rIdImage",
            alt_text="Invalid group image",
            width_emu=_EMU_PER_INCH,
            height_emu=_EMU_PER_INCH,
        ),
        child_width_emu=0,
    )
    report = preflight_pptx(
        _pptx(
            _shape("Title", title=True) + grouped,
            slide_relationships=image_relationships,
            extra_parts={"ppt/media/image1.png": _png(100, 100)},
        )
    )

    image = report["image_quality"]["assessments"][0]
    assert image["status"] == "unknown"
    assert image["reason"] == "display_geometry_unavailable"
    geometry = next(assessment for assessment in report["geometry_quality"]["assessments"] if assessment["path"] == "/slide[1]/group[@id=20]/picture[@id=5]")
    assert geometry == {
        "slide_index": 1,
        "path": "/slide[1]/group[@id=20]/picture[@id=5]",
        "object_kind": "picture",
        "status": "unknown",
        "reason": "group_transform_unavailable",
    }


def test_preflight_fails_closed_for_adversarial_crop_and_rotation_numbers() -> None:
    image_relationships = f"""<Relationships xmlns="{_PACKAGE_RELATIONSHIP_NS}">
      <Relationship Id="rIdImage" Type="{_RELATIONSHIP_NS}/image" Target="../media/image1.png"/>
    </Relationships>"""
    huge_number = "9" * 4_000
    crop_picture = _picture(
        object_id=3,
        relationship_id="rIdImage",
        alt_text="Adversarial crop",
        width_emu=_EMU_PER_INCH,
        height_emu=_EMU_PER_INCH,
        crop=(0, 0, 0, 0),
    ).replace('l="0"', f'l="{huge_number}"', 1)
    rotation_picture = _picture(
        object_id=4,
        relationship_id="rIdImage",
        alt_text="Adversarial rotation",
        width_emu=_EMU_PER_INCH,
        height_emu=_EMU_PER_INCH,
    ).replace("<a:xfrm>", f'<a:xfrm rot="{huge_number}">', 1)

    report = preflight_pptx(
        _pptx(
            _shape("Title", title=True) + crop_picture + rotation_picture,
            slide_relationships=image_relationships,
            extra_parts={"ppt/media/image1.png": _png(100, 100)},
        )
    )

    images = {item["path"]: item for item in report["image_quality"]["assessments"]}
    assert images["/slide[1]/picture[@id=3]"]["reason"] == "unsupported_crop_geometry"
    assert images["/slide[1]/picture[@id=4]"]["reason"] == "display_geometry_unavailable"
    geometry = {item["path"]: item for item in report["geometry_quality"]["assessments"]}
    assert geometry["/slide[1]/picture[@id=4]"] == {
        "slide_index": 1,
        "path": "/slide[1]/picture[@id=4]",
        "object_kind": "picture",
        "status": "unknown",
        "reason": "object_transform_unavailable",
    }


def test_preflight_bounds_findings_and_image_evidence() -> None:
    pictures = "".join(_picture(object_id=object_id) for object_id in range(2, 207))

    report = preflight_pptx(_pptx(pictures))

    assert report["summary"]["picture_count"] == 205
    assert report["summary"]["finding_count"] == 206
    assert report["summary"]["findings_returned"] == 200
    assert report["summary"]["findings_truncated"] is True
    assert report["image_quality"]["assessment_count"] == 205
    assert report["image_quality"]["assessments_returned"] == 200
    assert report["image_quality"]["assessments_truncated"] is True
    assert report["geometry_quality"]["assessment_count"] == 205
    assert report["geometry_quality"]["assessments_returned"] == 200
    assert report["geometry_quality"]["assessments_truncated"] is True


def test_preflight_reads_native_powerpoint_and_wps_roundtrip_corpus() -> None:
    for filename in ("powerpoint-16-v1.pptx", "wps-v1.pptx"):
        data = (_ROUNDTRIP_CORPUS / filename).read_bytes()

        report = preflight_pptx(data)

        assert report["source_sha256"] == hashlib.sha256(data).hexdigest()
        assert report["summary"]["slide_count"] == 13
        assert report["summary"]["findings_returned"] <= 200
        assert report["image_quality"]["assessments_returned"] <= 200
        assert report["visual_review_status"] == "not_performed"
        assert {check["id"]: check["status"] for check in report["checks"]}["geometry_bounds_and_overlap"] == "partial"

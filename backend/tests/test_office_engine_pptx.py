from __future__ import annotations

import copy
import hashlib
import io
import struct
import zipfile
import zlib

import pytest
from PIL import Image

import vassilflow.community.office.pptx as pptx_module
from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.errors import (
    OfficeOperationError,
    OfficePackageError,
)
from vassilflow.community.office.models import (
    DocxTextReplacement,
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
    PptxObjectSelector,
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
from vassilflow.community.office.pptx import (
    edit_pptx,
    inspect_pptx,
    validate_pptx,
    validate_pptx_renderable,
)

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>"""
_ROOT_RELATIONSHIPS = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""
_PRESENTATION = """<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rIdSecond"/>
    <p:sldId id="257" r:id="rIdFirst"/>
  </p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000"/>
</p:presentation>"""
_PRESENTATION_RELATIONSHIPS = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdFirst" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
  <Relationship Id="rIdSecond" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>
</Relationships>"""


def _png(*, color: tuple[int, int, int] = (68, 114, 196)) -> bytes:
    width = 4
    height = 3
    rows = b"".join(b"\x00" + bytes((*color, 255)) * width for _ in range(height))

    def chunk(chunk_type: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _jpeg(
    *,
    mode: str = "RGB",
    progressive: bool = False,
    exif_orientation: int | None = None,
) -> bytes:
    color: int | tuple[int, ...]
    if mode == "L":
        color = 128
    elif mode == "CMYK":
        color = (0, 128, 128, 0)
    else:
        color = (68, 114, 196)
    image = Image.new(mode, (4, 3), color)
    output = io.BytesIO()
    kwargs: dict[str, object] = {
        "format": "JPEG",
        "quality": 90,
        "progressive": progressive,
        "optimize": False,
    }
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        kwargs["exif"] = exif
    image.save(output, **kwargs)
    return output.getvalue()


def _shape(text: str, *, title: bool = False) -> str:
    placeholder = '<p:ph type="title"/>' if title else ""
    return f"""<p:sp>
      <p:nvSpPr><p:cNvPr id="2" name="Text"/><p:cNvSpPr/><p:nvPr>{placeholder}</p:nvPr></p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody>
    </p:sp>"""


def _formatted_shape() -> str:
    return """<p:sp>
      <p:nvSpPr><p:cNvPr id="7" name="Styled copy" descr="Accessible summary"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="100" y="200"/><a:ext cx="300" cy="400"/></a:xfrm>
        <a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>
        <a:solidFill><a:srgbClr val="336699"><a:alpha val="75000"/></a:srgbClr></a:solidFill>
        <a:ln w="25400" cap="rnd">
          <a:solidFill><a:schemeClr val="accent1"/></a:solidFill>
          <a:prstDash val="dash"/><a:round/>
        </a:ln>
      </p:spPr>
      <p:txBody>
        <a:bodyPr lIns="100" tIns="200" rIns="300" bIns="400" anchor="ctr" wrap="none" rtlCol="0">
          <a:normAutofit fontScale="92500" lnSpcReduction="12500"/>
        </a:bodyPr>
        <a:lstStyle/>
        <a:p>
          <a:pPr algn="ctr" marL="1000" indent="-500" rtl="0">
            <a:lnSpc><a:spcPct val="150000"/></a:lnSpc>
            <a:spcBef><a:spcPts val="1200"/></a:spcBef>
            <a:buChar char="&#x2022;"/>
          </a:pPr>
          <a:r>
            <a:rPr lang="en-US" sz="2400" b="1">
              <a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>
              <a:latin typeface="Aptos Display"/>
            </a:rPr>
            <a:t>Alpha</a:t>
          </a:r>
          <a:r>
            <a:rPr sz="1800" b="0" i="1" u="dbl" strike="sngStrike" spc="50" baseline="33000">
              <a:solidFill><a:srgbClr val="00FF00"><a:alpha val="50000"/></a:srgbClr></a:solidFill>
            </a:rPr>
            <a:t>Beta</a:t>
          </a:r>
          <a:br><a:rPr sz="1000"/></a:br>
          <a:tab/>
          <a:fld id="field-1" type="slidenum"><a:rPr sz="1200"/><a:t>42</a:t></a:fld>
        </a:p>
        <a:p>
          <a:pPr algn="r"><a:defRPr sz="1200" b="0"/></a:pPr>
          <a:endParaRPr sz="800" i="0"/>
        </a:p>
      </p:txBody>
    </p:sp>"""


def _formatted_gradient_shape(*, gradient_attributes: str = ' rotWithShape="1"') -> str:
    gradient = f"""<a:gradFill{gradient_attributes}>
          <a:gsLst>
            <a:gs pos="0"><a:srgbClr val="203864"/></a:gs>
            <a:gs pos="37500"><a:srgbClr val="4472C4"><a:alpha val="85000"/></a:srgbClr></a:gs>
            <a:gs pos="100000"><a:srgbClr val="70AD47"/></a:gs>
          </a:gsLst>
          <a:lin ang="2250000" scaled="1"/>
        </a:gradFill>"""
    return _formatted_shape().replace(
        '<a:solidFill><a:srgbClr val="336699"><a:alpha val="75000"/></a:srgbClr></a:solidFill>',
        gradient,
        1,
    )


def _matching_gradient_formatting() -> PptxShapeFillFormatting:
    return PptxShapeFillFormatting(
        type="gradient",
        stops=[
            PptxGradientStopFormatting(position_percent=0, color="203864"),
            PptxGradientStopFormatting(
                position_percent=37.5,
                color="4472C4",
                opacity_percent=85,
            ),
            PptxGradientStopFormatting(position_percent=100, color="70AD47"),
        ],
        geometry=PptxLinearGradientFormatting(
            angle_degrees=37.5,
            scaled=True,
        ),
        rotate_with_shape=True,
    )


def _formatted_path_gradient_shape() -> str:
    gradient = """<a:gradFill rotWithShape="0">
          <a:gsLst>
            <a:gs pos="0"><a:srgbClr val="FFFFFF"/></a:gs>
            <a:gs pos="35000"><a:srgbClr val="5B9BD5"><a:alpha val="90000"/></a:srgbClr></a:gs>
            <a:gs pos="100000"><a:srgbClr val="203864"/></a:gs>
          </a:gsLst>
          <a:path path="circle"><a:fillToRect l="35000" t="25000" r="65000" b="75000"/></a:path>
        </a:gradFill>"""
    return _formatted_shape().replace(
        '<a:solidFill><a:srgbClr val="336699"><a:alpha val="75000"/></a:srgbClr></a:solidFill>',
        gradient,
        1,
    )


def _matching_path_gradient_formatting() -> PptxShapeFillFormatting:
    return PptxShapeFillFormatting(
        type="gradient",
        stops=[
            PptxGradientStopFormatting(position_percent=0, color="FFFFFF"),
            PptxGradientStopFormatting(
                position_percent=35,
                color="5B9BD5",
                opacity_percent=90,
            ),
            PptxGradientStopFormatting(position_percent=100, color="203864"),
        ],
        geometry=PptxPathGradientFormatting(
            fill_to_rectangle=PptxGradientRectangleFormatting(
                left_percent=35,
                top_percent=25,
                right_percent=65,
                bottom_percent=75,
            )
        ),
        rotate_with_shape=False,
    )


def _formatted_pattern_shape() -> str:
    pattern = """<a:pattFill prst="diagCross">
          <a:fgClr><a:srgbClr val="4472C4"/></a:fgClr>
          <a:bgClr><a:srgbClr val="D9EAF7"/></a:bgClr>
        </a:pattFill>"""
    return _formatted_shape().replace(
        '<a:solidFill><a:srgbClr val="336699"><a:alpha val="75000"/></a:srgbClr></a:solidFill>',
        pattern,
        1,
    )


def _matching_pattern_formatting() -> PptxShapeFillFormatting:
    return PptxShapeFillFormatting(
        type="pattern",
        preset="diagCross",
        foreground_color="4472C4",
        background_color="D9EAF7",
    )


def _image_fill_shape(
    *,
    relationship_id: str = "rIdImage",
    rotate_with_shape: bool = False,
    crop: tuple[int, int, int, int] | None = (12_500, 5_000, 8_000, 10_000),
    framing: str | None = None,
) -> str:
    source_rectangle = ""
    if crop is not None:
        source_rectangle = f'<a:srcRect l="{crop[0]}" t="{crop[1]}" r="{crop[2]}" b="{crop[3]}"/>'
    framing_xml = framing or "<a:stretch><a:fillRect/></a:stretch>"
    image_fill = f'<a:blipFill rotWithShape="{int(rotate_with_shape)}"><a:blip r:embed="{relationship_id}"/>{source_rectangle}{framing_xml}</a:blipFill>'
    return _formatted_shape().replace(
        '<a:solidFill><a:srgbClr val="336699"><a:alpha val="75000"/></a:srgbClr></a:solidFill>',
        image_fill,
        1,
    )


def _image_fill_formatting(
    *,
    path: str = "/mnt/user-data/uploads/replacement.png",
    rotate_with_shape: bool = False,
    crop: PptxImageCropFormatting | None = None,
) -> PptxShapeFillFormatting:
    return PptxShapeFillFormatting(
        type="image",
        image_path=path,
        rotate_with_shape=rotate_with_shape,
        crop=(
            crop
            if crop is not None
            else PptxImageCropFormatting(
                left_percent=12.5,
                top_percent=5,
                right_percent=8,
                bottom_percent=10,
            )
        ),
    )


def _formatted_connector(*, object_id: int = 9, name: str = "Authored connector") -> str:
    return f"""<p:cxnSp>
      <p:nvCxnSpPr><p:cNvPr id="{object_id}" name="{name}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>
      <p:spPr>
        <a:xfrm><a:off x="500" y="600"/><a:ext cx="700" cy="800"/></a:xfrm>
        <a:prstGeom prst="line"><a:avLst/></a:prstGeom>
        <a:ln w="38100" cap="rnd" cmpd="dbl" algn="ctr">
          <a:solidFill><a:srgbClr val="4472C4"/></a:solidFill>
          <a:prstDash val="dash"/><a:miter lim="800000"/>
          <a:headEnd type="diamond" w="sm" len="med"/>
          <a:tailEnd type="triangle" w="lg" len="lg"/>
        </a:ln>
      </p:spPr>
    </p:cxnSp>"""


def _slide(
    body: str,
    *,
    hidden: bool = False,
    name: str | None = None,
    show_master_shapes: bool | None = None,
    background: str = "",
    after_common_slide: str = "",
) -> str:
    show = ' show="0"' if hidden else ""
    master_shapes = "" if show_master_shapes is None else f' showMasterSp="{int(show_master_shapes)}"'
    common_slide_name = "" if name is None else f' name="{name}"'
    return f"""<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"{show}{master_shapes}>
      <p:cSld{common_slide_name}>{background}<p:spTree>
        <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
        {body}
      </p:spTree></p:cSld>
      {after_common_slide}
    </p:sld>"""


def _pptx(
    *,
    slide1: str | None = None,
    slide2: str | None = None,
    slide1_relationships: str | None = None,
    slide2_relationships: str | None = None,
    root_relationships: str = _ROOT_RELATIONSHIPS,
    presentation_relationships: str = _PRESENTATION_RELATIONSHIPS,
    content_types: str = _CONTENT_TYPES,
    extra_parts: dict[str, str] | None = None,
) -> bytes:
    table = """<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="4" name="Table"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr/><a:tblGrid/>
        <a:tr h="1"><a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>North</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc></a:tr>
      </a:tbl></a:graphicData></a:graphic>
    </p:graphicFrame>"""
    chart = """<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="Chart"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"/></a:graphic>
    </p:graphicFrame>"""
    group = f"""<p:grpSp><p:nvGrpSpPr><p:cNvPr id="3" name="Group"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{_shape("Grouped copy")}</p:grpSp>"""
    picture = """<p:pic><p:nvPicPr><p:cNvPr id="6" name="Image" descr="Useful diagram"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill/><p:spPr/></p:pic>"""
    slide1 = slide1 or _slide(_shape("First file", title=True))
    slide2 = slide2 or _slide(
        _shape("Second in declared order", title=True) + group + table + chart + picture,
        hidden=True,
    )
    slide1_relationships = (
        slide1_relationships
        or """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdNotes" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
    </Relationships>"""
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("ppt/presentation.xml", _PRESENTATION)
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            presentation_relationships,
        )
        archive.writestr("ppt/slides/slide1.xml", slide1)
        archive.writestr("ppt/slides/slide2.xml", slide2)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", slide1_relationships)
        if slide2_relationships is not None:
            archive.writestr("ppt/slides/_rels/slide2.xml.rels", slide2_relationships)
        archive.writestr("ppt/notesSlides/notesSlide1.xml", "<notes/>")
        for part_name, payload in (extra_parts or {}).items():
            archive.writestr(part_name, payload)
    return output.getvalue()


def _resource_pptx() -> bytes:
    slide = _slide(
        """<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="Revenue chart"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm/>
          <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><a:chart r:id="rIdChart"/></a:graphicData></a:graphic>
        </p:graphicFrame>
        <p:pic><p:nvPicPr><p:cNvPr id="6" name="Logo"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rIdImage"/></p:blipFill><p:spPr/></p:pic>
        <p:sp><p:nvSpPr><p:cNvPr id="7" name="Website"><a:hlinkClick r:id="rIdLink"/></p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/></p:sp>"""
    )
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdLayout" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
      <Relationship Id="rIdChart" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/>
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
      <Relationship Id="rIdLink" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.test/report" TargetMode="External"/>
    </Relationships>"""
    layout_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdMaster" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../custom/master.xml"/>
    </Relationships>"""
    master_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdLayoutBack" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout2.xml"/>
      <Relationship Id="rIdTheme" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
    </Relationships>"""
    chart_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdData" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" Target="../embeddings/book1.xlsx"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/custom/master.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/ppt/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>
</Types>""",
    )
    return _pptx(
        slide2=slide,
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={
            "ppt/slideLayouts/slideLayout1.xml": "<layout/>",
            "ppt/slideLayouts/slideLayout2.xml": "<layout/>",
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": layout_relationships,
            "ppt/custom/master.xml": "<master/>",
            "ppt/custom/_rels/master.xml.rels": master_relationships,
            "ppt/theme/theme1.xml": "<theme/>",
            "ppt/charts/chart1.xml": "<chart/>",
            "ppt/charts/_rels/chart1.xml.rels": chart_relationships,
            "ppt/embeddings/book1.xlsx": "workbook-bytes",
            "ppt/media/image1.png": "image-bytes",
        },
    )


def _metadata_interactions_pptx() -> bytes:
    background = """<p:bg><p:bgPr shadeToTitle="0"><a:solidFill><a:srgbClr val="112233"/></a:solidFill></p:bgPr></p:bg>"""
    picture = """<p:pic>
      <p:nvPicPr><p:cNvPr id="20" name="Hero image" descr="Product overview"><a:hlinkClick r:id="rIdWebsite" tooltip="Open product page"/></p:cNvPr><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
      <p:blipFill dpi="144" rotWithShape="0">
        <a:blip r:embed="rIdImage" cstate="print">
          <a:alphaModFix amt="75000"/>
          <a:lum bright="15000" contrast="-20000"/>
          <a:grayscl/>
          <a:biLevel thresh="50000"/>
          <a:duotone><a:srgbClr val="000000"/><a:schemeClr val="accent2"/></a:duotone>
        </a:blip>
        <a:srcRect l="10000" t="5000" r="-2500" b="0"/>
        <a:stretch><a:fillRect l="1000" t="2000" r="3000" b="4000"/></a:stretch>
      </p:blipFill>
      <p:spPr><a:xfrm><a:off x="10" y="20"/><a:ext cx="30" cy="40"/></a:xfrm></p:spPr>
    </p:pic>"""
    linked_shape = """<p:sp>
      <p:nvSpPr><p:cNvPr id="21" name="Linked copy"><a:hlinkHover r:id="" action="ppaction://hlinkshowjump?jump=nextslide" tooltip="Preview next slide"/></p:cNvPr><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
      <p:spPr/>
      <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr>
        <a:hlinkClick r:id="rIdTarget" action="ppaction://hlinksldjump" tooltip="Open details"/>
        <a:hlinkMouseOver r:id="rIdWebsite" tooltip="Preview website"/>
      </a:rPr><a:t>Details</a:t></a:r></a:p></p:txBody>
    </p:sp>"""
    slide = _slide(
        picture + linked_shape,
        name="Quarterly review",
        show_master_shapes=False,
        background=background,
    )
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdLayout" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
      <Relationship Id="rIdWebsite" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.test/product" TargetMode="External"/>
      <Relationship Id="rIdTarget" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slide1.xml"/>
    </Relationships>"""
    layout = """<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="title" matchingName="Fallback layout"><p:cSld name="Editorial layout"><p:spTree/></p:cSld></p:sldLayout>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
</Types>""",
    )
    return _pptx(
        slide2=slide,
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={
            "ppt/slideLayouts/slideLayout1.xml": layout,
            "ppt/media/image1.png": "image-bytes",
        },
    )


def _picture_source_pptx(
    *,
    primary_picture: str | None = None,
    secondary_picture: str | None = None,
    relationships: str | None = None,
    source_payload: bytes | None = None,
) -> bytes:
    primary = (
        primary_picture
        if primary_picture is not None
        else """<p:pic>
      <p:nvPicPr>
        <p:cNvPr id="20" name="Hero image" descr="Product overview" title="Hero title"/>
        <p:cNvPicPr preferRelativeResize="0"><a:picLocks noChangeAspect="1"/></p:cNvPicPr>
        <p:nvPr><p:ph idx="2"/></p:nvPr>
      </p:nvPicPr>
      <p:blipFill dpi="144" rotWithShape="0">
        <a:blip r:embed="rIdImage" cstate="print">
          <a:alphaModFix amt="75000"/>
          <a:lum bright="15000" contrast="-20000"/>
          <a:grayscl/>
        </a:blip>
        <a:srcRect l="10000" t="5000" r="-2500" b="0"/>
        <a:stretch><a:fillRect l="1000" t="2000" r="3000" b="4000"/></a:stretch>
      </p:blipFill>
      <p:spPr bwMode="auto">
        <a:xfrm rot="60000" flipH="1"><a:off x="10" y="20"/><a:ext cx="30" cy="40"/></a:xfrm>
        <a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>
        <a:ln w="12700"><a:solidFill><a:srgbClr val="4472C4"/></a:solidFill></a:ln>
      </p:spPr>
    </p:pic>"""
    )
    secondary = (
        secondary_picture
        if secondary_picture is not None
        else """<p:pic>
      <p:nvPicPr><p:cNvPr id="22" name="Shared source" descr="Peer picture"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
      <p:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
      <p:spPr><a:xfrm><a:off x="50" y="60"/><a:ext cx="70" cy="80"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
    </p:pic>"""
    )
    slide_relationships = (
        relationships
        or """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
    </Relationships>"""
    )
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
</Types>""",
    )
    return _pptx(
        slide2=_slide(primary + secondary),
        slide2_relationships=slide_relationships,
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": source_payload or _png()},
    )


def _picture_preservation_view(record: dict[str, object]) -> dict[str, object]:
    preserved = copy.deepcopy(record)
    source = preserved.pop("source")
    assert isinstance(source, dict)
    relationship_id = source["relationship_id"]
    relationship_ids = preserved.get("relationship_ids")
    if isinstance(relationship_ids, list):
        preserved["relationship_ids"] = ["<picture-source>" if item == relationship_id else item for item in relationship_ids]
    style = preserved.get("style")
    if isinstance(style, dict):
        picture_style = style.get("picture")
        if isinstance(picture_style, dict):
            picture_relationships = picture_style.get("relationship_ids")
            if isinstance(picture_relationships, list):
                picture_style["relationship_ids"] = ["<picture-source>" if item == relationship_id else item for item in picture_relationships]
    return preserved


def _annotations_pptx(
    *,
    legacy_author_id: str = "0",
    legacy_comment_author_id: str = "0",
) -> bytes:
    slide_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdNotes" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide2.xml"/>
      <Relationship Id="rIdLegacyComments" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="../comments/comment1.xml"/>
      <Relationship Id="rIdModernComments" Type="http://schemas.microsoft.com/office/2018/10/relationships/comments" Target="../comments/modernComment1.xml"/>
    </Relationships>"""
    presentation_relationships = _PRESENTATION_RELATIONSHIPS.replace(
        "</Relationships>",
        """  <Relationship Id="rIdLegacyAuthors" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/commentAuthors" Target="commentAuthors.xml"/>
  <Relationship Id="rIdModernAuthors" Type="http://schemas.microsoft.com/office/2018/10/relationships/authors" Target="authors.xml"/>
</Relationships>""",
    )
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Override PartName="/ppt/notesSlides/notesSlide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>
  <Override PartName="/ppt/comments/comment1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.comments+xml"/>
  <Override PartName="/ppt/commentAuthors.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml"/>
  <Override PartName="/ppt/comments/modernComment1.xml" ContentType="application/vnd.ms-powerpoint.comments+xml"/>
  <Override PartName="/ppt/authors.xml" ContentType="application/vnd.ms-powerpoint.authors+xml"/>
</Types>""",
    )
    notes = """<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:cSld><p:spTree>
        <p:nvGrpSpPr/><p:grpSpPr/>
        <p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide image"/><p:cNvSpPr/><p:nvPr><p:ph type="sldImg" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Not speaker notes</a:t></a:r></a:p></p:txBody></p:sp>
        <p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes body"/><p:cNvSpPr/><p:nvPr><p:ph type="body" idx="7"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody>
          <a:bodyPr/><a:lstStyle/>
          <a:p><a:pPr rtl="0"/><a:r><a:rPr b="1"/><a:t>Review</a:t></a:r><a:br/><a:tab/><a:fld id="f1" type="datetime"><a:t>today</a:t></a:fld></a:p>
          <a:p><a:r><a:t>Second paragraph</a:t></a:r></a:p>
        </p:txBody></p:sp>
      </p:spTree></p:cSld>
    </p:notes>"""
    legacy_authors = """<p:cmAuthorLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
      <p:cmAuthor id="0" name="Alice Reviewer" initials="AR" lastIdx="3" clrIdx="0"/>
    </p:cmAuthorLst>""".replace('id="0"', f'id="{legacy_author_id}"')
    legacy_comments = """<p:cmLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
      <p:cm authorId="0" dt="2026-07-14T01:02:03Z" idx="3"><p:pos x="120" y="340"/><p:text>Legacy review</p:text></p:cm>
    </p:cmLst>""".replace(
        'authorId="0"',
        f'authorId="{legacy_comment_author_id}"',
    )
    modern_authors = """<p188:authorLst xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/8/main">
      <p188:author id="{AUTHOR-1}" name="Bob Reviewer" initials="BR"/>
    </p188:authorLst>"""
    modern_comments = """<p188:cmLst xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/8/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p188:cm id="{THREAD-1}" authorId="{AUTHOR-1}" created="2026-07-14T02:03:04Z" status="resolved">
        <p188:pos x="10" y="20"/>
        <p188:txBody><a:bodyPr/><a:p><a:r><a:t>Thread review</a:t></a:r></a:p></p188:txBody>
        <p188:replyLst><p188:reply id="{REPLY-1}" authorId="{AUTHOR-1}" created="2026-07-14T03:04:05Z">
          <p188:txBody><a:bodyPr/><a:p><a:r><a:t>Reply review</a:t></a:r></a:p></p188:txBody>
        </p188:reply></p188:replyLst>
      </p188:cm>
    </p188:cmLst>"""
    return _pptx(
        slide2_relationships=slide_relationships,
        presentation_relationships=presentation_relationships,
        content_types=content_types,
        extra_parts={
            "ppt/notesSlides/notesSlide2.xml": notes,
            "ppt/commentAuthors.xml": legacy_authors,
            "ppt/comments/comment1.xml": legacy_comments,
            "ppt/authors.xml": modern_authors,
            "ppt/comments/modernComment1.xml": modern_comments,
        },
    )


def _dynamics_pptx(
    *,
    wrapper_delay: str = "250",
    build_markup: str = '<p:bldP spid="7" grpId="42" build="p"/>',
) -> bytes:
    transition = """<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:p159="http://schemas.microsoft.com/office/powerpoint/2015/09/main">
      <mc:Choice Requires="future" xmlns:future="urn:vassilflow:test:unsupported"><p:transition><future:warp/></p:transition></mc:Choice>
      <mc:Choice Requires="p159"><p:transition spd="slow" p14:dur="900" advTm="2500" advClick="0" xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"><p159:morph option="byWord"/></p:transition></mc:Choice>
      <mc:Fallback><p:transition><p:fade thruBlk="1"/></p:transition></mc:Fallback>
    </mc:AlternateContent>"""
    timing = """<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" nodeType="tmRoot"><p:childTnLst>
      <p:par><p:cTn id="2"><p:stCondLst><p:cond delay="250"/></p:stCondLst><p:childTnLst>
        <p:par><p:cTn id="3" grpId="42" presetID="19" presetClass="entr"><p:childTnLst>
          <p:animEffect filter="wheel"><p:cBhvr><p:cTn id="4" dur="750"/><p:tgtEl><p:spTgt spid="7"><p:subSp><p:chart bldStep="gridLegend"/></p:subSp></p:spTgt></p:tgtEl></p:cBhvr></p:animEffect>
        </p:childTnLst></p:cTn></p:par>
        <p:par><p:cTn id="7" grpId="42" presetID="10" presetClass="entr" presetSubtype="8" repeatCount="3000" autoRev="1" nodeType="withEffect" accel="25000" decel="10000" restart="whenNotActive"><p:childTnLst>
          <p:animEffect filter="fade"><p:cBhvr><p:cTn id="8" dur="750"/><p:tgtEl><p:spTgt spid="7"/></p:tgtEl></p:cBhvr></p:animEffect>
        </p:childTnLst></p:cTn></p:par>
      </p:childTnLst></p:cTn></p:par>
      <p:par><p:cTn id="5" presetClass="path" nodeType="clickEffect"><p:childTnLst>
        <p:animMotion path="M 0 0 L 1 1 E"><p:cBhvr><p:cTn id="6" dur="500"/><p:tgtEl><p:spTgt spid="99"/></p:tgtEl></p:cBhvr></p:animMotion>
      </p:childTnLst></p:cTn></p:par>
    </p:childTnLst></p:cTn></p:par></p:tnLst><p:bldLst><p:bldP spid="7" grpId="42" build="p"/></p:bldLst></p:timing>"""
    timing = timing.replace('delay="250"', f'delay="{wrapper_delay}"', 1)
    timing = timing.replace(
        '<p:bldP spid="7" grpId="42" build="p"/>',
        build_markup,
        1,
    )
    slide = _slide(
        _formatted_shape(),
        after_common_slide=transition + timing,
    )
    return _pptx(slide2=slide)


def test_inspect_pptx_uses_declared_slide_order_and_bounded_visible_text() -> None:
    inspected = inspect_pptx(_pptx(), max_slides=1)

    assert inspected["format"] == "pptx"
    assert inspected["slide_count"] == 2
    assert inspected["slide_size"]["width_inches"] == 13.3333
    assert inspected["returned"] == 1
    assert inspected["has_more"] is True
    assert inspected["slides"][0]["part_name"] == "ppt/slides/slide2.xml"
    assert inspected["slides"][0]["title"] == "Second in declared order"
    assert inspected["slides"][0]["hidden"] is True
    assert inspected["slides"][0]["show_master_shapes"] is True
    assert inspected["slides"][0]["show_master_shapes_authored"] is False
    assert [item["text"] for item in inspected["slides"][0]["text"]] == [
        "Second in declared order",
        "Grouped copy",
        "North",
    ]
    assert inspected["slides"][0]["inventory"] == {
        "shapes": 2,
        "text_boxes": 2,
        "pictures": 1,
        "pictures_without_alt_text": 0,
        "tables": 1,
        "charts": 1,
        "groups": 1,
        "connectors": 0,
        "ole_objects": 0,
        "has_notes": False,
        "has_legacy_comments": False,
        "has_modern_comments": False,
        "has_timing": False,
    }


def test_inspect_pptx_annotations_are_opt_in_and_preserve_typed_paths() -> None:
    source = _annotations_pptx()

    default = inspect_pptx(source, max_slides=1)

    assert default["annotations_included"] is False
    assert "notes" not in default["slides"][0]
    assert "comments" not in default["slides"][0]
    assert default["slides"][0]["inventory"]["has_notes"] is True
    assert default["slides"][0]["inventory"]["has_legacy_comments"] is True
    assert default["slides"][0]["inventory"]["has_modern_comments"] is True

    inspected = inspect_pptx(
        source,
        max_slides=1,
        include_annotations=True,
        include_formatting=True,
    )
    slide = inspected["slides"][0]
    notes = slide["notes"]

    assert inspected["annotations_included"] is True
    assert inspected["selected_annotation_count"] == 4
    assert inspected["selected_annotations_returned"] == 4
    assert inspected["selected_annotations_truncated"] is False
    assert notes["path"] == "/slide[1]/notes"
    assert notes["body_found"] is True
    assert notes["text"] == "Review\n\ttoday\nSecond paragraph"
    assert notes["paragraph_count"] == 2
    assert [segment["kind"] for segment in notes["text_body"]["paragraphs"][0]["segments"]] == ["run", "line_break", "tab", "field"]
    assert notes["text_body"]["paragraphs"][0]["segments"][0]["formatting"]["bold"] is True

    comments = slide["comments"]
    assert comments["legacy_count"] == 1
    assert comments["modern_thread_count"] == 1
    assert comments["modern_reply_count"] == 1
    assert comments["returned"] == 3
    assert comments["truncated"] is False
    legacy, thread, reply = comments["items"]
    assert legacy == {
        "path": "/slide[1]/comment[@author_id=0][@index=3]",
        "type": "comment",
        "part_name": "ppt/comments/comment1.xml",
        "text": "Legacy review",
        "author_id": "0",
        "author": "Alice Reviewer",
        "initials": "AR",
        "author_resolved": True,
        "authored_index": 3,
        "created": "2026-07-14T01:02:03Z",
        "position": {"x_emu": 120, "y_emu": 340},
    }
    assert thread["path"] == "/slide[1]/comment_thread[@id=%7BTHREAD-1%7D]"
    assert thread["type"] == "comment_thread"
    assert thread["parent_path"] is None
    assert thread["text"] == "Thread review"
    assert thread["author"] == "Bob Reviewer"
    assert thread["resolved"] is True
    assert thread["position"] == {"x_emu": 10, "y_emu": 20}
    assert reply["path"] == "/slide[1]/comment_thread[@id=%7BTHREAD-1%7D]/reply[@id=%7BREPLY-1%7D]"
    assert reply["type"] == "comment_reply"
    assert reply["parent_path"] == "/slide[1]/comment_thread[@id=%7BTHREAD-1%7D]"
    assert reply["text"] == "Reply review"


def test_inspect_pptx_transition_and_animation_metadata_is_typed() -> None:
    source = _dynamics_pptx()

    default = inspect_pptx(source, max_slides=1)
    assert default["dynamics_included"] is False
    assert "animations" not in default["slides"][0]

    inspected = inspect_pptx(
        source,
        max_slides=1,
        include_dynamics=True,
    )
    slide = inspected["slides"][0]

    assert slide["transition"] == {
        "path": "/slide[1]/transition",
        "source": "markup_compatibility_choice",
        "effect": "morph",
        "schema": "extension_2015",
        "option": "by_word",
        "speed": "slow",
        "duration_ms": 900,
        "advance_after_ms": 2500,
        "advance_on_click": False,
        "fallback": {
            "path": "/slide[1]/transition/fallback",
            "source": "markup_compatibility_fallback",
            "effect": "fade",
            "schema": "standard",
            "through_black": True,
        },
    }
    assert slide["inventory"]["has_timing"] is True
    assert slide["animation_count"] == 2
    assert slide["animations_returned"] == 2
    assert slide["animations_truncated"] is False
    assert inspected["selected_animation_count"] == 2
    assert inspected["selected_animations_returned"] == 2
    assert inspected["selected_animations_truncated"] is False

    effect, motion = slide["animations"]
    assert effect == {
        "path": "/slide[1]/shape[@id=7]/animation[@timing_id=7]",
        "target_path": "/slide[1]/shape[@id=7]",
        "target_resolved": True,
        "preset_class": "entrance",
        "timing_node_id": 7,
        "group_id": 42,
        "target_shape_id": 7,
        "preset_id": 10,
        "preset_subtype": 8,
        "effect": "fade",
        "filter": "fade",
        "direction": "left",
        "duration_ms": 750,
        "trigger": "with_previous",
        "delay_ms": 250,
        "ease_in_percent": 25.0,
        "ease_out_percent": 10.0,
        "repeat_count": 3.0,
        "auto_reverse": True,
        "restart": "when_not_active",
        "paragraph_build": "p",
    }
    assert motion == {
        "path": "/slide[1]/animation[@timing_id=5]",
        "target_path": None,
        "target_resolved": False,
        "preset_class": "path",
        "timing_node_id": 5,
        "target_shape_id": 99,
        "effect": "motion_path",
        "duration_ms": 500,
        "trigger": "on_click",
        "motion_path": "M 0 0 L 1 1 E",
    }


def test_inspect_pptx_uses_nearest_animation_delay_and_typed_chart_build() -> None:
    no_delay = inspect_pptx(
        _dynamics_pptx(wrapper_delay="0"),
        max_slides=1,
        include_dynamics=True,
    )
    assert "delay_ms" not in no_delay["slides"][0]["animations"][0]

    chart_build = inspect_pptx(
        _dynamics_pptx(build_markup=('<p:bldGraphic spid="7"><p:bldSub><a:bldChart xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" bld="seriesEl"/></p:bldSub></p:bldGraphic>')),
        max_slides=1,
        include_dynamics=True,
    )
    assert chart_build["slides"][0]["animations"][0]["chart_build"] == "series_elements"


def test_inspect_pptx_marks_truncated_unknown_transition_values() -> None:
    direction = "X" * 80
    source = _pptx(
        slide2=_slide(
            _formatted_shape(),
            after_common_slide=(f'<p:transition><p:push dir="{direction}"/></p:transition>'),
        )
    )

    transition = inspect_pptx(source, max_slides=1)["slides"][0]["transition"]
    assert transition["direction"] == "x" * 64
    assert transition["direction_truncated"] is True


def test_inspect_pptx_annotation_and_animation_budgets_are_explicit(
    monkeypatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_ANNOTATIONS", 1)
    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_ANNOTATION_CHARS", 5)

    annotations = inspect_pptx(
        _annotations_pptx(),
        max_slides=1,
        include_annotations=True,
    )

    assert annotations["slides"][0]["notes"]["text"] == "Revie"
    assert annotations["slides"][0]["notes"]["text_truncated"] is True
    assert annotations["slides"][0]["comments"]["returned"] == 1
    assert annotations["slides"][0]["comments"]["truncated"] is True
    assert annotations["selected_annotation_count"] == 4
    assert annotations["selected_annotations_returned"] == 2
    assert annotations["selected_annotations_truncated"] is True

    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_ANIMATIONS", 1)
    dynamics = inspect_pptx(
        _dynamics_pptx(),
        max_slides=1,
        include_dynamics=True,
    )

    assert dynamics["slides"][0]["animation_count"] == 2
    assert dynamics["slides"][0]["animations_returned"] == 1
    assert dynamics["slides"][0]["animations_truncated"] is True
    assert dynamics["selected_animations_truncated"] is True

    monkeypatch.setattr(
        pptx_module,
        "_MAX_ANIMATION_TARGETS_PER_SLIDE",
        1,
    )
    source_bounded = inspect_pptx(
        _dynamics_pptx(),
        max_slides=1,
        include_dynamics=True,
    )
    assert source_bounded["slides"][0]["animation_count"] == 1
    assert source_bounded["slides"][0]["animation_count_truncated"] is True
    assert source_bounded["selected_animation_count_truncated"] is True
    assert source_bounded["selected_animations_truncated"] is True


def test_inspect_pptx_annotation_source_scan_and_author_maps_are_bounded(
    monkeypatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_ANNOTATION_SCAN_ITEMS", 1)
    monkeypatch.setattr(pptx_module, "_MAX_ANNOTATION_AUTHORS", 1)

    inspected = inspect_pptx(
        _annotations_pptx(legacy_author_id="00"),
        max_slides=1,
        include_annotations=True,
    )

    comments = inspected["slides"][0]["comments"]
    assert comments["legacy_count"] == 1
    assert comments["modern_thread_count"] == 0
    assert comments["modern_reply_count"] == 0
    assert comments["scanned"] == 1
    assert comments["count_truncated"] is True
    assert comments["scan_truncated"] is True
    assert comments["authors_truncated"] is True
    assert comments["truncated"] is True
    assert comments["items"][0]["author_id"] == "0"
    assert comments["items"][0]["author_resolved"] is True
    assert inspected["selected_annotation_count"] == 2
    assert inspected["selected_annotation_count_truncated"] is True
    assert inspected["selected_annotation_authors_truncated"] is True
    assert inspected["selected_annotations_truncated"] is True


def test_inspect_pptx_validates_annotation_parts_only_when_requested() -> None:
    source = _pptx()

    assert inspect_pptx(source, start_slide=2, max_slides=1)["annotations_included"] is False
    with pytest.raises(
        OfficePackageError,
        match="unexpected annotation content type",
    ):
        inspect_pptx(
            source,
            start_slide=2,
            max_slides=1,
            include_annotations=True,
        )


def test_inspect_pptx_reports_slide_metadata_interactions_and_picture_formatting() -> None:
    inspected = inspect_pptx(
        _metadata_interactions_pptx(),
        max_slides=1,
        include_formatting=True,
    )
    slide = inspected["slides"][0]

    assert slide["name"] == "Quarterly review"
    assert slide["layout"] == {
        "part_name": "ppt/slideLayouts/slideLayout1.xml",
        "type": "title",
        "name": "Editorial layout",
        "name_source": "common_slide_data",
    }
    assert slide["show_master_shapes"] is False
    assert slide["show_master_shapes_authored"] is True
    assert slide["background"] == {
        "scope": "direct",
        "type": "solid",
        "color": {"type": "rgb", "value": "#112233"},
        "shade_to_title": False,
    }
    assert slide["interaction_count"] == 4
    assert slide["matched_interaction_count"] == 4
    assert slide["interactions_returned"] == 4
    assert slide["interactions_truncated"] is False
    assert inspected["selected_interaction_count"] == 4
    assert inspected["selected_matched_interaction_count"] == 4
    assert inspected["selected_interactions_returned"] == 4
    assert inspected["selected_interactions_truncated"] is False

    picture, shape = slide["objects"]
    assert picture["source"] == {
        "relationship_id": "rIdImage",
        "part_name": "ppt/media/image1.png",
        "content_type": "image/png",
        "size_bytes": len("image-bytes"),
        "sha256": hashlib.sha256(b"image-bytes").hexdigest(),
    }
    assert picture["style"]["picture"] == {
        "dpi": 144,
        "rotate_with_shape": False,
        "crop": {
            "left_percent": 10.0,
            "top_percent": 5.0,
            "right_percent": -2.5,
            "bottom_percent": 0.0,
        },
        "fill_mode": "stretch",
        "fill_rectangle": {
            "left_percent": 1.0,
            "top_percent": 2.0,
            "right_percent": 3.0,
            "bottom_percent": 4.0,
        },
        "relationship_ids": ["rIdImage"],
        "compression_state": "print",
        "effects": {
            "alpha_modulation_percent": 75.0,
            "brightness_percent": 15.0,
            "contrast_percent": -20.0,
            "grayscale": True,
            "bilevel_threshold_percent": 50.0,
            "duotone_colors": [
                {"type": "rgb", "value": "#000000"},
                {"type": "scheme", "value": "accent2"},
            ],
        },
    }
    assert picture["interactions"] == [
        {
            "owner_path": "/slide[1]/picture[@id=20]",
            "trigger": "click",
            "tooltip": "Open product page",
            "relationship_id": "rIdWebsite",
            "target_kind": "external_url",
            "target": "https://example.test/product",
        }
    ]
    assert shape["interaction_count"] == 3
    assert shape["interactions"] == [
        {
            "owner_path": "/slide[1]/shape[@id=21]",
            "trigger": "hover",
            "tooltip": "Preview next slide",
            "action": "ppaction://hlinkshowjump?jump=nextslide",
            "target_kind": "show_navigation",
            "target": "next_slide",
        },
        {
            "owner_path": "/slide[1]/shape[@id=21]/paragraph[1]/run[1]",
            "trigger": "click",
            "tooltip": "Open details",
            "relationship_id": "rIdTarget",
            "action": "ppaction://hlinksldjump",
            "part_name": "ppt/slides/slide1.xml",
            "target_kind": "slide",
            "target": "/slide[2]",
        },
        {
            "owner_path": "/slide[1]/shape[@id=21]/paragraph[1]/run[1]",
            "trigger": "hover",
            "tooltip": "Preview website",
            "relationship_id": "rIdWebsite",
            "target_kind": "external_url",
            "target": "https://example.test/product",
        },
    ]


def test_edit_pptx_replaces_only_picture_source_and_preserves_shared_rich_metadata() -> None:
    source = _picture_source_pptx()
    before_objects = {
        item["name"]: item
        for item in inspect_pptx(
            source,
            max_slides=1,
            include_formatting=True,
        )["slides"][0]["objects"]
    }
    primary = before_objects["Hero image"]
    peer = before_objects["Shared source"]
    same_source_path = "/mnt/user-data/uploads/same-source.png"
    same_source = _png()
    no_op_operation = PptxPictureSourceReplacementOperation(
        pictures=PptxPictureSelector(
            targets=[
                PptxPictureTarget(
                    path=primary["path"],
                    expected_name=primary["name"],
                    expected_source_sha256=primary["source"]["sha256"],
                )
            ]
        ),
        image_path=same_source_path,
    )

    no_op, no_op_reports = edit_pptx(
        source,
        [no_op_operation],
        image_assets={same_source_path: same_source},
    )

    assert no_op == source
    assert no_op_reports[0]["match_count"] == 1

    replacement_path = "/mnt/user-data/uploads/replacement.jpg"
    replacement = _jpeg()
    operation = PptxPictureSourceReplacementOperation(
        pictures=PptxPictureSelector(
            targets=[
                PptxPictureTarget(
                    path=primary["path"],
                    expected_name=primary["name"],
                    expected_source_sha256=primary["source"]["sha256"],
                )
            ]
        ),
        image_path=replacement_path,
    )

    edited, reports = edit_pptx(
        source,
        [operation],
        image_assets={replacement_path: replacement},
    )

    assert reports == [
        {
            "operation": 1,
            "type": "replace_pptx_picture_sources",
            "match_count": 1,
            "matched_paths": [primary["path"]],
            "matched_paths_truncated": False,
        }
    ]
    assert validate_pptx(edited)["valid"] is True
    after_objects = {
        item["name"]: item
        for item in inspect_pptx(
            edited,
            max_slides=1,
            include_formatting=True,
        )["slides"][0]["objects"]
    }
    changed = after_objects["Hero image"]
    assert after_objects["Shared source"] == peer
    assert _picture_preservation_view(changed) == _picture_preservation_view(primary)
    assert changed["source"] == {
        "relationship_id": "rId1",
        "part_name": "ppt/media/image2.jpg",
        "content_type": "image/jpeg",
        "size_bytes": len(replacement),
        "sha256": hashlib.sha256(replacement).hexdigest(),
    }
    assert after_objects["Shared source"]["source"] == primary["source"]

    with (
        zipfile.ZipFile(io.BytesIO(source)) as source_archive,
        zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
    ):
        source_names = set(source_archive.namelist())
        edited_names = set(edited_archive.namelist())
        assert edited_names - source_names == {"ppt/media/image2.jpg"}
        assert edited_archive.read("ppt/media/image1.png") == same_source
        assert edited_archive.read("ppt/media/image2.jpg") == replacement
        changed_parts = {name for name in source_names if source_archive.read(name) != edited_archive.read(name)}
    assert changed_parts == {
        "ppt/slides/_rels/slide2.xml.rels",
        "ppt/slides/slide2.xml",
    }

    with pytest.raises(
        OfficeOperationError,
        match="expected_source_sha256 no longer matches",
    ):
        edit_pptx(
            edited,
            [operation],
            image_assets={replacement_path: replacement},
        )

    refreshed_operation = PptxPictureSourceReplacementOperation(
        pictures=PptxPictureSelector(
            targets=[
                PptxPictureTarget(
                    path=changed["path"],
                    expected_name=changed["name"],
                    expected_source_sha256=changed["source"]["sha256"],
                )
            ]
        ),
        image_path=replacement_path,
    )
    refreshed, _ = edit_pptx(
        edited,
        [refreshed_operation],
        image_assets={replacement_path: replacement},
    )
    assert refreshed == edited


def test_edit_pptx_picture_replacement_preflights_all_name_and_digest_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _picture_source_pptx()
    objects = {item["name"]: item for item in inspect_pptx(source, max_slides=1)["slides"][0]["objects"]}
    primary = objects["Hero image"]
    peer = objects["Shared source"]
    image_path = "/mnt/user-data/uploads/replacement.jpg"
    replacement = _jpeg()
    called = False
    original_apply = pptx_module._apply_pptx_picture_source

    def record_apply(*args, **kwargs):
        nonlocal called
        called = True
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_picture_source",
        record_apply,
    )
    operations = [
        PptxPictureSourceReplacementOperation(
            pictures=PptxPictureSelector(
                targets=[
                    PptxPictureTarget(
                        path=primary["path"],
                        expected_name=primary["name"],
                        expected_source_sha256=primary["source"]["sha256"],
                    )
                ]
            ),
            image_path=image_path,
        ),
        PptxPictureSourceReplacementOperation(
            pictures=PptxPictureSelector(
                targets=[
                    PptxPictureTarget(
                        path=peer["path"],
                        expected_name=peer["name"],
                        expected_source_sha256="0" * 64,
                    )
                ]
            ),
            image_path=image_path,
        ),
    ]

    with pytest.raises(
        OfficeOperationError,
        match="expected_source_sha256 no longer matches",
    ):
        edit_pptx(
            source,
            operations,
            image_assets={image_path: replacement},
        )
    assert called is False

    bad_name = PptxPictureSourceReplacementOperation(
        pictures=PptxPictureSelector(
            targets=[
                PptxPictureTarget(
                    path=primary["path"],
                    expected_name="Outdated picture",
                    expected_source_sha256=primary["source"]["sha256"],
                )
            ]
        ),
        image_path=image_path,
    )
    with pytest.raises(
        OfficeOperationError,
        match="expected_name no longer matches",
    ):
        edit_pptx(
            source,
            [bad_name],
            image_assets={image_path: replacement},
        )
    assert called is False


@pytest.mark.parametrize(
    ("picture", "error"),
    [
        (
            """<p:pic><p:nvPicPr><p:cNvPr id="20" name="Hero image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:link="rIdImage"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/></p:pic>""",
            "one embedded source",
        ),
        (
            '<p:pic><p:nvPicPr><p:cNvPr id="20" name="Hero image"/>'
            "<p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill>"
            '<a:blip r:embed="rIdImage"><a:extLst><a:ext uri="source-companion">'
            '<asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" '
            'r:embed="rIdImage"/></a:ext></a:extLst></a:blip>'
            "<a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/></p:pic>",
            "one embedded source",
        ),
        (
            '<p:pic><p:nvPicPr><p:cNvPr id="20" name="Hero image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rIdImage"/><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/></p:pic>',
            "exactly one direct embedded-image blip",
        ),
        (
            '<p:pic xmlns:as="http://purl.oclc.org/ooxml/drawingml/main">'
            '<p:nvPicPr><p:cNvPr id="20" name="Hero image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
            '<p:blipFill><as:blip r:embed="rIdImage"/>'
            "<as:stretch><as:fillRect/></as:stretch></p:blipFill><p:spPr/></p:pic>",
            "mixes Strict and Transitional DrawingML",
        ),
        (
            """<p:pic><p:nvPicPr><p:cNvPr id="20" name="Hero image"/><p:cNvPicPr/><p:nvPr><a:videoFile/></p:nvPr></p:nvPicPr><p:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/></p:pic>""",
            "stale or missing paths",
        ),
    ],
)
def test_edit_pptx_picture_replacement_rejects_unsafe_source_structures(
    picture: str,
    error: str,
) -> None:
    source = _picture_source_pptx(
        primary_picture=picture,
        secondary_picture="",
    )
    image_path = "/mnt/user-data/uploads/replacement.jpg"
    operation = PptxPictureSourceReplacementOperation(
        pictures=PptxPictureSelector(
            targets=[
                PptxPictureTarget(
                    path="/slide[1]/picture[@id=20]",
                    expected_name="Hero image",
                    expected_source_sha256=hashlib.sha256(_png()).hexdigest(),
                )
            ]
        ),
        image_path=image_path,
    )

    with pytest.raises(OfficeOperationError, match=error):
        edit_pptx(
            source,
            [operation],
            image_assets={image_path: _jpeg()},
        )


def test_edit_pptx_picture_replacement_preservation_gate_masks_only_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _picture_source_pptx()
    picture = inspect_pptx(source, max_slides=1)["slides"][0]["objects"][0]
    image_path = "/mnt/user-data/uploads/replacement.jpg"
    operation = PptxPictureSourceReplacementOperation(
        pictures=PptxPictureSelector(
            targets=[
                PptxPictureTarget(
                    path=picture["path"],
                    expected_name=picture["name"],
                    expected_source_sha256=picture["source"]["sha256"],
                )
            ]
        ),
        image_path=image_path,
    )
    original_apply = pptx_module._apply_pptx_picture_source

    def corrupt_alt_text(*args, **kwargs):
        changed = original_apply(*args, **kwargs)
        target = args[0]
        non_visual = pptx_module._non_visual_drawing_properties(target.element)
        assert non_visual is not None
        non_visual.set("descr", "Corrupted alt text")
        return changed

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_picture_source",
        corrupt_alt_text,
    )

    with pytest.raises(
        OfficeOperationError,
        match="changed unsupported structure",
    ):
        edit_pptx(
            source,
            [operation],
            image_assets={image_path: _jpeg()},
        )


def test_edit_pptx_picture_replacement_rejects_duplicate_targets() -> None:
    source = _picture_source_pptx()
    picture = inspect_pptx(source, max_slides=1)["slides"][0]["objects"][0]
    image_path = "/mnt/user-data/uploads/replacement.jpg"
    operation = PptxPictureSourceReplacementOperation(
        pictures=PptxPictureSelector(
            targets=[
                PptxPictureTarget(
                    path=picture["path"],
                    expected_name=picture["name"],
                    expected_source_sha256=picture["source"]["sha256"],
                )
            ]
        ),
        image_path=image_path,
    )

    with pytest.raises(
        OfficeOperationError,
        match="image mutation targets may appear in only one operation",
    ):
        edit_pptx(
            source,
            [operation, operation],
            image_assets={image_path: _jpeg()},
        )


def test_pptx_picture_replacement_models_require_stable_paths_and_exact_fields() -> None:
    with pytest.raises(ValueError, match="authored-ID PPTX picture path"):
        PptxPictureTarget(
            path="/slide[1]/picture[1]",
            expected_name="Hero image",
            expected_source_sha256="0" * 64,
        )
    with pytest.raises(ValueError):
        PptxPictureTarget(
            path="/slide[1]/picture[@id=20]",
            expected_name="Hero image",
            expected_source_sha256="A" * 64,
        )
    with pytest.raises(ValueError):
        PptxPictureSourceReplacementOperation.model_validate(
            {
                "type": "replace_pptx_picture_sources",
                "pictures": {
                    "targets": [
                        {
                            "path": "/slide[1]/picture[@id=20]",
                            "expected_name": "Hero image",
                            "expected_source_sha256": "0" * 64,
                        }
                    ],
                    "occurrence": "first",
                },
                "image_path": "/mnt/user-data/uploads/replacement.png",
                "crop": {"left_percent": 10},
            }
        )


def test_inspect_pptx_caps_structured_interactions_per_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_INTERACTIONS_PER_OBJECT", 1)
    selector = PptxObjectSelector(paths=["/slide[1]/shape[@id=21]"])

    inspected = inspect_pptx(
        _metadata_interactions_pptx(),
        max_slides=1,
        selector=selector,
    )
    slide = inspected["slides"][0]
    shape = slide["objects"][0]

    assert shape["interaction_count"] == 3
    assert shape["interactions_returned"] == 1
    assert shape["interactions_truncated"] is True
    assert slide["interaction_count"] == 4
    assert slide["matched_interaction_count"] == 3
    assert slide["interactions_returned"] == 1
    assert slide["interactions_truncated"] is True
    assert inspected["selected_interactions_returned"] == 1
    assert inspected["selected_interactions_truncated"] is True


def test_inspect_pptx_caps_structured_interactions_per_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_INTERACTIONS", 2)
    selector = PptxObjectSelector(paths=["/slide[1]/shape[@id=21]"])

    inspected = inspect_pptx(
        _metadata_interactions_pptx(),
        max_slides=1,
        selector=selector,
    )
    shape = inspected["slides"][0]["objects"][0]

    assert shape["interaction_count"] == 3
    assert shape["interactions_returned"] == 2
    assert shape["interactions_truncated"] is True
    assert inspected["selected_interactions_returned"] == 2
    assert inspected["selected_interactions_truncated"] is True


def test_pptx_object_selector_keeps_interaction_counts_owner_aware() -> None:
    selector = PptxObjectSelector(paths=["/slide[1]/shape[@id=21]"])

    inspected = inspect_pptx(
        _metadata_interactions_pptx(),
        max_slides=1,
        selector=selector,
    )
    slide = inspected["slides"][0]

    assert [item["path"] for item in slide["objects"]] == ["/slide[1]/shape[@id=21]"]
    assert slide["interaction_count"] == 4
    assert slide["matched_interaction_count"] == 3
    assert slide["interactions_returned"] == 3
    assert slide["interactions_truncated"] is False


def test_inspect_pptx_preserves_direct_background_kind_and_gradient_focus() -> None:
    gradient_background = """<p:bg><p:bgPr><a:gradFill><a:path path="circle"><a:fillToRect l="1000" t="2000" r="3000" b="4000"/></a:path></a:gradFill></p:bgPr></p:bg>"""
    gradient = inspect_pptx(
        _pptx(slide2=_slide("", background=gradient_background)),
        max_slides=1,
    )["slides"][0]["background"]

    assert gradient == {
        "scope": "direct",
        "type": "gradient",
        "geometry": "path",
        "path": "circle",
        "fill_to_rectangle": {
            "left_percent": 1.0,
            "top_percent": 2.0,
            "right_percent": 3.0,
            "bottom_percent": 4.0,
        },
    }

    reference_background = """<p:bg><p:bgRef idx="1001"><a:schemeClr val="background1"/></p:bgRef></p:bg>"""
    reference = inspect_pptx(
        _pptx(slide2=_slide("", background=reference_background)),
        max_slides=1,
    )["slides"][0]["background"]

    assert reference == {
        "scope": "direct",
        "type": "theme_reference",
        "style_index": 1001,
        "color": {"type": "scheme", "value": "background1"},
    }


def test_edit_pptx_clears_only_the_exact_direct_slide_background() -> None:
    background = """<p:bg><p:bgPr><a:solidFill><a:srgbClr val="112233"/></a:solidFill></p:bgPr></p:bg>"""
    source = _pptx(slide2=_slide(_shape("Keep me"), background=background))
    operation = PptxSlideBackgroundFormatOperation(
        slides=PptxSlideSelector(
            targets=[
                PptxSlideTarget(
                    path="/slide[1]",
                    expected_part_name="ppt/slides/slide2.xml",
                )
            ]
        ),
        formatting=PptxSlideBackgroundFormatting(type="none"),
    )

    edited, reports = edit_pptx(source, [operation])

    assert reports == [
        {
            "operation": 1,
            "type": "format_pptx_slide_backgrounds",
            "match_count": 1,
            "matched_paths": ["/slide[1]"],
            "matched_paths_truncated": False,
        }
    ]
    assert inspect_pptx(edited, max_slides=1)["slides"][0]["background"] is None
    with (
        zipfile.ZipFile(io.BytesIO(source)) as source_archive,
        zipfile.ZipFile(io.BytesIO(edited)) as edited_archive,
    ):
        assert source_archive.namelist() == edited_archive.namelist()
        assert [name for name in source_archive.namelist() if source_archive.read(name) != edited_archive.read(name)] == ["ppt/slides/slide2.xml"]
    no_op, _ = edit_pptx(edited, [operation])
    assert no_op == edited


def test_edit_pptx_slide_background_rejects_stale_part_name() -> None:
    operation = PptxSlideBackgroundFormatOperation(
        slides=PptxSlideSelector(
            targets=[
                PptxSlideTarget(
                    path="/slide[1]",
                    expected_part_name="ppt/slides/slide1.xml",
                )
            ]
        ),
        formatting=PptxSlideBackgroundFormatting(
            type="solid",
            color="#4472C4",
        ),
    )

    with pytest.raises(
        OfficeOperationError,
        match="expected_part_name no longer matches",
    ):
        edit_pptx(_pptx(), [operation])


@pytest.mark.parametrize(
    "background, error",
    [
        (
            """<p:bg><p:bgRef idx="1001"><a:schemeClr val="background1"/></p:bgRef></p:bg>""",
            "theme-reference backgrounds are read-only",
        ),
        (
            "<p:bg><p:bgPr><a:gradFill><a:gsLst>"
            '<a:gs pos="0"><a:srgbClr val="000000"/></a:gs>'
            '<a:gs pos="100000"><a:srgbClr val="FFFFFF"/></a:gs>'
            '</a:gsLst><a:path path="circle">'
            '<a:fillToRect l="50000" t="50000" r="50000" b="50000"/>'
            "</a:path></a:gradFill></p:bgPr></p:bg>",
            "path-gradient slide backgrounds are read-only",
        ),
        (
            """<p:bg><p:bgPr><a:solidFill><a:srgbClr val="112233"/></a:solidFill><a:effectLst><a:outerShdw blurRad="1"/></a:effectLst></p:bgPr></p:bg>""",
            "background effects are read-only",
        ),
    ],
)
def test_edit_pptx_slide_background_rejects_deferred_existing_surfaces(
    background: str,
    error: str,
) -> None:
    operation = PptxSlideBackgroundFormatOperation(
        slides=PptxSlideSelector(
            targets=[
                PptxSlideTarget(
                    path="/slide[1]",
                    expected_part_name="ppt/slides/slide2.xml",
                )
            ]
        ),
        formatting=PptxSlideBackgroundFormatting(
            type="solid",
            color="#4472C4",
        ),
    )

    with pytest.raises(OfficeOperationError, match=error):
        edit_pptx(
            _pptx(slide2=_slide("", background=background)),
            [operation],
        )


def test_pptx_slide_background_model_keeps_deferred_fields_closed() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        PptxSlideBackgroundFormatting(
            type="image",
            image_path="/mnt/user-data/uploads/background.png",
            crop={
                "left_percent": 1,
                "top_percent": 2,
                "right_percent": 3,
                "bottom_percent": 4,
            },
        )
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        PptxSlideBackgroundFormatting(
            type="gradient",
            stops=[
                PptxGradientStopFormatting(position_percent=0, color="#000000"),
                PptxGradientStopFormatting(position_percent=100, color="#FFFFFF"),
            ],
            geometry={
                "type": "path",
                "path": "circle",
                "fill_to_rectangle": {
                    "left_percent": 50,
                    "top_percent": 50,
                    "right_percent": 50,
                    "bottom_percent": 50,
                },
            },
        )


def test_inspect_pptx_distinguishes_absent_and_empty_picture_fill_rectangle() -> None:
    pictures = """<p:pic><p:nvPicPr><p:cNvPr id="31" name="Bare stretch"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:stretch/></p:blipFill><p:spPr/></p:pic>
    <p:pic><p:nvPicPr><p:cNvPr id="32" name="Explicit rectangle"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/></p:pic>"""

    objects = inspect_pptx(
        _pptx(slide2=_slide(pictures)),
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"]

    assert objects[0]["style"]["picture"] == {"fill_mode": "stretch"}
    assert objects[1]["style"]["picture"] == {
        "fill_mode": "stretch",
        "fill_rectangle": {},
    }


def test_inspect_pptx_uses_stable_table_text_interaction_owner_paths() -> None:
    table = """<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="40" name="Interactive table"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr/><a:tblGrid/>
        <a:tr h="1"><a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p>
          <a:pPr><a:defRPr><a:hlinkMouseOver r:id="" action="ppaction://hlinkshowjump?jump=nextslide"/></a:defRPr></a:pPr>
          <a:br><a:rPr><a:hlinkClick r:id="" action="ppaction://hlinkshowjump?jump=previousslide"/></a:rPr></a:br>
          <a:endParaRPr><a:hlinkClick r:id="" action="ppaction://hlinkshowjump?jump=firstslide"/></a:endParaRPr>
        </a:p></a:txBody><a:tcPr/></a:tc></a:tr>
      </a:tbl></a:graphicData></a:graphic>
    </p:graphicFrame>"""

    inspected_table = inspect_pptx(
        _pptx(slide2=_slide(table)),
        max_slides=1,
    )["slides"][0]["objects"][0]

    base = "/slide[1]/table[@id=40]/row[1]/cell[1]/paragraph[1]"
    assert [item["owner_path"] for item in inspected_table["interactions"]] == [
        f"{base}/default_run",
        f"{base}/line_break[1]",
        f"{base}/end_run",
    ]
    assert [item["trigger"] for item in inspected_table["interactions"]] == [
        "hover",
        "click",
        "click",
    ]


def test_group_interactions_do_not_duplicate_children_and_follow_object_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = """<p:grpSp><p:nvGrpSpPr><p:cNvPr id="50" name="Interactive group"><a:hlinkClick r:id="" action="ppaction://hlinkshowjump?jump=nextslide"/></p:cNvPr><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
      <p:sp><p:nvSpPr><p:cNvPr id="51" name="Interactive child"><a:hlinkClick r:id="" action="ppaction://hlinkshowjump?jump=previousslide"/></p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/></p:sp>
    </p:grpSp>"""
    document = _pptx(slide2=_slide(group))

    complete = inspect_pptx(document, max_slides=1)["slides"][0]
    assert complete["interaction_count"] == 2
    assert [item["interaction_count"] for item in complete["objects"]] == [1, 1]

    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_OBJECTS", 1)
    capped = inspect_pptx(document, max_slides=1)["slides"][0]
    assert [item["path"] for item in capped["objects"]] == ["/slide[1]/group[@id=50]"]
    assert capped["matched_interaction_count"] == 2
    assert capped["interactions_returned"] == 1
    assert capped["interactions_truncated"] is True


def test_inspect_pptx_marks_unsafe_external_target_and_bounds_relationship_id() -> None:
    relationship_id = "R" * 300
    shape = f"""<p:sp><p:nvSpPr><p:cNvPr id="60" name="Unsafe link"><a:hlinkClick r:id="{relationship_id}"/></p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/></p:sp>"""
    relationships = f"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="{relationship_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="javascript:alert(1)" TargetMode="External"/>
    </Relationships>"""
    document = _pptx(
        slide2=_slide(shape),
        slide2_relationships=relationships,
    )

    inspected = inspect_pptx(document, max_slides=1)
    inspected_object = inspected["slides"][0]["objects"][0]
    interaction = inspected_object["interactions"][0]
    resource = inspected["slides"][0]["resources"][0]

    assert inspected["risky_features"] == ["external relationships"]
    assert len(inspected_object["relationship_ids"][0]) == 256
    assert inspected_object["relationship_ids_truncated"] is True
    assert len(interaction["relationship_id"]) == 256
    assert interaction["relationship_id_truncated"] is True
    assert interaction["target_kind"] == "unsafe_external_url"
    assert interaction["unsafe_target"] is True
    assert len(resource["relationship_id"]) == 256
    assert resource["relationship_id_truncated"] is True
    with pytest.raises(OfficeOperationError, match="external relationships"):
        validate_pptx_renderable(document)


def test_inspect_pptx_enforces_real_interaction_window_cap() -> None:
    runs = "".join("""<a:r><a:rPr><a:hlinkClick r:id="" action="ppaction://hlinkshowjump?jump=nextslide"/></a:rPr><a:t>x</a:t></a:r>""" for _ in range(100))
    shapes = "".join(
        f"""<p:sp><p:nvSpPr><p:cNvPr id="{70 + index}" name="Interaction batch {index}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p>{runs}</a:p></p:txBody></p:sp>""" for index in range(21)
    )

    inspected = inspect_pptx(
        _pptx(slide2=_slide(shapes)),
        max_slides=1,
    )
    slide = inspected["slides"][0]

    assert slide["interaction_count"] == 2_100
    assert slide["interactions_returned"] == 2_000
    assert slide["interactions_truncated"] is True
    assert slide["objects"][0]["interactions_returned"] == 100
    assert slide["objects"][-1]["interaction_count"] == 100
    assert slide["objects"][-1]["interactions_returned"] == 0
    assert slide["objects"][-1]["interactions_truncated"] is True
    assert inspected["selected_interactions_returned"] == 2_000
    assert inspected["selected_interactions_truncated"] is True


def test_inspect_pptx_reports_nested_identity_z_order_and_exact_geometry() -> None:
    slide = _slide(
        """<p:sp><p:nvSpPr><p:cNvPr id="7" name="Rotated text"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
          <p:spPr><a:xfrm rot="300000" flipH="1"><a:off x="100" y="200"/><a:ext cx="300" cy="400"/></a:xfrm></p:spPr>
          <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Root copy</a:t></a:r></a:p></p:txBody>
        </p:sp>
        <p:grpSp><p:nvGrpSpPr><p:cNvPr id="8" name="Scaled group"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
          <p:grpSpPr><a:xfrm><a:off x="1000" y="2000"/><a:ext cx="3000" cy="4000"/><a:chOff x="10" y="20"/><a:chExt cx="30" cy="40"/></a:xfrm></p:grpSpPr>
          <p:sp><p:nvSpPr><p:cNvPr id="9" name="Nested text"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/>
            <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Nested copy</a:t></a:r></a:p></p:txBody>
          </p:sp>
        </p:grpSp>"""
    )

    inspected = inspect_pptx(_pptx(slide2=slide), max_slides=1)
    objects = inspected["slides"][0]["objects"]

    assert [item["path"] for item in objects] == [
        "/slide[1]/shape[@id=7]",
        "/slide[1]/group[@id=8]",
        "/slide[1]/group[@id=8]/shape[@id=9]",
    ]
    assert [(item["parent_path"], item["z_order"]) for item in objects] == [
        ("/slide[1]", 1),
        ("/slide[1]", 2),
        ("/slide[1]/group[@id=8]", 1),
    ]
    assert objects[0]["kind"] == "text_box"
    assert objects[0]["geometry"] == {
        "x_emu": 100,
        "y_emu": 200,
        "width_emu": 300,
        "height_emu": 400,
        "rotation_degrees": 5.0,
        "flip_horizontal": True,
    }
    assert objects[1]["geometry"] == {
        "x_emu": 1000,
        "y_emu": 2000,
        "width_emu": 3000,
        "height_emu": 4000,
        "child_x_emu": 10,
        "child_y_emu": 20,
        "child_width_emu": 30,
        "child_height_emu": 40,
    }
    assert objects[1]["child_count"] == 1
    assert [item["path"] for item in inspected["slides"][0]["text"]] == [
        "/slide[1]/shape[@id=7]",
        "/slide[1]/group[@id=8]/shape[@id=9]",
    ]


def test_inspect_pptx_uses_collision_free_positional_paths_for_duplicate_ids() -> None:
    slide = _slide(_shape("One") + _shape("Two"))

    objects = inspect_pptx(_pptx(slide2=slide), max_slides=1)["slides"][0]["objects"]

    assert [item["path"] for item in objects] == [
        "/slide[1]/shape[1]",
        "/slide[1]/shape[2]",
    ]
    assert [item["id"] for item in objects] == [2, 2]
    assert {item["identity_source"] for item in objects} == {"position"}


def test_pptx_object_selector_accepts_only_typed_exact_object_paths() -> None:
    selector = PptxObjectSelector(
        paths=[
            "/slide[1]/group[@id=8]/shape[@id=9]",
            "/slide[2]/picture[1]",
        ],
        kinds=["text_box", "picture"],
    )

    assert selector.paths == [
        "/slide[1]/group[@id=8]/shape[@id=9]",
        "/slide[2]/picture[1]",
    ]
    with pytest.raises(ValueError, match="at least one filter"):
        PptxObjectSelector()
    with pytest.raises(ValueError, match="exact stable PPTX object paths"):
        PptxObjectSelector(paths=["/slide[1]/shape[*]"])
    with pytest.raises(ValueError, match="at most 16,384 characters"):
        PptxObjectSelector(paths=["/slide[1]" + "/group[1]" * 2_000])
    with pytest.raises(ValueError, match="duplicates"):
        PptxObjectSelector(paths=["/slide[1]/shape[1]"] * 2)
    with pytest.raises(ValueError, match="duplicates"):
        PptxObjectSelector(kinds=["shape", "shape"])


def test_inspect_pptx_reads_direct_shape_paragraph_and_run_formatting() -> None:
    inspected = inspect_pptx(
        _pptx(slide2=_slide(_formatted_shape())),
        max_slides=1,
        include_formatting=True,
    )
    shape = inspected["slides"][0]["objects"][0]

    assert inspected["formatting_included"] is True
    assert inspected["selected_formatting_truncated"] is False
    assert shape["style"] == {
        "geometry": {"type": "preset", "preset": "roundRect"},
        "fill": {
            "type": "solid",
            "color": {
                "type": "rgb",
                "value": "#336699",
                "opacity_percent": 75.0,
            },
        },
        "line": {
            "width_emu": 25400,
            "cap": "round",
            "fill": {
                "type": "solid",
                "color": {"type": "scheme", "value": "accent1"},
            },
            "dash": "dash",
            "join": "round",
        },
        "text_box": {
            "margins": {
                "left_emu": 100,
                "top_emu": 200,
                "right_emu": 300,
                "bottom_emu": 400,
            },
            "vertical_anchor": "middle",
            "wrap": False,
            "right_to_left_columns": False,
            "autofit": "normal",
            "font_scale_percent": 92.5,
            "line_spacing_reduction_percent": 12.5,
        },
    }
    assert "bold" not in shape["style"]
    text_body = shape["text_body"]
    assert text_body["paragraph_count"] == 2
    assert text_body["paragraphs_truncated"] is False

    first_paragraph = text_body["paragraphs"][0]
    assert first_paragraph["path"] == "/slide[1]/shape[@id=7]/paragraph[1]"
    assert first_paragraph["text"] == "AlphaBeta\n\t42"
    assert first_paragraph["formatting"] == {
        "alignment": "center",
        "indent_emu": -500,
        "margin_left_emu": 1000,
        "right_to_left": False,
        "line_spacing": {"unit": "percent", "value": 150.0},
        "space_before": {"unit": "points", "value": 12.0},
        "bullet": {"type": "character", "character": "\u2022"},
    }
    assert [segment["path"] for segment in first_paragraph["segments"]] == [
        "/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
        "/slide[1]/shape[@id=7]/paragraph[1]/run[2]",
        "/slide[1]/shape[@id=7]/paragraph[1]/line_break[1]",
        "/slide[1]/shape[@id=7]/paragraph[1]/tab[1]",
        "/slide[1]/shape[@id=7]/paragraph[1]/field[1]",
    ]
    first_run = first_paragraph["segments"][0]
    second_run = first_paragraph["segments"][1]
    assert first_run["formatting"] == {
        "fonts": {"latin": "Aptos Display"},
        "font_size_points": 24.0,
        "bold": True,
        "language": "en-US",
        "fill": {
            "type": "solid",
            "color": {"type": "rgb", "value": "#FF0000"},
        },
    }
    assert second_run["formatting"] == {
        "font_size_points": 18.0,
        "bold": False,
        "italic": True,
        "underline": "double",
        "strike": "single",
        "character_spacing_points": 0.5,
        "baseline_percent": 33.0,
        "fill": {
            "type": "solid",
            "color": {
                "type": "rgb",
                "value": "#00FF00",
                "opacity_percent": 50.0,
            },
        },
    }
    assert first_paragraph["segments"][-1]["field_id"] == "field-1"
    assert first_paragraph["segments"][-1]["field_type"] == "slidenum"
    second_paragraph = text_body["paragraphs"][1]
    assert second_paragraph["formatting"]["default_run_formatting"] == {
        "font_size_points": 12.0,
        "bold": False,
    }
    assert second_paragraph["end_run_formatting"] == {
        "font_size_points": 8.0,
        "italic": False,
    }


def test_inspect_pptx_reads_ordered_color_transforms_and_canonical_line_style() -> None:
    shape = (
        _formatted_shape()
        .replace(
            '<a:alpha val="75000"/>',
            '<a:alpha val="75000"/><a:lumMod val="65000"/><a:hueOff val="5400000"/><a:tint val="12500"/>',
            1,
        )
        .replace('cap="rnd"', 'cap="sq"', 1)
        .replace('<a:prstDash val="dash"/><a:round/>', '<a:prstDash val="lgDashDotDot"/><a:miter lim="800000"/>', 1)
    )

    style = inspect_pptx(
        _pptx(slide2=_slide(shape)),
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["style"]

    assert style["fill"]["color"] == {
        "type": "rgb",
        "value": "#336699",
        "opacity_percent": 75.0,
        "transform_count": 3,
        "transforms_returned": 3,
        "transforms_truncated": False,
        "transforms": [
            {
                "type": "luminance_modulation",
                "value": 65_000,
                "percent": 65.0,
            },
            {
                "type": "hue_offset",
                "value": 5_400_000,
                "degrees": 90.0,
            },
            {"type": "tint", "value": 12_500, "percent": 12.5},
        ],
    }
    assert style["line"]["cap"] == "square"
    assert style["line"]["dash"] == "large_dash_dot_dot"
    assert style["line"]["join"] == "miter"
    assert style["line"]["miter_limit_percent"] == 800.0


def test_inspect_pptx_caps_ordered_color_transform_output() -> None:
    transforms = "".join(f'<a:lumMod val="{50_000 + index}"/>' for index in range(40))
    shape = _formatted_shape().replace(
        '<a:alpha val="75000"/>',
        f'<a:alpha val="75000"/>{transforms}',
        1,
    )

    color = inspect_pptx(
        _pptx(slide2=_slide(shape)),
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["style"]["fill"]["color"]

    assert color["transform_count"] == 40
    assert color["transforms_returned"] == 32
    assert color["transforms_truncated"] is True
    assert [item["value"] for item in color["transforms"]] == list(range(50_000, 50_032))


def test_inspect_pptx_filters_returned_objects_but_keeps_slide_context() -> None:
    document = _pptx(slide2=_slide(_formatted_shape() + _shape("Other copy")))
    selector = PptxObjectSelector(
        paths=["/slide[1]/shape[@id=7]"],
        kinds=["text_box"],
        contains_text="Alpha",
        has_text=True,
        name_equals="Styled copy",
        has_alt_text=True,
    )

    inspected = inspect_pptx(document, max_slides=1, selector=selector)
    slide = inspected["slides"][0]

    assert inspected["selector_applied"] is True
    assert inspected["selected_object_count"] == 2
    assert inspected["selected_matched_object_count"] == 1
    assert slide["object_count"] == 2
    assert slide["matched_object_count"] == 1
    assert [item["path"] for item in slide["objects"]] == ["/slide[1]/shape[@id=7]"]
    assert [item["text"] for item in slide["text"]] == [
        "AlphaBeta\n\t42\n",
        "Other copy",
    ]

    no_match = inspect_pptx(
        document,
        max_slides=1,
        selector=PptxObjectSelector(contains_text="alpha"),
    )
    assert no_match["selected_matched_object_count"] == 0
    assert no_match["slides"][0]["objects"] == []


def test_pptx_name_selector_matches_the_bounded_inspectable_name() -> None:
    authored_name = "A" * 300
    shape = _formatted_shape().replace('name="Styled copy"', f'name="{authored_name}"')
    document = _pptx(slide2=_slide(shape))

    summary = inspect_pptx(document, max_slides=1)
    inspected_name = summary["slides"][0]["objects"][0]["name"]
    selected = inspect_pptx(
        document,
        max_slides=1,
        selector=PptxObjectSelector(name_equals=inspected_name),
    )

    assert len(inspected_name) == 256
    assert summary["slides"][0]["objects"][0]["name_truncated"] is True
    assert selected["selected_matched_object_count"] == 1


def test_inspect_pptx_uses_stable_text_paths_inside_table_cells() -> None:
    inspected = inspect_pptx(
        _pptx(),
        max_slides=1,
        include_formatting=True,
        selector=PptxObjectSelector(kinds=["table"]),
    )
    table = inspected["slides"][0]["objects"][0]
    cell = table["cells"][0]
    paragraph = cell["text_body"]["paragraphs"][0]
    run = paragraph["segments"][0]

    assert table["path"] == "/slide[1]/table[@id=4]"
    assert table["cell_count"] == 1
    assert cell["path"] == "/slide[1]/table[@id=4]/row[1]/cell[1]"
    assert paragraph["path"] == ("/slide[1]/table[@id=4]/row[1]/cell[1]/paragraph[1]")
    assert run["path"] == ("/slide[1]/table[@id=4]/row[1]/cell[1]/paragraph[1]/run[1]")
    assert run["text"] == "North"


def test_inspect_pptx_caps_nested_formatting_output_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_FORMATTED_PARAGRAPHS", 1)
    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_FORMATTED_SEGMENTS", 2)

    inspected = inspect_pptx(
        _pptx(slide2=_slide(_formatted_shape())),
        max_slides=1,
        include_formatting=True,
    )
    shape = inspected["slides"][0]["objects"][0]

    assert inspected["selected_formatting_truncated"] is True
    assert shape["formatting_truncated"] is True
    assert shape["text_body"]["paragraph_count"] == 2
    assert shape["text_body"]["paragraphs_returned"] == 1
    assert shape["text_body"]["paragraphs_truncated"] is True
    assert shape["text_body"]["paragraphs"][0]["segment_count"] == 5
    assert shape["text_body"]["paragraphs"][0]["segments_returned"] == 2
    assert shape["text_body"]["paragraphs"][0]["segments_truncated"] is True


def test_inspect_pptx_counts_model3d_alternate_content_once() -> None:
    model = """<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:am3d="http://schemas.microsoft.com/office/drawing/2017/model3d">
      <mc:Choice Requires="am3d">
        <p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="11" name="Product model"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
          <p:xfrm><a:off x="100" y="200"/><a:ext cx="300" cy="400"/></p:xfrm>
          <a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/drawing/2017/model3d">
            <am3d:model3d r:embed="rIdModel"><am3d:raster><am3d:blip r:embed="rIdThumb"/></am3d:raster></am3d:model3d>
          </a:graphicData></a:graphic>
        </p:graphicFrame>
      </mc:Choice>
      <mc:Fallback>
        <p:pic><p:nvPicPr><p:cNvPr id="11" name="Product model"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rIdThumb"/></p:blipFill><p:spPr/></p:pic>
      </mc:Fallback>
    </mc:AlternateContent>"""
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdModel" Type="http://schemas.microsoft.com/office/2017/06/relationships/model3d" Target="../media/model.glb"/>
      <Relationship Id="rIdThumb" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/thumb.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="glb" ContentType="model/gltf-binary"/>
  <Default Extension="png" ContentType="image/png"/>
</Types>""",
    )
    document = _pptx(
        slide2=_slide(_shape("Before") + model),
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={
            "ppt/media/model.glb": "model-bytes",
            "ppt/media/thumb.png": "thumbnail-bytes",
        },
    )

    slide = inspect_pptx(document, max_slides=1)["slides"][0]
    model_object = slide["objects"][1]

    assert slide["object_count"] == 2
    assert model_object["path"] == "/slide[1]/model3d[@id=11]"
    assert model_object["kind"] == "model3d"
    assert model_object["z_order"] == 2
    assert model_object["geometry"] == {
        "x_emu": 100,
        "y_emu": 200,
        "width_emu": 300,
        "height_emu": 400,
    }
    assert model_object["relationship_ids"] == ["rIdModel", "rIdThumb"]
    assert {item["kind"] for item in slide["resources"]} == {"model3d", "image"}
    assert all(item["owner_paths"] == ["/slide[1]/model3d[@id=11]"] for item in slide["resources"])


def test_inspect_pptx_reports_owner_aware_bounded_resource_graph() -> None:
    inspected = inspect_pptx(_resource_pptx(), max_slides=1)
    slide = inspected["slides"][0]
    resources = {(item["source_part"], item["relationship_id"]): item for item in slide["resources"]}

    assert slide["resource_count"] == 7
    assert not slide["resources_truncated"]
    assert ("ppt/custom/master.xml", "rIdLayoutBack") not in resources
    assert all(item["part_name"] != "ppt/slideLayouts/slideLayout2.xml" for item in resources.values())

    chart = resources[("ppt/slides/slide2.xml", "rIdChart")]
    workbook = resources[("ppt/charts/chart1.xml", "rIdData")]
    image = resources[("ppt/slides/slide2.xml", "rIdImage")]
    theme = resources[("ppt/custom/master.xml", "rIdTheme")]
    hyperlink = resources[("ppt/slides/slide2.xml", "rIdLink")]
    assert chart["owner_paths"] == ["/slide[1]/chart[@id=5]"]
    assert workbook["owner_paths"] == ["/slide[1]/chart[@id=5]"]
    assert workbook["content_type"] == ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert workbook["size_bytes"] == len("workbook-bytes")
    assert image["owner_paths"] == ["/slide[1]/picture[@id=6]"]
    assert image["content_type"] == "image/png"
    assert image["size_bytes"] == len("image-bytes")
    assert image["sha256"] == hashlib.sha256(b"image-bytes").hexdigest()
    assert image["package_relationship_count"] == 1
    assert image["package_relationship_source_count"] == 1
    assert image["shared_part"] is False
    assert theme["owner_paths"] == ["/slide[1]"]
    assert hyperlink["owner_paths"] == ["/slide[1]/shape[@id=7]"]
    assert hyperlink["target_mode"] == "external"
    assert hyperlink["part_name"] is None
    assert hyperlink["content_type"] is None
    assert hyperlink["size_bytes"] is None
    assert hyperlink["package_relationship_count"] is None
    assert hyperlink["package_relationship_source_count"] is None
    assert hyperlink["shared_part"] is None


def test_inspect_pptx_reports_package_wide_image_asset_inventory() -> None:
    image_relationship = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
</Types>""",
    )
    document = _pptx(
        slide1_relationships=image_relationship,
        slide2_relationships=image_relationship,
        content_types=content_types,
        extra_parts={
            "ppt/media/image1.png": "shared-image",
            "ppt/media/image2.jpg": "orphan-image",
        },
    )

    inventory = inspect_pptx(document, max_slides=1)["image_asset_inventory"]

    assert inventory == {
        "part_count": 2,
        "referenced_part_count": 1,
        "orphan_part_count": 1,
        "shared_part_count": 1,
        "parts_returned": 2,
        "parts_truncated": False,
        "parts": [
            {
                "part_name": "ppt/media/image1.png",
                "content_type": "image/png",
                "size_bytes": len("shared-image"),
                "sha256": hashlib.sha256(b"shared-image").hexdigest(),
                "relationship_count": 2,
                "relationship_source_count": 2,
                "orphan": False,
                "shared_relationships": True,
            },
            {
                "part_name": "ppt/media/image2.jpg",
                "content_type": "image/jpeg",
                "size_bytes": len("orphan-image"),
                "sha256": hashlib.sha256(b"orphan-image").hexdigest(),
                "relationship_count": 0,
                "relationship_source_count": 0,
                "orphan": True,
                "shared_relationships": False,
            },
        ],
    }


def test_inspect_pptx_caps_image_asset_inventory_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_IMAGE_ASSETS", 1)
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
</Types>""",
    )
    document = _pptx(
        content_types=content_types,
        extra_parts={
            "ppt/media/image1.png": "first",
            "ppt/media/image2.png": "second",
        },
    )

    inventory = inspect_pptx(document, max_slides=1)["image_asset_inventory"]

    assert inventory["part_count"] == 2
    assert inventory["parts_returned"] == 1
    assert inventory["parts_truncated"] is True
    assert inventory["orphan_part_count"] == 2


def test_inspect_pptx_media_gc_plan_is_opt_in_and_reports_orphan_parts() -> None:
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpeg" ContentType="image/jpeg"/>
</Types>""",
    )
    document = _pptx(
        content_types=content_types,
        extra_parts={
            "docProps/thumbnail.jpeg": b"thumbnail",
            "ppt/media/image1.png": b"orphan-image",
        },
    )

    default_inspection = inspect_pptx(document, max_slides=1)
    inspected = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )
    plan = inspected["media_gc_plan"]

    assert default_inspection["media_gc_plan_included"] is False
    assert "media_gc_plan" not in default_inspection
    assert inspected["media_gc_plan_included"] is True
    assert plan["contract_version"] == 2
    assert plan["package_sha256"] == hashlib.sha256(document).hexdigest()
    assert plan["mode"] == "dry_run"
    assert plan["actionable"] is False
    assert plan["candidate_evidence_only"] is True
    assert plan["destructive"] is False
    assert plan["deletion_supported"] is False
    assert plan["scope"] == {
        "content_type_prefix": "image/",
        "part_prefix": "ppt/media/",
        "external_relationships_in_scope": False,
        "package_root_reachability_analyzed": True,
    }
    assert plan["liveness_basis"] == ("package_root_graph_and_content_type_declared_xml_relationship_id_embed_link_attributes")
    assert plan["analysis_limitations"] == [
        "direct_part_uri_references_not_analyzed",
        "non_xml_or_untyped_part_contents_not_scanned",
        "non_image_relationship_semantics_assumed_live",
    ]
    assert plan["package_xml_integrity_complete"] is True
    assert plan["projected_root_reachability_analyzed"] is True
    assert plan["xml_source_part_count"] == 4
    assert plan["scanned_source_part_count"] == 4
    assert plan["root_unreachable_scoped_image_part_count"] == 1
    assert plan["projected_root_unreachable_scoped_image_part_count"] == 1
    assert plan["analysis_complete"] is True
    assert plan["image_part_count"] == 1
    assert plan["out_of_scope_image_part_count"] == 1
    assert plan["image_relationship_count"] == 0
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 1
    assert plan["zero_incoming_relationship_part_count"] == 1
    assert plan["estimated_reclaimable_uncompressed_bytes"] == len(b"orphan-image")
    assert plan["part_candidates"] == [
        {
            "actionable": False,
            "part_name": "ppt/media/image1.png",
            "content_type": "image/png",
            "size_bytes": len(b"orphan-image"),
            "sha256": hashlib.sha256(b"orphan-image").hexdigest(),
            "relationship_count": 0,
            "relationship_source_count": 0,
            "live_relationship_count": 0,
            "unreferenced_relationship_count": 0,
            "blocked_relationship_count": 0,
            "root_reachable_before_zero_ref_filter": False,
            "root_reachable_after_zero_ref_filter": False,
            "status": "zero_incoming_relationships",
            "evidence": "zero_incoming_relationships",
        }
    ]
    assert plan["root_unreachable_scoped_image_evidence_count"] == 1
    assert plan["root_unreachable_scoped_image_evidence_returned"] == 1
    assert plan["root_unreachable_scoped_image_evidence_truncated"] is False
    assert plan["root_unreachable_scoped_image_evidence"] == [
        {
            **plan["part_candidates"][0],
            "reason": "unreachable_from_package_root",
            "incoming_relationships_count": 0,
            "incoming_relationships_returned": 0,
            "incoming_relationships_truncated": False,
            "incoming_relationships": [],
        }
    ]
    assert plan["protected_image_parts"] == [
        {
            "actionable": False,
            "part_name": "docProps/thumbnail.jpeg",
            "content_type": "image/jpeg",
            "size_bytes": len(b"thumbnail"),
            "sha256": hashlib.sha256(b"thumbnail").hexdigest(),
            "reason": "outside_ppt_media_scope",
        }
    ]
    assert plan["blocker_count"] == 0
    assert plan["blockers"] == []


def test_inspect_pptx_media_gc_plan_finds_stale_replaced_picture_source() -> None:
    source = _picture_source_pptx(secondary_picture="")
    picture = inspect_pptx(source, max_slides=1)["slides"][0]["objects"][0]
    replacement_path = "/mnt/user-data/uploads/replacement.jpg"
    replacement = _jpeg()

    edited, _ = edit_pptx(
        source,
        [
            PptxPictureSourceReplacementOperation(
                pictures=PptxPictureSelector(
                    targets=[
                        PptxPictureTarget(
                            path=picture["path"],
                            expected_name=picture["name"],
                            expected_source_sha256=picture["source"]["sha256"],
                        )
                    ]
                ),
                image_path=replacement_path,
            )
        ],
        image_assets={replacement_path: replacement},
    )

    plan = inspect_pptx(
        edited,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["image_part_count"] == 2
    assert plan["image_relationship_count"] == 2
    assert plan["live_relationship_count"] == 1
    assert plan["unreferenced_relationship_count"] == 1
    assert plan["blocked_relationship_count"] == 0
    assert plan["relationship_candidate_count"] == 1
    candidate = plan["relationship_candidates"][0]
    assert candidate["actionable"] is False
    assert candidate["source_part"] == "ppt/slides/slide2.xml"
    assert candidate["relationship_part"] == ("ppt/slides/_rels/slide2.xml.rels")
    assert candidate["relationship_id"] == "rIdImage"
    assert candidate["relationship_type"] == ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/image")
    assert candidate["part_name"] == "ppt/media/image1.png"
    assert candidate["content_type"] == "image/png"
    assert candidate["size_bytes"] == len(_png())
    assert candidate["target_part_sha256"] == hashlib.sha256(_png()).hexdigest()
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        assert candidate["source_part_sha256"] == hashlib.sha256(archive.read("ppt/slides/slide2.xml")).hexdigest()
        assert candidate["relationship_part_sha256"] == hashlib.sha256(archive.read("ppt/slides/_rels/slide2.xml.rels")).hexdigest()
    assert candidate["xml_reference_count"] == 0
    assert candidate["reason"] == ("zero_source_xml_relationship_attribute_references")
    assert candidate["source_root_reachable"] is True
    assert candidate["target_root_reachable_before_zero_ref_filter"] is True
    assert candidate["target_root_reachable_after_zero_ref_filter"] is False
    assert candidate["part_status"] == ("all_incoming_relationships_have_zero_xml_references")
    assert candidate["part_relationship_count"] == 1
    assert candidate["part_live_relationship_count"] == 0
    assert candidate["part_unreferenced_relationship_count"] == 1
    assert candidate["part_all_incoming_relationships_have_zero_xml_references"] is True
    assert plan["part_candidate_count"] == 1
    assert plan["all_incoming_relationships_zero_xml_refs_part_count"] == 1
    assert plan["estimated_reclaimable_uncompressed_bytes"] == len(_png())
    assert plan["part_candidates"][0]["part_name"] == "ppt/media/image1.png"
    assert plan["part_candidates"][0]["status"] == ("all_incoming_relationships_have_zero_xml_references")
    assert plan["part_candidates"][0]["root_reachable_before_zero_ref_filter"] is True
    assert plan["part_candidates"][0]["root_reachable_after_zero_ref_filter"] is False


def test_inspect_pptx_media_gc_plan_keeps_shared_picture_source_live() -> None:
    source = _picture_source_pptx()
    picture = inspect_pptx(source, max_slides=1)["slides"][0]["objects"][0]
    replacement_path = "/mnt/user-data/uploads/replacement.jpg"

    edited, _ = edit_pptx(
        source,
        [
            PptxPictureSourceReplacementOperation(
                pictures=PptxPictureSelector(
                    targets=[
                        PptxPictureTarget(
                            path=picture["path"],
                            expected_name=picture["name"],
                            expected_source_sha256=picture["source"]["sha256"],
                        )
                    ]
                ),
                image_path=replacement_path,
            )
        ],
        image_assets={replacement_path: _jpeg()},
    )

    plan = inspect_pptx(
        edited,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["image_relationship_count"] == 2
    assert plan["live_relationship_count"] == 2
    assert plan["unreferenced_relationship_count"] == 0
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 0


def test_inspect_pptx_media_gc_plan_keeps_part_with_another_live_source() -> None:
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    live_picture = """<p:pic>
      <p:nvPicPr><p:cNvPr id="20" name="Live image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
      <p:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
      <p:spPr/>
    </p:pic>"""
    document = _pptx(
        slide1=_slide(_shape("No image reference")),
        slide2=_slide(live_picture),
        slide1_relationships=relationships,
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": _png()},
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["image_relationship_count"] == 2
    assert plan["live_relationship_count"] == 1
    assert plan["unreferenced_relationship_count"] == 1
    assert plan["relationship_candidate_count"] == 1
    candidate = plan["relationship_candidates"][0]
    assert candidate["source_part"] == "ppt/slides/slide1.xml"
    assert candidate["part_live_relationship_count"] == 1
    assert candidate["part_all_incoming_relationships_have_zero_xml_references"] is False
    assert plan["part_candidate_count"] == 0


def test_inspect_pptx_media_gc_plan_keeps_part_with_another_live_relationship_id() -> None:
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdLive" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
      <Relationship Id="rIdStale" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    picture = """<p:pic>
      <p:nvPicPr><p:cNvPr id="20" name="Live image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
      <p:blipFill><a:blip r:embed="rIdLive"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
      <p:spPr/>
    </p:pic>"""
    document = _pptx(
        slide2=_slide(picture),
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": _png()},
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["image_relationship_count"] == 2
    assert plan["live_relationship_count"] == 1
    assert plan["unreferenced_relationship_count"] == 1
    assert plan["relationship_candidate_count"] == 1
    candidate = plan["relationship_candidates"][0]
    assert candidate["relationship_id"] == "rIdStale"
    assert candidate["part_live_relationship_count"] == 1
    assert candidate["part_all_incoming_relationships_have_zero_xml_references"] is False
    assert plan["part_candidate_count"] == 0


def test_inspect_pptx_media_gc_plan_counts_strict_non_slide_xml_sources() -> None:
    strict_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://purl.oclc.org/ooxml/officeDocument/relationships/image" Target="../media/{image_name}"/>
    </Relationships>"""
    strict_source = """<x:root xmlns:x="urn:vassilflow:test" xmlns:r="http://purl.oclc.org/ooxml/officeDocument/relationships"><x:item r:id="rIdImage"/></x:root>"""
    sources = {
        "ppt/slideMasters/slideMaster1.xml": (
            "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
            "master.png",
        ),
        "ppt/slideLayouts/slideLayout1.xml": (
            "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
            "layout.png",
        ),
        "ppt/notesSlides/notesSlide2.xml": (
            "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml",
            "notes.png",
        ),
        "ppt/theme/theme1.xml": (
            "application/vnd.openxmlformats-officedocument.theme+xml",
            "theme.png",
        ),
    }
    content_type_rows = [f'  <Override PartName="/{part_name}" ContentType="{content_type}"/>' for part_name, (content_type, _) in sources.items()]
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n' + "\n".join(content_type_rows) + "\n</Types>",
    )
    extra_parts: dict[str, str | bytes] = {}
    for part_name, (_, image_name) in sources.items():
        relationship_part = pptx_module._relationship_part_name(part_name)
        extra_parts[part_name] = strict_source
        extra_parts[relationship_part] = strict_relationships.format(image_name=image_name)
        extra_parts[f"ppt/media/{image_name}"] = _png()
    document = _pptx(
        content_types=content_types,
        extra_parts=extra_parts,
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["image_part_count"] == 4
    assert plan["standard_image_relationship_count"] == 4
    assert plan["live_relationship_count"] == 4
    assert plan["unreferenced_relationship_count"] == 0
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 0


def test_inspect_pptx_media_gc_plan_treats_package_root_image_as_live() -> None:
    root_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
      <Relationship Id="rIdRootImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="ppt/media/root.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    document = _pptx(
        root_relationships=root_relationships,
        content_types=content_types,
        extra_parts={"ppt/media/root.png": _png()},
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["image_relationship_count"] == 1
    assert plan["live_relationship_count"] == 1
    assert plan["blocked_relationship_count"] == 0
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 0
    assert plan["root_reachable_scoped_image_part_count"] == 1
    assert plan["projected_root_reachable_scoped_image_part_count"] == 1


def test_inspect_pptx_media_gc_plan_excludes_explicit_zip_directories_from_graph() -> None:
    baseline = inspect_pptx(
        _pptx(),
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]
    with_directory = inspect_pptx(
        _pptx(extra_parts={"ppt/media/": b""}),
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert with_directory["graph_part_count"] == baseline["graph_part_count"]
    assert with_directory["root_reachable_part_count"] == (baseline["root_reachable_part_count"])
    assert with_directory["root_unreachable_part_count"] == (baseline["root_unreachable_part_count"])


def test_inspect_pptx_media_gc_plan_handles_cycles_and_multiple_root_paths() -> None:
    root_relationships = _ROOT_RELATIONSHIPS.replace(
        "</Relationships>",
        """  <Relationship Id="rIdCustomA" Type="urn:vassilflow:test:custom" Target="ppt/customXml/a.xml"/>
  <Relationship Id="rIdCustomB" Type="urn:vassilflow:test:custom" Target="ppt/customXml/b.xml"/>
</Relationships>""",
    )
    source_a = """<x:item xmlns:x="urn:vassilflow:test" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rIdB"/>"""
    source_b = """<x:item xmlns:x="urn:vassilflow:test" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rIdA" r:embed="rIdImage"/>"""
    relationships_a = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdB" Type="urn:vassilflow:test:peer" Target="b.xml"/>
    </Relationships>"""
    relationships_b = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdA" Type="urn:vassilflow:test:peer" Target="a.xml"/>
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/cycle.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/customXml/a.xml" ContentType="application/xml"/>
  <Override PartName="/ppt/customXml/b.xml" ContentType="application/xml"/>
</Types>""",
    )
    document = _pptx(
        root_relationships=root_relationships,
        content_types=content_types,
        extra_parts={
            "ppt/customXml/a.xml": source_a,
            "ppt/customXml/b.xml": source_b,
            "ppt/customXml/_rels/a.xml.rels": relationships_a,
            "ppt/customXml/_rels/b.xml.rels": relationships_b,
            "ppt/media/cycle.png": _png(),
        },
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["package_xml_integrity_complete"] is True
    assert plan["root_reachable_scoped_image_part_count"] == 1
    assert plan["projected_root_reachable_scoped_image_part_count"] == 1
    assert plan["live_relationship_count"] == 1
    assert plan["relationship_candidate_count"] == 0
    assert plan["root_unreachable_scoped_image_evidence_count"] == 0


def test_inspect_pptx_media_gc_plan_blocks_undeclared_non_slide_xml_reference() -> None:
    theme = """<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" name="Broken"><a:themeElements r:id="rIdMissing"/></a:theme>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
</Types>""",
    )
    document = _pptx(
        content_types=content_types,
        extra_parts={
            "ppt/theme/theme1.xml": theme,
            "ppt/media/image1.png": _png(),
        },
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is False
    assert plan["package_xml_integrity_complete"] is False
    assert plan["undeclared_relationship_reference_count"] == 1
    assert plan["package_integrity_blocker_count"] == 1
    assert plan["part_candidate_count"] == 1
    assert plan["part_candidates"][0]["actionable"] is False
    assert plan["blockers"] == [
        {
            "actionable": False,
            "reason": "undeclared_xml_relationship_reference",
            "source_content_type": ("application/vnd.openxmlformats-officedocument.theme+xml"),
            "source_size_bytes": len(theme.encode()),
            "source_part_sha256": hashlib.sha256(theme.encode()).hexdigest(),
            "source_part": "ppt/theme/theme1.xml",
            "relationship_id": "rIdMissing",
        }
    ]


def test_inspect_pptx_media_gc_plan_ignores_non_reference_relationship_namespace_attributes() -> None:
    source = """<x:item xmlns:x="urn:vassilflow:test" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:label="not-a-relationship-id"/>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Override PartName="/ppt/customXml/item1.xml" ContentType="application/xml"/>
</Types>""",
    )
    document = _pptx(
        content_types=content_types,
        extra_parts={"ppt/customXml/item1.xml": source},
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["package_xml_integrity_complete"] is True
    assert plan["undeclared_relationship_reference_count"] == 0
    assert plan["package_integrity_blocker_count"] == 0


def test_inspect_pptx_media_gc_plan_reports_unreachable_live_owner_island() -> None:
    source = """<x:item xmlns:x="urn:vassilflow:test" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rIdImage"/>"""
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/island.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/customXml/item1.xml" ContentType="application/xml"/>
</Types>""",
    )
    document = _pptx(
        content_types=content_types,
        extra_parts={
            "ppt/customXml/item1.xml": source,
            "ppt/customXml/_rels/item1.xml.rels": relationships,
            "ppt/media/island.png": _png(),
        },
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["live_relationship_count"] == 1
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 0
    assert plan["root_unreachable_scoped_image_part_count"] == 1
    assert plan["projected_root_unreachable_scoped_image_part_count"] == 1
    assert plan["root_unreachable_scoped_image_evidence_count"] == 1
    assert plan["root_unreachable_scoped_image_evidence_returned"] == 1
    assert plan["root_unreachable_scoped_image_evidence_truncated"] is False
    evidence = plan["root_unreachable_scoped_image_evidence"][0]
    assert evidence["actionable"] is False
    assert evidence["reason"] == "unreachable_from_package_root"
    assert evidence["part_name"] == "ppt/media/island.png"
    assert evidence["sha256"] == hashlib.sha256(_png()).hexdigest()
    assert evidence["root_reachable_before_zero_ref_filter"] is False
    assert evidence["root_reachable_after_zero_ref_filter"] is False
    assert evidence["relationship_count"] == 1
    assert evidence["live_relationship_count"] == 1
    assert evidence["incoming_relationships_count"] == 1
    assert evidence["incoming_relationships_truncated"] is False
    incoming = evidence["incoming_relationships"][0]
    assert incoming["source_part"] == "ppt/customXml/item1.xml"
    assert incoming["source_part_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert incoming["relationship_part"] == ("ppt/customXml/_rels/item1.xml.rels")
    assert incoming["relationship_part_sha256"] == hashlib.sha256(relationships.encode()).hexdigest()
    assert incoming["relationship_id"] == "rIdImage"
    assert incoming["state"] == "live"
    assert incoming["xml_reference_count"] == 1
    assert incoming["source_root_reachable"] is False


def test_inspect_pptx_media_gc_plan_counts_background_group_and_svg_references() -> None:
    background = """<p:bg><p:bgPr><a:blipFill><a:blip r:embed="rIdBackground"/><a:stretch><a:fillRect/></a:stretch></a:blipFill></p:bgPr></p:bg>"""
    grouped_picture = """<p:grpSp>
      <p:nvGrpSpPr><p:cNvPr id="10" name="Group"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
      <p:pic><p:nvPicPr><p:cNvPr id="11" name="Grouped image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
        <p:blipFill><a:blip r:embed="rIdGroup"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/>
      </p:pic>
    </p:grpSp>"""
    svg_picture = """<p:pic>
      <p:nvPicPr><p:cNvPr id="12" name="SVG image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
      <p:blipFill><a:blip r:embed="rIdFallback"><a:extLst><a:ext uri="{28A0092B-C50C-407E-A947-70E740481C1C}">
        <asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" r:embed="rIdSvg"/>
      </a:ext></a:extLst></a:blip><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/>
    </p:pic>"""
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdBackground" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/background.png"/>
      <Relationship Id="rIdGroup" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/group.png"/>
      <Relationship Id="rIdFallback" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/fallback.png"/>
      <Relationship Id="rIdSvg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/vector.svg"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="svg" ContentType="image/svg+xml"/>
</Types>""",
    )
    document = _pptx(
        slide2=_slide(
            grouped_picture + svg_picture,
            background=background,
        ),
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={
            "ppt/media/background.png": _png(),
            "ppt/media/group.png": _png(color=(1, 2, 3)),
            "ppt/media/fallback.png": _png(color=(4, 5, 6)),
            "ppt/media/vector.svg": b'<svg xmlns="http://www.w3.org/2000/svg"/>',
        },
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["image_part_count"] == 4
    assert plan["image_relationship_count"] == 4
    assert plan["live_relationship_count"] == 4
    assert plan["unreferenced_relationship_count"] == 0
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 0


def test_inspect_pptx_media_gc_plan_blocks_opaque_and_nonstandard_sources() -> None:
    slide_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdCustom" Type="https://vassilflow.example/relationships/custom-image" Target="../media/image2.png"/>
    </Relationships>"""
    opaque_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdOpaque" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        """  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="bin" ContentType="application/octet-stream"/>
</Types>""",
    )
    document = _pptx(
        slide2_relationships=slide_relationships,
        content_types=content_types,
        extra_parts={
            "ppt/embeddings/source.bin": b"<root/>",
            "ppt/embeddings/_rels/source.bin.rels": opaque_relationships,
            "ppt/media/image1.png": _png(),
            "ppt/media/image2.png": _png(color=(1, 2, 3)),
        },
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is False
    assert plan["image_relationship_count"] == 2
    assert plan["standard_image_relationship_count"] == 1
    assert plan["nonstandard_image_relationship_count"] == 1
    assert plan["live_relationship_count"] == 0
    assert plan["unreferenced_relationship_count"] == 0
    assert plan["blocked_relationship_count"] == 2
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 0
    assert {blocker["reason"] for blocker in plan["blockers"]} == {
        "nonstandard_image_relationship_type",
        "relationship_source_content_type_is_not_xml",
    }


def test_inspect_pptx_media_gc_plan_fails_closed_at_relationship_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_MEDIA_GC_RELATIONSHIPS", 0)
    document = _picture_source_pptx()

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is False
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 0
    assert plan["blockers"] == [
        {
            "reason": "relationship_scan_limit_exceeded",
            "relationship_limit": 0,
            "relationship_count": 1,
        }
    ]


def test_inspect_pptx_media_gc_plan_fails_closed_at_xml_scan_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_MEDIA_GC_TOTAL_XML_BYTES", 0)
    document = _picture_source_pptx()

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is False
    assert plan["live_relationship_count"] == 0
    assert plan["unreferenced_relationship_count"] == 0
    assert plan["blocked_relationship_count"] == 1
    assert plan["relationship_candidate_count"] == 0
    assert plan["part_candidate_count"] == 0
    assert plan["package_xml_integrity_complete"] is False
    assert plan["relationship_source_blocker_count"] == 1
    assert plan["package_integrity_blocker_count"] >= 1
    assert {blocker["reason"] for blocker in plan["blockers"]} == {"xml_source_scan_budget_exhausted"}


def test_inspect_pptx_media_gc_plan_bounds_candidate_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_MEDIA_GC_PART_CANDIDATES", 0)
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    document = _pptx(
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": _png()},
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["part_candidate_count"] == 1
    assert plan["part_candidates_returned"] == 0
    assert plan["part_candidates_truncated"] is True
    assert plan["part_candidates"] == []
    assert plan["output_truncated"] is True


def test_inspect_pptx_media_gc_plan_bounds_unreachable_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_MEDIA_GC_UNREACHABLE_IMAGE_PARTS", 0)
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    document = _pptx(
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": _png()},
    )

    plan = inspect_pptx(
        document,
        max_slides=1,
        include_media_gc_plan=True,
    )["media_gc_plan"]

    assert plan["analysis_complete"] is True
    assert plan["root_unreachable_scoped_image_evidence_count"] == 1
    assert plan["root_unreachable_scoped_image_evidence_returned"] == 0
    assert plan["root_unreachable_scoped_image_evidence_truncated"] is True
    assert plan["root_unreachable_scoped_image_evidence"] == []
    assert plan["output_truncated"] is True


def test_pptx_selector_does_not_reclassify_full_slide_resource_owners() -> None:
    inspected = inspect_pptx(
        _resource_pptx(),
        max_slides=1,
        selector=PptxObjectSelector(kinds=["chart"]),
    )
    slide = inspected["slides"][0]
    resources = {(item["source_part"], item["relationship_id"]): item for item in slide["resources"]}

    assert slide["matched_object_count"] == 1
    assert [item["path"] for item in slide["objects"]] == ["/slide[1]/chart[@id=5]"]
    assert resources[("ppt/slides/slide2.xml", "rIdImage")]["owner_paths"] == ["/slide[1]/picture[@id=6]"]
    assert resources[("ppt/slides/slide2.xml", "rIdLink")]["owner_paths"] == ["/slide[1]/shape[@id=7]"]


def test_inspect_pptx_caps_object_and_resource_output_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_OBJECTS", 2)
    monkeypatch.setattr(pptx_module, "_MAX_INSPECT_RESOURCES", 3)

    inspected = inspect_pptx(_resource_pptx(), max_slides=1)
    slide = inspected["slides"][0]

    assert slide["object_count"] == 3
    assert slide["objects_returned"] == 2
    assert slide["objects_truncated"] is True
    assert slide["resource_count"] == 7
    assert slide["resources_returned"] == 3
    assert slide["resources_truncated"] is True
    assert inspected["selected_objects_truncated"] is True
    assert inspected["selected_resources_truncated"] is True


def test_inspect_pptx_caps_scheduled_resource_graph_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pptx_module, "_MAX_RESOURCE_GRAPH_EDGES_PER_SLIDE", 3)

    inspected = inspect_pptx(_resource_pptx(), max_slides=1)
    slide = inspected["slides"][0]

    assert slide["resource_count"] == 3
    assert slide["resources_returned"] == 3
    assert slide["resources_truncated"] is True
    assert inspected["selected_resources_truncated"] is True


def test_inspect_pptx_resource_depth_uses_shortest_dependency_path() -> None:
    slide_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdChain" Type="http://schemas.example.test/relationships/dependency" Target="../custom/link.xml"/>
      <Relationship Id="rIdDirect" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/>
    </Relationships>"""
    link_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdToChart" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/>
    </Relationships>"""
    chart_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdData" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" Target="../embeddings/book.xlsx"/>
    </Relationships>"""
    document = _pptx(
        slide2=_slide(""),
        slide2_relationships=slide_relationships,
        extra_parts={
            "ppt/custom/link.xml": "<link/>",
            "ppt/custom/_rels/link.xml.rels": link_relationships,
            "ppt/charts/chart1.xml": "<chart/>",
            "ppt/charts/_rels/chart1.xml.rels": chart_relationships,
            "ppt/embeddings/book.xlsx": "workbook",
        },
    )

    resources = inspect_pptx(document, max_slides=1)["slides"][0]["resources"]
    chart_data = next(item for item in resources if item["source_part"] == "ppt/charts/chart1.xml" and item["relationship_id"] == "rIdData")

    assert chart_data["depth"] == 1
    assert chart_data["owner_paths"] == ["/slide[1]"]


def test_inspect_pptx_reports_notes_on_relationship_resolved_slide() -> None:
    inspected = inspect_pptx(_pptx(), start_slide=2, max_slides=1)

    assert inspected["slides"][0]["part_name"] == "ppt/slides/slide1.xml"
    assert inspected["slides"][0]["inventory"]["has_notes"] is True


@pytest.mark.parametrize(
    ("start_slide", "max_slides", "message"),
    [(0, 1, "start_slide"), (1, 0, "max_slides"), (1, 51, "max_slides")],
)
def test_inspect_pptx_rejects_unbounded_windows(
    start_slide: int,
    max_slides: int,
    message: str,
) -> None:
    with pytest.raises(OfficeOperationError, match=message):
        inspect_pptx(_pptx(), start_slide=start_slide, max_slides=max_slides)


def test_validate_pptx_accepts_empty_relationship_id_on_action_hyperlink() -> None:
    slide = _slide(_shape("Action") + '<p:sp><p:nvSpPr><p:cNvPr id="9" name="Action"><a:hlinkClick r:id="" action="ppaction://hlinkshowjump?jump=nextslide"/></p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/></p:sp>')

    assert validate_pptx(_pptx(slide1=slide))["valid"] is True


def test_validate_pptx_accepts_relationship_resolved_slide_jump_action() -> None:
    slide = _slide(_shape("Jump") + '<p:sp><p:nvSpPr><p:cNvPr id="9" name="Jump"><a:hlinkClick r:id="rIdJump" action="ppaction://hlinksldjump"/></p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/></p:sp>')
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdJump" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slide2.xml"/>
    </Relationships>"""

    assert validate_pptx(_pptx(slide1=slide, slide1_relationships=relationships))["valid"] is True


def test_validate_pptx_renderable_rejects_unsafe_slide_action() -> None:
    slide = _slide(_shape("Unsafe") + '<p:sp><p:nvSpPr><p:cNvPr id="9" name="Unsafe"><a:hlinkClick r:id="" action="javascript:alert(1)"/></p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/></p:sp>')
    document = _pptx(slide1=slide)

    assert validate_pptx(document)["risky_features"] == ["unsafe actions"]
    interaction = inspect_pptx(
        document,
        start_slide=2,
        max_slides=1,
    )["slides"][0]["objects"][1]["interactions"][0]
    assert interaction["target_kind"] == "unsafe_action"
    assert interaction["unsafe_action"] is True
    with pytest.raises(OfficeOperationError, match="unsafe actions"):
        validate_pptx_renderable(document)


def test_validate_pptx_rejects_broken_slide_relationship_reference() -> None:
    slide = _slide(_shape("Broken") + '<p:pic><p:nvPicPr><p:cNvPr id="8" name="Broken"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rMissing"/></p:blipFill><p:spPr/></p:pic>')

    with pytest.raises(OfficePackageError, match="rMissing"):
        validate_pptx(_pptx(slide1=slide))


@pytest.mark.parametrize("target_mode", ["Bogus", ""])
def test_validate_pptx_rejects_invalid_relationship_target_mode(
    target_mode: str,
) -> None:
    relationships = f"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdTarget" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slide2.xml" TargetMode="{target_mode}"/>
    </Relationships>"""

    with pytest.raises(OfficePackageError, match="invalid TargetMode"):
        validate_pptx(_pptx(slide1_relationships=relationships))


def test_validate_pptx_rejects_relationship_part_without_source_owner() -> None:
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdSlide" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="../slides/slide1.xml"/>
    </Relationships>"""

    with pytest.raises(OfficePackageError, match="missing source part"):
        validate_pptx(
            _pptx(
                extra_parts={
                    "ppt/custom/_rels/missing.xml.rels": relationships,
                }
            )
        )


def test_validate_pptx_renderable_allows_safe_external_hyperlinks() -> None:
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.test" TargetMode="External"/>
    </Relationships>"""
    document = _pptx(slide1_relationships=relationships)

    assert validate_pptx(document)["risky_features"] == ["external hyperlinks"]
    assert validate_pptx_renderable(document)["valid"] is True


def test_validate_pptx_renderable_rejects_external_linked_resources() -> None:
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="https://example.test/image.png" TargetMode="External"/>
    </Relationships>"""
    document = _pptx(slide1_relationships=relationships)

    assert validate_pptx(document)["risky_features"] == ["external relationships"]
    with pytest.raises(OfficeOperationError, match="external relationships"):
        validate_pptx_renderable(document)


@pytest.mark.parametrize("target", ["file:///tmp/local.png", "javascript:alert(1)"])
def test_validate_pptx_renderable_rejects_unsafe_external_hyperlinks(target: str) -> None:
    relationships = f"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{target}" TargetMode="External"/>
    </Relationships>"""
    document = _pptx(slide1_relationships=relationships)

    assert validate_pptx(document)["risky_features"] == ["external relationships"]
    with pytest.raises(OfficeOperationError, match="external relationships"):
        validate_pptx_renderable(document)


def test_validate_pptx_rejects_missing_nested_layout_relationship_target() -> None:
    slide_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdLayout" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
    </Relationships>"""
    layout_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdMaster" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/missing.xml"/>
    </Relationships>"""

    with pytest.raises(OfficePackageError, match="targets a missing part"):
        validate_pptx(
            _pptx(
                slide1_relationships=slide_relationships,
                extra_parts={
                    "ppt/slideLayouts/slideLayout1.xml": "<layout/>",
                    "ppt/slideLayouts/_rels/slideLayout1.xml.rels": layout_relationships,
                },
            )
        )


def test_validate_pptx_rejects_missing_nested_chart_relationship_target() -> None:
    slide_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdChart" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/>
    </Relationships>"""
    chart_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdData" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" Target="../embeddings/missing.xlsx"/>
    </Relationships>"""

    with pytest.raises(OfficePackageError, match="targets a missing part"):
        validate_pptx(
            _pptx(
                slide1_relationships=slide_relationships,
                extra_parts={
                    "ppt/charts/chart1.xml": "<chart/>",
                    "ppt/charts/_rels/chart1.xml.rels": chart_relationships,
                },
            )
        )


def test_validate_pptx_rejects_macro_enabled_main_content_type() -> None:
    macro_types = _CONTENT_TYPES.replace(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml",
    )

    with pytest.raises(OfficePackageError, match="macro-free"):
        validate_pptx(_pptx(content_types=macro_types))


def test_edit_pptx_replaces_split_run_text_and_preserves_package() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    before = inspect_pptx(
        document,
        max_slides=1,
        include_formatting=True,
    )

    edited, reports = edit_pptx(
        document,
        [
            PptxTextReplacement(
                paths=["/slide[1]/shape[@id=7]"],
                find="AlphaBeta",
                replace="Gamma",
            )
        ],
    )

    assert reports == [
        {
            "operation": 1,
            "type": "replace_pptx_text",
            "occurrence": "all",
            "match_count": 1,
            "matched_paths": ["/slide[1]/shape[@id=7]"],
            "matched_paths_truncated": False,
        }
    ]
    after = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )
    before_shape = before["slides"][0]["objects"][0]
    after_shape = after["slides"][0]["objects"][0]
    before_segments = before_shape["text_body"]["paragraphs"][0]["segments"]
    after_segments = after_shape["text_body"]["paragraphs"][0]["segments"]

    assert after_shape["text_body"]["paragraphs"][0]["text"] == "Gamma\n\t42"
    assert after_shape["style"] == before_shape["style"]
    assert after_segments[0]["text"] == "Gamma"
    assert after_segments[1]["text"] == ""
    assert after_segments[0]["formatting"] == before_segments[0]["formatting"]
    assert after_segments[1]["formatting"] == before_segments[1]["formatting"]
    assert after_segments[2:] == before_segments[2:]
    assert validate_pptx(edited)["valid"] is True

    with (
        zipfile.ZipFile(io.BytesIO(document)) as source,
        zipfile.ZipFile(io.BytesIO(edited)) as result,
    ):
        assert source.comment == result.comment
        assert source.namelist() == result.namelist()
        for source_info, result_info in zip(
            source.infolist(),
            result.infolist(),
            strict=True,
        ):
            assert source_info.filename == result_info.filename
            assert source_info.date_time == result_info.date_time
            assert source_info.compress_type == result_info.compress_type
            assert source_info.comment == result_info.comment
            assert source_info.extra == result_info.extra
            if source_info.filename == "ppt/slides/slide2.xml":
                assert source.read(source_info) != result.read(result_info)
            else:
                assert source.read(source_info) == result.read(result_info)


def test_edit_pptx_applies_repeated_cross_run_matches_right_to_left() -> None:
    shape = """<p:sp>
      <p:nvSpPr><p:cNvPr id="9" name="Repeated text"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p>
        <a:r><a:rPr b="1"/><a:t>a</a:t></a:r>
        <a:r><a:t>ba</a:t></a:r>
        <a:r><a:rPr i="1"/><a:t>b</a:t></a:r>
      </a:p></p:txBody>
    </p:sp>"""
    document = _pptx(slide2=_slide(shape))

    edited, reports = edit_pptx(
        document,
        [
            PptxTextReplacement(
                paths=["/slide[1]/shape[@id=9]"],
                find="ab",
                replace="XYZ",
            )
        ],
    )

    inspected = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )
    paragraph = inspected["slides"][0]["objects"][0]["text_body"]["paragraphs"][0]
    assert reports[0]["match_count"] == 2
    assert paragraph["text"] == "XYZXYZ"
    assert paragraph["segments"][0]["formatting"]["bold"] is True
    assert paragraph["segments"][2]["formatting"]["italic"] is True


def test_edit_pptx_preserves_safe_external_hyperlink_relationships() -> None:
    document = _metadata_interactions_pptx()
    with zipfile.ZipFile(io.BytesIO(document)) as source:
        relationships = source.read("ppt/slides/_rels/slide2.xml.rels")

    edited, _ = edit_pptx(
        document,
        [
            PptxTextReplacement(
                paths=["/slide[1]/shape[@id=21]"],
                find="Details",
                replace="Summary",
            )
        ],
    )

    assert validate_pptx(edited)["risky_features"] == ["external hyperlinks"]
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        assert result.read("ppt/slides/_rels/slide2.xml.rels") == relationships


def test_edit_pptx_preserves_slide_root_siblings() -> None:
    slide = "<!--before-root--><?review keep?>" + _slide(_shape("original")) + "<!--after-root-->"
    document = _pptx(slide2=slide)

    edited, _ = edit_pptx(
        document,
        [
            PptxTextReplacement(
                paths=["/slide[1]/shape[@id=2]"],
                find="original",
                replace="updated",
            )
        ],
    )

    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        payload = result.read("ppt/slides/slide2.xml")
    assert b"<!--before-root-->" in payload
    assert b"<?review keep?>" in payload
    assert b"<!--after-root-->" in payload


def test_edit_pptx_rejects_matches_crossing_field_boundary() -> None:
    shape = """<p:sp>
      <p:nvSpPr><p:cNvPr id="9" name="Field text"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p>
        <a:r><a:t>left</a:t></a:r>
        <a:fld id="field-1" type="slidenum"><a:t>right</a:t></a:fld>
      </a:p></p:txBody>
    </p:sp>"""
    document = _pptx(slide2=_slide(shape))

    with pytest.raises(OfficeOperationError, match="field, break, tab"):
        edit_pptx(
            document,
            [
                PptxTextReplacement(
                    paths=["/slide[1]/shape[@id=9]"],
                    find="leftright",
                    replace="blocked",
                )
            ],
        )


def test_edit_pptx_rejects_matches_crossing_hyperlink_boundary() -> None:
    shape = """<p:sp>
      <p:nvSpPr><p:cNvPr id="9" name="Linked text"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p>
        <a:r><a:rPr><a:hlinkClick r:id="rIdExternal"/></a:rPr><a:t>linked</a:t></a:r>
        <a:r><a:t>plain</a:t></a:r>
      </a:p></p:txBody>
    </p:sp>"""
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.test" TargetMode="External"/>
    </Relationships>"""
    document = _pptx(
        slide2=_slide(shape),
        slide2_relationships=relationships,
    )

    with pytest.raises(OfficeOperationError, match="hyperlink, field"):
        edit_pptx(
            document,
            [
                PptxTextReplacement(
                    paths=["/slide[1]/shape[@id=9]"],
                    find="linkedplain",
                    replace="blocked",
                )
            ],
        )


def test_pptx_text_replacement_requires_exact_stable_shape_paths() -> None:
    with pytest.raises(ValueError, match="authored-ID stable paths"):
        PptxTextReplacement(
            paths=["/slide[1]/shape[1]"],
            find="old",
            replace="new",
        )
    with pytest.raises(ValueError, match="targets shapes only"):
        PptxTextReplacement(
            paths=["/slide[1]/table[@id=4]"],
            find="old",
            replace="new",
        )
    with pytest.raises(ValueError, match="tabs or line breaks"):
        PptxTextReplacement(
            paths=["/slide[1]/shape[@id=2]"],
            find="old\nvalue",
            replace="new",
        )
    with pytest.raises(ValueError, match="invalid XML text"):
        PptxTextReplacement(
            paths=["/slide[1]/shape[@id=2]"],
            find="old",
            replace="new\x00value",
        )


def test_edit_pptx_rejects_stale_paths_transactionally() -> None:
    document = _pptx(slide2=_slide(_shape("original")))

    with pytest.raises(OfficeOperationError, match="stale or missing paths"):
        edit_pptx(
            document,
            [
                PptxTextReplacement(
                    paths=["/slide[1]/shape[@id=999]"],
                    find="original",
                    replace="changed",
                )
            ],
        )

    inspected = inspect_pptx(
        document,
        max_slides=1,
        include_formatting=True,
    )
    assert inspected["slides"][0]["objects"][0]["text_body"]["paragraphs"][0]["text"] == "original"


def test_edit_pptx_required_operations_are_one_transaction() -> None:
    document = _pptx(slide2=_slide(_shape("original")))
    path = "/slide[1]/shape[@id=2]"

    with pytest.raises(OfficeOperationError, match="no presentation changes"):
        edit_pptx(
            document,
            [
                PptxTextReplacement(
                    paths=[path],
                    find="original",
                    replace="changed",
                ),
                PptxTextReplacement(
                    paths=[path],
                    find="missing",
                    replace="never written",
                ),
            ],
        )

    inspected = inspect_pptx(
        document,
        max_slides=1,
        include_formatting=True,
    )
    assert inspected["slides"][0]["objects"][0]["text_body"]["paragraphs"][0]["text"] == "original"


def test_edit_pptx_no_match_returns_exact_source_when_allowed() -> None:
    document = _pptx(slide2=_slide(_shape("original")))

    edited, reports = edit_pptx(
        document,
        [
            PptxTextReplacement(
                paths=["/slide[1]/shape[@id=2]"],
                find="missing",
                replace="never written",
                require_match=False,
            )
        ],
    )

    assert edited == document
    assert reports[0]["match_count"] == 0


def test_edit_pptx_text_only_gate_rejects_other_shape_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_shape("original")))
    replace_shape_text = pptx_module._replace_pptx_shape_text

    def mutate_shape(ref, **kwargs):
        result = replace_shape_text(ref, **kwargs)
        ref.element.set("unexpected", "1")
        return result

    monkeypatch.setattr(
        pptx_module,
        "_replace_pptx_shape_text",
        mutate_shape,
    )

    with pytest.raises(OfficeOperationError, match="unsupported structure"):
        edit_pptx(
            document,
            [
                PptxTextReplacement(
                    paths=["/slide[1]/shape[@id=2]"],
                    find="original",
                    replace="changed",
                )
            ],
        )


def test_edit_pptx_enforces_bounded_replacement_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_shape("alpha alpha")))
    monkeypatch.setattr(pptx_module, "_MAX_EDIT_TEXT_REPLACEMENTS", 1)

    with pytest.raises(OfficeOperationError, match="replacement limit"):
        edit_pptx(
            document,
            [
                PptxTextReplacement(
                    paths=["/slide[1]/shape[@id=2]"],
                    find="alpha",
                    replace="beta",
                )
            ],
        )


def test_pptx_formatting_models_require_stable_exact_targets_and_bounded_values() -> None:
    with pytest.raises(ValueError, match="exact authored-ID PPTX shape path"):
        PptxShapeTarget(
            path="/slide[1]/shape[1]",
            expected_name="Styled copy",
        )
    with pytest.raises(ValueError, match="shape or connector path"):
        PptxLineTarget(
            path="/slide[1]/picture[@id=6]",
            expected_name="Image",
        )
    with pytest.raises(ValueError, match="exact PPTX run path"):
        PptxRunTarget(
            path="/slide[1]/shape[1]/paragraph[1]/run[1]",
            expected_text="Alpha",
        )
    with pytest.raises(ValueError, match="exact PPTX paragraph path"):
        PptxParagraphTarget(
            path="/slide[1]/table[@id=4]/paragraph[1]",
            expected_text="Alpha",
        )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        PptxRunSelector(
            targets=[
                PptxRunTarget(
                    path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                    expected_text="Alpha",
                ),
                PptxRunTarget(
                    path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                    expected_text="Alpha",
                ),
            ]
        )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        PptxShapeSelector(
            targets=[
                PptxShapeTarget(
                    path="/slide[1]/shape[@id=7]",
                    expected_name="Styled copy",
                ),
                PptxShapeTarget(
                    path="/slide[1]/shape[@id=7]",
                    expected_name="Styled copy",
                ),
            ]
        )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        PptxLineSelector(
            targets=[
                PptxLineTarget(
                    path="/slide[1]/connector[@id=9]",
                    expected_name="Authored connector",
                ),
                PptxLineTarget(
                    path="/slide[1]/connector[@id=9]",
                    expected_name="Authored connector",
                ),
            ]
        )
    with pytest.raises(ValueError, match="at least one property"):
        PptxRunFormatting()
    with pytest.raises(ValueError, match="0.5-point increments"):
        PptxRunFormatting(font_size=12.25)
    with pytest.raises(ValueError, match="cannot be combined"):
        PptxRunFormatting(font="Aptos", font_latin="Arial")
    with pytest.raises(ValueError, match="0.01-point increments"):
        PptxParagraphFormatting(space_before=1.001)
    with pytest.raises(ValueError, match="mutually exclusive"):
        PptxParagraphFormatting(
            line_spacing_points=12,
            line_spacing_percent=125,
        )
    with pytest.raises(ValueError, match="solid PPTX fill requires color"):
        PptxShapeFillFormatting(type="solid")
    with pytest.raises(ValueError, match="does not accept color"):
        PptxShapeFillFormatting(type="none", color="112233")
    with pytest.raises(ValueError, match="requires stops, geometry, and rotate_with_shape"):
        PptxShapeFillFormatting(type="gradient")
    with pytest.raises(ValueError, match="requires preset, foreground_color, and background_color"):
        PptxShapeFillFormatting(type="pattern", preset="diagCross")
    with pytest.raises(ValueError, match="requires image_path and rotate_with_shape"):
        PptxShapeFillFormatting(type="image", image_path="/mnt/user-data/uploads/image.png")
    tile = PptxImageTileFormatting(
        offset_x_emu=127_000,
        offset_y_emu=-63_500,
        scale_x_percent=45,
        scale_y_percent=65,
        alignment="bottom_right",
        flip="horizontal",
    )
    with pytest.raises(ValueError, match="requires explicit tile properties"):
        PptxShapeFillFormatting(
            type="image",
            image_path="/mnt/user-data/uploads/image.png",
            rotate_with_shape=False,
            mode="tile",
        )
    with pytest.raises(ValueError, match="tile PPTX image fill does not support crop"):
        PptxShapeFillFormatting(
            type="image",
            image_path="/mnt/user-data/uploads/image.png",
            rotate_with_shape=False,
            mode="tile",
            tile=tile,
            crop=PptxImageCropFormatting(
                left_percent=1,
                top_percent=1,
                right_percent=1,
                bottom_percent=1,
            ),
        )
    with pytest.raises(ValueError, match="canonical framing"):
        PptxShapeFillFormatting(
            type="image",
            image_path="/mnt/user-data/uploads/image.png",
            rotate_with_shape=False,
            mode="center",
            tile=tile,
        )
    with pytest.raises(ValueError, match="stretch PPTX image fill does not accept tile"):
        PptxShapeFillFormatting(
            type="image",
            image_path="/mnt/user-data/uploads/image.png",
            rotate_with_shape=False,
            mode="stretch",
            tile=tile,
        )
    with pytest.raises(ValueError, match="0.001-percent increments"):
        PptxImageTileFormatting(
            offset_x_emu=0,
            offset_y_emu=0,
            scale_x_percent=45.0001,
            scale_y_percent=65,
            alignment="top_left",
            flip="none",
        )
    with pytest.raises(ValueError, match="does not accept solid, gradient, or pattern properties"):
        PptxShapeFillFormatting(
            type="image",
            image_path="/mnt/user-data/uploads/image.png",
            rotate_with_shape=False,
            color="112233",
        )
    with pytest.raises(ValueError, match="leave a visible area"):
        PptxImageCropFormatting(
            left_percent=60,
            top_percent=0,
            right_percent=40,
            bottom_percent=0,
        )
    with pytest.raises(ValueError, match="does not accept solid or gradient properties"):
        PptxShapeFillFormatting(
            type="pattern",
            preset="diagCross",
            foreground_color="112233",
            background_color="445566",
            color="778899",
        )
    with pytest.raises(ValueError):
        PptxShapeFillFormatting(
            type="pattern",
            preset="unknown",
            foreground_color="112233",
            background_color="445566",
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        PptxShapeFillFormatting(
            type="gradient",
            stops=[
                PptxGradientStopFormatting(position_percent=50, color="112233"),
                PptxGradientStopFormatting(position_percent=50, color="445566"),
            ],
            geometry=PptxLinearGradientFormatting(
                angle_degrees=45,
                scaled=True,
            ),
            rotate_with_shape=True,
        )
    with pytest.raises(ValueError, match="0.001-percent increments"):
        PptxGradientStopFormatting(
            position_percent=10.0001,
            color="112233",
        )
    with pytest.raises(ValueError, match="1/60000-degree increments"):
        PptxLinearGradientFormatting(
            angle_degrees=10.000001,
            scaled=True,
        )
    with pytest.raises(ValueError, match="sum to 100 percent"):
        PptxGradientRectangleFormatting(
            left_percent=35,
            top_percent=25,
            right_percent=60,
            bottom_percent=75,
        )
    with pytest.raises(ValueError, match="linear gradients only"):
        PptxShapeLineFormatting(fill=_matching_path_gradient_formatting())
    with pytest.raises(ValueError, match="do not support pattern fills"):
        PptxShapeLineFormatting(fill=_matching_pattern_formatting())
    with pytest.raises(ValueError, match="do not support image fills"):
        PptxShapeLineFormatting(fill=_image_fill_formatting())
    with pytest.raises(ValueError):
        PptxPresetGeometryFormatting(preset="customShape")
    with pytest.raises(ValueError, match="0.01-point increments"):
        PptxShapeLineFormatting(width_points=1.001)
    assert (
        PptxShapeLineFormatting(
            cap="square",
            dash="large_dash_dot_dot",
            join="miter",
            miter_limit_percent=800,
        ).miter_limit_percent
        == 800
    )
    with pytest.raises(ValueError, match="requires join=miter"):
        PptxShapeLineFormatting(
            join="round",
            miter_limit_percent=800,
        )
    with pytest.raises(ValueError, match="0.001-percent increments"):
        PptxShapeLineFormatting(
            join="miter",
            miter_limit_percent=1.0001,
        )
    with pytest.raises(ValueError, match="at least one property"):
        PptxLineFormatting()
    with pytest.raises(ValueError, match="at least one property"):
        PptxLineEndFormatting()
    with pytest.raises(ValueError, match="does not accept width or length"):
        PptxLineEndFormatting(type="none", width="small")
    assert (
        PptxLineFormatting(
            compound="thick_thin",
            alignment="inset",
            head_end=PptxLineEndFormatting(type="arrow", width="small", length="large"),
        ).compound
        == "thick_thin"
    )
    with pytest.raises(ValueError, match="at least one property"):
        PptxShapeFormatting()
    with pytest.raises(ValueError, match="at least one property"):
        PptxTextBoxFormatting()


def test_edit_pptx_formats_exact_run_and_preserves_other_content() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    before = inspect_pptx(
        document,
        max_slides=1,
        include_formatting=True,
    )

    edited, reports = edit_pptx(
        document,
        [
            PptxRunFormatOperation(
                runs=PptxRunSelector(
                    targets=[
                        PptxRunTarget(
                            path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                            expected_text="Alpha",
                        )
                    ]
                ),
                formatting=PptxRunFormatting(
                    bold=False,
                    italic=True,
                    underline="single",
                    strike="double",
                    color="#123abc",
                    font="Aptos",
                    font_complex_script="Arial",
                    font_size=30.5,
                ),
            )
        ],
    )

    assert reports == [
        {
            "operation": 1,
            "type": "format_pptx_runs",
            "match_count": 1,
            "matched_paths": ["/slide[1]/shape[@id=7]/paragraph[1]/run[1]"],
            "matched_paths_truncated": False,
        }
    ]
    after = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )
    before_shape = before["slides"][0]["objects"][0]
    after_shape = after["slides"][0]["objects"][0]
    before_paragraph = before_shape["text_body"]["paragraphs"][0]
    after_paragraph = after_shape["text_body"]["paragraphs"][0]
    formatting = after_paragraph["segments"][0]["formatting"]

    assert after_shape["style"] == before_shape["style"]
    assert after_paragraph["text"] == before_paragraph["text"]
    assert after_paragraph["formatting"] == before_paragraph["formatting"]
    assert after_paragraph["segments"][1:] == before_paragraph["segments"][1:]
    assert formatting["fonts"] == {
        "latin": "Aptos",
        "east_asia": "Aptos",
        "complex_script": "Arial",
    }
    assert formatting["font_size_points"] == 30.5
    assert formatting["bold"] is False
    assert formatting["italic"] is True
    assert formatting["underline"] == "single"
    assert formatting["strike"] == "double"
    assert formatting["language"] == "en-US"
    assert formatting["fill"] == {
        "type": "solid",
        "color": {"type": "rgb", "value": "#123ABC"},
    }
    assert validate_pptx(edited)["valid"] is True

    with (
        zipfile.ZipFile(io.BytesIO(document)) as source,
        zipfile.ZipFile(io.BytesIO(edited)) as result,
    ):
        for name in source.namelist():
            if name == "ppt/slides/slide2.xml":
                assert source.read(name) != result.read(name)
            else:
                assert source.read(name) == result.read(name)


def test_edit_pptx_run_color_preserves_existing_alpha_transform() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))

    edited, _ = edit_pptx(
        document,
        [
            PptxRunFormatOperation(
                runs=PptxRunSelector(
                    targets=[
                        PptxRunTarget(
                            path="/slide[1]/shape[@id=7]/paragraph[1]/run[2]",
                            expected_text="Beta",
                        )
                    ]
                ),
                formatting=PptxRunFormatting(color="#112233"),
            )
        ],
    )

    run = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["text_body"]["paragraphs"][0]["segments"][1]
    assert run["formatting"]["fill"] == {
        "type": "solid",
        "color": {
            "type": "rgb",
            "value": "#112233",
            "opacity_percent": 50.0,
        },
    }
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert b'<a:srgbClr val="112233"><a:alpha val="50000"/></a:srgbClr>' in slide_xml


def test_edit_pptx_run_font_preserves_existing_font_metadata() -> None:
    shape = """<p:sp>
      <p:nvSpPr><p:cNvPr id="10" name="Font metadata"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>
        <a:rPr><a:latin typeface="Original" panose="020F0502020204030204" pitchFamily="34" charset="0"/></a:rPr>
        <a:t>Metadata</a:t>
      </a:r></a:p></p:txBody>
    </p:sp>"""
    document = _pptx(slide2=_slide(shape))

    edited, _ = edit_pptx(
        document,
        [
            PptxRunFormatOperation(
                runs=PptxRunSelector(
                    targets=[
                        PptxRunTarget(
                            path="/slide[1]/shape[@id=10]/paragraph[1]/run[1]",
                            expected_text="Metadata",
                        )
                    ]
                ),
                formatting=PptxRunFormatting(font_latin="Updated"),
            )
        ],
    )

    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert (b'<a:latin typeface="Updated" panose="020F0502020204030204" pitchFamily="34" charset="0"/>') in slide_xml


def test_edit_pptx_underline_none_clears_authored_line_and_fill_children() -> None:
    shape = """<p:sp>
      <p:nvSpPr><p:cNvPr id="11" name="Underline metadata"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>
        <a:rPr u="sng">
          <a:uLn><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></a:uLn>
          <a:uFill><a:solidFill><a:srgbClr val="00FF00"/></a:solidFill></a:uFill>
        </a:rPr>
        <a:t>Underlined</a:t>
      </a:r></a:p></p:txBody>
    </p:sp>"""
    document = _pptx(slide2=_slide(shape))

    edited, _ = edit_pptx(
        document,
        [
            PptxRunFormatOperation(
                runs=PptxRunSelector(
                    targets=[
                        PptxRunTarget(
                            path="/slide[1]/shape[@id=11]/paragraph[1]/run[1]",
                            expected_text="Underlined",
                        )
                    ]
                ),
                formatting=PptxRunFormatting(underline="none"),
            )
        ],
    )

    run = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["text_body"]["paragraphs"][0]["segments"][0]
    assert run["formatting"]["underline"] == "none"
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert b"<a:uLn" not in slide_xml
    assert b"<a:uFill" not in slide_xml


def test_edit_pptx_run_color_rejects_complex_fill_replacement() -> None:
    shape = """<p:sp>
      <p:nvSpPr><p:cNvPr id="12" name="Gradient run"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>
        <a:rPr><a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="000000"/></a:gs></a:gsLst></a:gradFill></a:rPr>
        <a:t>Gradient</a:t>
      </a:r></a:p></p:txBody>
    </p:sp>"""
    document = _pptx(slide2=_slide(shape))

    with pytest.raises(OfficeOperationError, match="cannot replace a gradient"):
        edit_pptx(
            document,
            [
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path="/slide[1]/shape[@id=12]/paragraph[1]/run[1]",
                                expected_text="Gradient",
                            )
                        ]
                    ),
                    formatting=PptxRunFormatting(color="#112233"),
                )
            ],
        )


def test_edit_pptx_formats_exact_paragraph_and_preserves_runs_and_bullets() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    before = inspect_pptx(
        document,
        max_slides=1,
        include_formatting=True,
    )

    edited, reports = edit_pptx(
        document,
        [
            PptxParagraphFormatOperation(
                paragraphs=PptxParagraphSelector(
                    targets=[
                        PptxParagraphTarget(
                            path="/slide[1]/shape[@id=7]/paragraph[1]",
                            expected_text="AlphaBeta\n\t42",
                        )
                    ]
                ),
                formatting=PptxParagraphFormatting(
                    alignment="left",
                    space_before=6.25,
                    space_after=8.5,
                    line_spacing_percent=125.125,
                ),
            )
        ],
    )

    assert reports[0]["type"] == "format_pptx_paragraphs"
    assert reports[0]["match_count"] == 1
    after = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )
    before_paragraphs = before["slides"][0]["objects"][0]["text_body"]["paragraphs"]
    after_paragraphs = after["slides"][0]["objects"][0]["text_body"]["paragraphs"]
    formatting = after_paragraphs[0]["formatting"]

    assert after_paragraphs[0]["text"] == before_paragraphs[0]["text"]
    assert after_paragraphs[0]["segments"] == before_paragraphs[0]["segments"]
    assert after_paragraphs[1] == before_paragraphs[1]
    assert formatting == {
        "alignment": "left",
        "indent_emu": -500,
        "margin_left_emu": 1000,
        "right_to_left": False,
        "line_spacing": {"unit": "percent", "value": 125.125},
        "space_before": {"unit": "points", "value": 6.25},
        "space_after": {"unit": "points", "value": 8.5},
        "bullet": {"type": "character", "character": "\u2022"},
    }
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert slide_xml.index(b"<a:lnSpc") < slide_xml.index(b"<a:spcBef")
    assert slide_xml.index(b"<a:spcBef") < slide_xml.index(b"<a:spcAft")
    assert slide_xml.index(b"<a:spcAft") < slide_xml.index(b"<a:buChar")


def test_edit_pptx_formatting_rejects_stale_text_and_paths_transactionally() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))

    with pytest.raises(OfficeOperationError, match="expected_text no longer matches"):
        edit_pptx(
            document,
            [
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                                expected_text="Outdated",
                            )
                        ]
                    ),
                    formatting=PptxRunFormatting(bold=False),
                )
            ],
        )
    with pytest.raises(OfficeOperationError, match="stale or missing paths"):
        edit_pptx(
            document,
            [
                PptxParagraphFormatOperation(
                    paragraphs=PptxParagraphSelector(
                        targets=[
                            PptxParagraphTarget(
                                path="/slide[1]/shape[@id=999]/paragraph[1]",
                                expected_text="AlphaBeta\n\t42",
                            )
                        ]
                    ),
                    formatting=PptxParagraphFormatting(alignment="left"),
                )
            ],
        )

    assert (
        inspect_pptx(
            document,
            max_slides=1,
            include_formatting=True,
        )["slides"][0]["objects"][0]["text_body"]["paragraphs"][0]["formatting"]["alignment"]
        == "center"
    )


def test_edit_pptx_preflights_all_formatting_guards_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    called = False
    apply_formatting = pptx_module._apply_pptx_run_formatting

    def record_formatting(run, formatting):
        nonlocal called
        called = True
        return apply_formatting(run, formatting)

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_run_formatting",
        record_formatting,
    )

    with pytest.raises(OfficeOperationError, match="expected_text no longer matches"):
        edit_pptx(
            document,
            [
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                                expected_text="Alpha",
                            )
                        ]
                    ),
                    formatting=PptxRunFormatting(bold=False),
                ),
                PptxParagraphFormatOperation(
                    paragraphs=PptxParagraphSelector(
                        targets=[
                            PptxParagraphTarget(
                                path="/slide[1]/shape[@id=7]/paragraph[1]",
                                expected_text="Stale",
                            )
                        ]
                    ),
                    formatting=PptxParagraphFormatting(alignment="left"),
                ),
            ],
        )

    assert called is False


def test_edit_pptx_rejects_truncated_formatting_stale_guards() -> None:
    document = _pptx(slide2=_slide(_shape("x" * 4_001)))

    with pytest.raises(OfficeOperationError, match="longer than the 4,000-character"):
        edit_pptx(
            document,
            [
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path="/slide[1]/shape[@id=2]/paragraph[1]/run[1]",
                                expected_text="x" * 4_000,
                            )
                        ]
                    ),
                    formatting=PptxRunFormatting(bold=True),
                )
            ],
        )


def test_edit_pptx_mixes_text_and_run_formatting_when_rpr_is_absent() -> None:
    document = _pptx(slide2=_slide(_shape("original")))
    edited, reports = edit_pptx(
        document,
        [
            PptxTextReplacement(
                paths=["/slide[1]/shape[@id=2]"],
                find="original",
                replace="updated",
            ),
            PptxRunFormatOperation(
                runs=PptxRunSelector(
                    targets=[
                        PptxRunTarget(
                            path="/slide[1]/shape[@id=2]/paragraph[1]/run[1]",
                            expected_text="original",
                        )
                    ]
                ),
                formatting=PptxRunFormatting(bold=True, color="445566"),
            ),
        ],
    )

    assert [report["type"] for report in reports] == [
        "replace_pptx_text",
        "format_pptx_runs",
    ]
    paragraph = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["text_body"]["paragraphs"][0]
    assert paragraph["text"] == "updated"
    assert paragraph["segments"][0]["formatting"] == {
        "bold": True,
        "fill": {
            "type": "solid",
            "color": {"type": "rgb", "value": "#445566"},
        },
    }


def test_edit_pptx_run_formatting_preserves_hyperlinks_and_relationships() -> None:
    document = _metadata_interactions_pptx()
    with zipfile.ZipFile(io.BytesIO(document)) as source:
        relationships = source.read("ppt/slides/_rels/slide2.xml.rels")

    edited, _ = edit_pptx(
        document,
        [
            PptxRunFormatOperation(
                runs=PptxRunSelector(
                    targets=[
                        PptxRunTarget(
                            path="/slide[1]/shape[@id=21]/paragraph[1]/run[1]",
                            expected_text="Details",
                        )
                    ]
                ),
                formatting=PptxRunFormatting(bold=True, color="112233"),
            )
        ],
    )

    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
        assert result.read("ppt/slides/_rels/slide2.xml.rels") == relationships
    assert b"hlinkClick" in slide_xml
    assert b"hlinkMouseOver" in slide_xml
    assert validate_pptx(edited)["risky_features"] == ["external hyperlinks"]


def test_edit_pptx_noop_formatting_returns_exact_source() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))

    edited, reports = edit_pptx(
        document,
        [
            PptxRunFormatOperation(
                runs=PptxRunSelector(
                    targets=[
                        PptxRunTarget(
                            path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                            expected_text="Alpha",
                        )
                    ]
                ),
                formatting=PptxRunFormatting(bold=True),
            )
        ],
    )

    assert edited == document
    assert reports[0]["match_count"] == 1


def test_edit_pptx_formatting_gate_rejects_unrelated_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    apply_formatting = pptx_module._apply_pptx_run_formatting

    def mutate_paragraph(run, formatting):
        changed = apply_formatting(run, formatting)
        run.getparent().set("unexpected", "1")
        return changed

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_run_formatting",
        mutate_paragraph,
    )

    with pytest.raises(OfficeOperationError, match="unsupported structure"):
        edit_pptx(
            document,
            [
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                                expected_text="Alpha",
                            )
                        ]
                    ),
                    formatting=PptxRunFormatting(bold=False),
                )
            ],
        )


def test_edit_pptx_enforces_bounded_formatting_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    monkeypatch.setattr(pptx_module, "_MAX_EDIT_FORMATTING_TARGETS", 1)

    with pytest.raises(OfficeOperationError, match="formatting target limit"):
        edit_pptx(
            document,
            [
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                                expected_text="Alpha",
                            ),
                            PptxRunTarget(
                                path="/slide[1]/shape[@id=7]/paragraph[1]/run[2]",
                                expected_text="Beta",
                            ),
                        ]
                    ),
                    formatting=PptxRunFormatting(bold=False),
                )
            ],
        )


def test_edit_pptx_formats_exact_shape_and_preserves_unrelated_style() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    before = inspect_pptx(
        document,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]

    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=PptxShapeFillFormatting(type="solid", color="#123ABC"),
                    line=PptxShapeLineFormatting(
                        fill=PptxShapeFillFormatting(type="solid", color="#ABCDEF"),
                        width_points=3.25,
                        cap="square",
                        dash="large_dash_dot_dot",
                        join="miter",
                        miter_limit_percent=800,
                    ),
                    text_box=PptxTextBoxFormatting(
                        margin_left=10.5,
                        margin_top=11,
                        margin_right=12.25,
                        margin_bottom=13.75,
                        vertical_anchor="bottom",
                    ),
                ),
            )
        ],
    )

    assert reports == [
        {
            "operation": 1,
            "type": "format_pptx_shapes",
            "match_count": 1,
            "matched_paths": ["/slide[1]/shape[@id=7]"],
            "matched_paths_truncated": False,
        }
    ]
    after = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]
    assert after["text_body"] == before["text_body"]
    assert after["geometry"] == before["geometry"]
    assert after["style"]["geometry"] == before["style"]["geometry"]
    assert after["style"]["fill"] == {
        "type": "solid",
        "color": {
            "type": "rgb",
            "value": "#123ABC",
            "opacity_percent": 75.0,
        },
    }
    assert after["style"]["line"] == {
        "width_emu": 41_275,
        "cap": "square",
        "fill": {
            "type": "solid",
            "color": {"type": "rgb", "value": "#ABCDEF"},
        },
        "dash": "large_dash_dot_dot",
        "join": "miter",
        "miter_limit_percent": 800.0,
    }
    assert after["style"]["text_box"] == {
        "margins": {
            "left_emu": 133_350,
            "top_emu": 139_700,
            "right_emu": 155_575,
            "bottom_emu": 174_625,
        },
        "vertical_anchor": "bottom",
        "wrap": False,
        "right_to_left_columns": False,
        "autofit": "normal",
        "font_scale_percent": 92.5,
        "line_spacing_reduction_percent": 12.5,
    }
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert b'<a:srgbClr val="123ABC"><a:alpha val="75000"/></a:srgbClr>' in slide_xml
    assert b'<a:ln w="41275" cap="sq">' in slide_xml
    assert b'<a:prstDash val="lgDashDotDot"/><a:miter lim="800000"/>' in slide_xml


def test_edit_pptx_formats_typed_linear_gradient_shape_and_connector() -> None:
    document = _pptx(
        slide2=_slide(
            _formatted_shape() + _formatted_connector(),
        )
    )
    gradient = PptxShapeFillFormatting(
        type="gradient",
        stops=[
            PptxGradientStopFormatting(
                position_percent=0,
                color="#203864",
            ),
            PptxGradientStopFormatting(
                position_percent=42.5,
                color="#4472C4",
                opacity_percent=70,
            ),
            PptxGradientStopFormatting(
                position_percent=100,
                color="#70AD47",
            ),
        ],
        geometry=PptxLinearGradientFormatting(
            angle_degrees=125,
            scaled=False,
        ),
        rotate_with_shape=False,
    )

    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(fill=gradient),
            ),
            PptxLineFormatOperation(
                lines=PptxLineSelector(
                    targets=[
                        PptxLineTarget(
                            path="/slide[1]/connector[@id=9]",
                            expected_name="Authored connector",
                        )
                    ]
                ),
                formatting=PptxLineFormatting(fill=gradient),
            ),
        ],
    )

    assert [report["type"] for report in reports] == [
        "format_pptx_shapes",
        "format_pptx_lines",
    ]
    objects = {
        item["name"]: item
        for item in inspect_pptx(
            edited,
            max_slides=1,
            include_formatting=True,
        )["slides"][0]["objects"]
    }
    expected_gradient = {
        "type": "gradient",
        "rotate_with_shape": False,
        "stops": [
            {
                "position_percent": 0.0,
                "color": {"type": "rgb", "value": "#203864"},
            },
            {
                "position_percent": 42.5,
                "color": {
                    "type": "rgb",
                    "value": "#4472C4",
                    "opacity_percent": 70.0,
                },
            },
            {
                "position_percent": 100.0,
                "color": {"type": "rgb", "value": "#70AD47"},
            },
        ],
        "geometry": "linear",
        "angle_degrees": 125.0,
        "scaled": False,
    }
    assert objects["Styled copy"]["style"]["fill"] == expected_gradient
    assert objects["Styled copy"]["style"]["line"]["fill"] == {
        "type": "solid",
        "color": {"type": "scheme", "value": "accent1"},
    }
    assert objects["Authored connector"]["style"]["line"]["fill"] == expected_gradient
    assert objects["Authored connector"]["geometry"] == {
        "x_emu": 500,
        "y_emu": 600,
        "width_emu": 700,
        "height_emu": 800,
    }
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert slide_xml.count(b'<a:gradFill rotWithShape="0">') == 2
    assert slide_xml.count(b'<a:gs pos="42500"><a:srgbClr val="4472C4"><a:alpha val="70000"/></a:srgbClr></a:gs>') == 2
    assert slide_xml.count(b'<a:lin ang="7500000" scaled="0"/>') == 2


def test_edit_pptx_formats_typed_radial_gradient_and_preset_geometry() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))

    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_matching_path_gradient_formatting(),
                    geometry=PptxPresetGeometryFormatting(preset="hexagon"),
                ),
            )
        ],
    )

    assert reports[0]["type"] == "format_pptx_shapes"
    item = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]
    assert item["style"]["geometry"] == {
        "type": "preset",
        "preset": "hexagon",
    }
    assert item["style"]["fill"] == {
        "type": "gradient",
        "rotate_with_shape": False,
        "stops": [
            {
                "position_percent": 0.0,
                "color": {"type": "rgb", "value": "#FFFFFF"},
            },
            {
                "position_percent": 35.0,
                "color": {
                    "type": "rgb",
                    "value": "#5B9BD5",
                    "opacity_percent": 90.0,
                },
            },
            {
                "position_percent": 100.0,
                "color": {"type": "rgb", "value": "#203864"},
            },
        ],
        "geometry": "path",
        "path": "circle",
        "fill_to_rectangle": {
            "left_percent": 35.0,
            "top_percent": 25.0,
            "right_percent": 65.0,
            "bottom_percent": 75.0,
        },
    }
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert b'<a:prstGeom prst="hexagon"><a:avLst/></a:prstGeom>' in slide_xml
    assert b'<a:path path="circle"><a:fillToRect l="35000" t="25000" r="65000" b="75000"/></a:path>' in slide_xml


def test_edit_pptx_formats_typed_direct_rgb_pattern_fill() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    pattern = PptxShapeFillFormatting(
        type="pattern",
        preset="weave",
        foreground_color="#C00000",
        background_color="#FFF2CC",
    )

    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(fill=pattern),
            )
        ],
    )

    assert reports[0]["type"] == "format_pptx_shapes"
    item = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]
    assert item["style"]["fill"] == {
        "type": "pattern",
        "preset": "weave",
        "foreground_color": {"type": "rgb", "value": "#C00000"},
        "background_color": {"type": "rgb", "value": "#FFF2CC"},
    }
    assert item["style"]["geometry"] == {
        "type": "preset",
        "preset": "roundRect",
    }
    assert item["style"]["line"]["fill"] == {
        "type": "solid",
        "color": {"type": "scheme", "value": "accent1"},
    }
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert b'<a:pattFill prst="weave"><a:fgClr><a:srgbClr val="C00000"/></a:fgClr><a:bgClr><a:srgbClr val="FFF2CC"/></a:bgClr></a:pattFill>' in slide_xml


def test_edit_pptx_embeds_typed_png_shape_fill_with_new_opc_parts() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    image_path = "/mnt/user-data/uploads/replacement.png"
    image = _png(color=(112, 48, 160))
    fill = _image_fill_formatting(
        path=image_path,
        rotate_with_shape=True,
        crop=PptxImageCropFormatting(
            left_percent=5,
            top_percent=12.5,
            right_percent=15,
            bottom_percent=7.5,
        ),
    )

    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(fill=fill),
            )
        ],
        image_assets={image_path: image},
    )

    assert reports[0]["match_count"] == 1
    assert validate_pptx(edited)["valid"] is True
    item = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]
    assert item["style"]["fill"] == {
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
        "relationship_ids": ["rId1"],
    }
    with (
        zipfile.ZipFile(io.BytesIO(document)) as source,
        zipfile.ZipFile(io.BytesIO(edited)) as result,
    ):
        added = set(result.namelist()) - set(source.namelist())
        changed = {name for name in set(source.namelist()) & set(result.namelist()) if source.read(name) != result.read(name)}
        assert added == {
            "ppt/media/image1.png",
            "ppt/slides/_rels/slide2.xml.rels",
        }
        assert changed == {
            "[Content_Types].xml",
            "ppt/slides/slide2.xml",
        }
        assert result.read("ppt/media/image1.png") == image
        assert b'Extension="png" ContentType="image/png"' in result.read("[Content_Types].xml")
        assert b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"' in result.read("ppt/slides/_rels/slide2.xml.rels")


@pytest.mark.parametrize(
    ("mode", "tile", "expected_framing", "expected_fill"),
    [
        (
            "tile",
            PptxImageTileFormatting(
                offset_x_emu=127_000,
                offset_y_emu=-63_500,
                scale_x_percent=45,
                scale_y_percent=65,
                alignment="bottom_right",
                flip="horizontal",
            ),
            b'<a:tile tx="127000" ty="-63500" sx="45000" sy="65000" algn="br" flip="x"/>',
            {
                "fill_mode": "tile",
                "tile": {
                    "offset_x_emu": 127_000,
                    "offset_y_emu": -63_500,
                    "scale_x_percent": 45.0,
                    "scale_y_percent": 65.0,
                    "alignment": "bottom_right",
                    "flip": "horizontal",
                },
            },
        ),
        (
            "center",
            None,
            b'<a:tile sx="100000" sy="100000" algn="ctr" flip="none"/>',
            {"fill_mode": "center"},
        ),
    ],
)
def test_edit_pptx_embeds_typed_tile_and_center_shape_fills(
    mode: str,
    tile: PptxImageTileFormatting | None,
    expected_framing: bytes,
    expected_fill: dict[str, object],
) -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    image_path = f"/mnt/user-data/uploads/{mode}.png"
    image = _png(color=(0, 150, 136))
    operation = PptxShapeFormatOperation(
        shapes=PptxShapeSelector(
            targets=[
                PptxShapeTarget(
                    path="/slide[1]/shape[@id=7]",
                    expected_name="Styled copy",
                )
            ]
        ),
        formatting=PptxShapeFormatting(
            fill=PptxShapeFillFormatting(
                type="image",
                image_path=image_path,
                rotate_with_shape=mode == "center",
                mode=mode,
                tile=tile,
            )
        ),
    )

    edited, reports = edit_pptx(
        document,
        [operation],
        image_assets={image_path: image},
    )

    assert reports[0]["match_count"] == 1
    actual_fill = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["style"]["fill"]
    assert actual_fill == {
        "type": "image",
        "rotate_with_shape": mode == "center",
        **expected_fill,
        "relationship_ids": ["rId1"],
    }
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        slide_xml = archive.read("ppt/slides/slide2.xml")
    assert expected_framing in slide_xml
    assert slide_xml.index(b"<a:blip ") < slide_xml.index(expected_framing)

    no_op, _ = edit_pptx(
        edited,
        [operation],
        image_assets={image_path: image},
    )
    assert no_op == edited


def test_edit_pptx_image_fill_deduplicates_asset_and_relationship() -> None:
    second_shape = _formatted_shape().replace(
        'id="7" name="Styled copy"',
        'id="8" name="Second styled copy"',
        1,
    )
    document = _pptx(
        slide2=_slide(_formatted_shape() + second_shape),
    )
    image_path = "/mnt/user-data/workspace/shared.png"
    image = _png(color=(0, 150, 136))

    edited, _ = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        ),
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=8]",
                            expected_name="Second styled copy",
                        ),
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_image_fill_formatting(path=image_path),
                ),
            )
        ],
        image_assets={image_path: image},
    )

    inspected = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )
    fills = [item["style"]["fill"] for item in inspected["slides"][0]["objects"]]
    assert len(fills) == 2
    assert {tuple(fill["relationship_ids"]) for fill in fills} == {("rId1",)}
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        assert [name for name in archive.namelist() if name.startswith("ppt/media/")] == ["ppt/media/image1.png"]
        relationships = archive.read("ppt/slides/_rels/slide2.xml.rels")
        assert relationships.count(b"relationships/image") == 1


def test_edit_pptx_image_fill_avoids_rid_and_content_type_collisions() -> None:
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="application/octet-stream"/>\n</Types>',
    )
    document = _pptx(
        slide2=_slide(_formatted_shape()),
        slide2_relationships=relationships,
        content_types=content_types,
    )
    image_path = "/mnt/user-data/uploads/collision.png"

    edited, _ = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_image_fill_formatting(path=image_path),
                ),
            )
        ],
        image_assets={image_path: _png()},
    )

    fill = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["style"]["fill"]
    assert fill["relationship_ids"] == ["rId2"]
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        content_types_payload = archive.read("[Content_Types].xml")
        assert b'Extension="png" ContentType="application/octet-stream"' in content_types_payload
        assert b'PartName="/ppt/media/image1.png" ContentType="image/png"' in content_types_payload


def test_edit_pptx_image_fill_noop_returns_exact_source() -> None:
    image_path = "/mnt/user-data/uploads/existing.png"
    image = _png()
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    document = _pptx(
        slide2=_slide(_image_fill_shape()),
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": image},
    )

    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_image_fill_formatting(path=image_path),
                ),
            )
        ],
        image_assets={image_path: image},
    )

    assert reports[0]["match_count"] == 1
    assert edited == document


def test_edit_pptx_image_fill_rejects_implicit_tile_defaults() -> None:
    image_path = "/mnt/user-data/uploads/existing.png"
    image = _png()
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    document = _pptx(
        slide2=_slide(
            _image_fill_shape(
                crop=None,
                framing='<a:tile sx="45000" sy="65000" algn="br"/>',
            )
        ),
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": image},
    )
    operation = PptxShapeFormatOperation(
        shapes=PptxShapeSelector(
            targets=[
                PptxShapeTarget(
                    path="/slide[1]/shape[@id=7]",
                    expected_name="Styled copy",
                )
            ]
        ),
        formatting=PptxShapeFormatting(
            fill=PptxShapeFillFormatting(
                type="image",
                image_path=image_path,
                rotate_with_shape=False,
                mode="tile",
                tile=PptxImageTileFormatting(
                    offset_x_emu=0,
                    offset_y_emu=0,
                    scale_x_percent=45,
                    scale_y_percent=65,
                    alignment="bottom_right",
                    flip="none",
                ),
            )
        ),
    )

    inspected_fill = inspect_pptx(
        document,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["style"]["fill"]
    assert inspected_fill["fill_mode"] == "tile"
    assert "flip" not in inspected_fill["tile"]
    with pytest.raises(OfficeOperationError, match="explicit typed tile attributes"):
        edit_pptx(
            document,
            [operation],
            image_assets={image_path: image},
        )


def test_validate_pptx_image_asset_accepts_bounded_baseline_jpeg_modes() -> None:
    rgb = pptx_module._validate_jpeg_asset(
        _jpeg(),
        label="RGB JPEG",
    )
    grayscale = pptx_module._validate_jpeg_asset(
        _jpeg(mode="L"),
        label="grayscale JPEG",
    )

    assert (rgb.content_type, rgb.extension, rgb.width, rgb.height) == (
        "image/jpeg",
        ".jpg",
        4,
        3,
    )
    assert (grayscale.content_type, grayscale.width, grayscale.height) == (
        "image/jpeg",
        4,
        3,
    )


@pytest.mark.parametrize(
    ("path", "payload", "message"),
    [
        ("/mnt/user-data/uploads/wrong.jpg", _png(), "not a JPEG image"),
        ("/mnt/user-data/uploads/wrong.png", _jpeg(), "not a PNG image"),
        (
            "/mnt/user-data/uploads/progressive.jpg",
            _jpeg(progressive=True),
            "progressive JPEG encoding",
        ),
        (
            "/mnt/user-data/uploads/cmyk.jpg",
            _jpeg(mode="CMYK"),
            "CMYK or multi-component JPEG encoding",
        ),
        (
            "/mnt/user-data/uploads/oriented.jpg",
            _jpeg(exif_orientation=6),
            "EXIF orientation metadata",
        ),
        (
            "/mnt/user-data/uploads/truncated.jpg",
            _jpeg()[:-2],
            "incomplete JPEG image data",
        ),
    ],
)
def test_validate_pptx_image_asset_rejects_unsupported_or_mismatched_jpeg(
    path: str,
    payload: bytes,
    message: str,
) -> None:
    with pytest.raises(OfficeOperationError, match=message):
        pptx_module._validate_image_asset_for_path(
            payload,
            path=path,
            label="PPTX image asset",
        )


def test_edit_pptx_embeds_typed_baseline_jpeg_with_global_media_allocation() -> None:
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    document = _pptx(
        slide2=_slide(_formatted_shape()),
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": _png()},
    )
    image_path = "/mnt/user-data/uploads/replacement.jpeg"
    image = _jpeg()

    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_image_fill_formatting(path=image_path),
                ),
            )
        ],
        image_assets={image_path: image},
    )

    assert reports[0]["match_count"] == 1
    inspected = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )
    assert inspected["slides"][0]["objects"][0]["style"]["fill"]["type"] == "image"
    assert inspected["image_asset_inventory"]["orphan_part_count"] == 1
    assert inspected["image_asset_inventory"]["referenced_part_count"] == 1
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        assert archive.read("ppt/media/image2.jpg") == image
        assert b'Extension="jpg" ContentType="image/jpeg"' in archive.read("[Content_Types].xml")
        assert b'Target="../media/image2.jpg"' in archive.read("ppt/slides/_rels/slide2.xml.rels")


def test_edit_pptx_baseline_jpeg_image_fill_noop_returns_exact_source() -> None:
    image_path = "/mnt/user-data/uploads/existing.jpg"
    image = _jpeg()
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.jpeg"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="jpeg" ContentType="image/jpeg"/>\n</Types>',
    )
    document = _pptx(
        slide2=_slide(_image_fill_shape()),
        slide2_relationships=relationships,
        content_types=content_types,
        extra_parts={"ppt/media/image1.jpeg": image},
    )

    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_image_fill_formatting(path=image_path),
                ),
            )
        ],
        image_assets={image_path: image},
    )

    assert reports[0]["match_count"] == 1
    assert edited == document


def test_edit_pptx_image_fill_preflights_assets_and_existing_relationship() -> None:
    image_path = "/mnt/user-data/uploads/replacement.png"
    operation = PptxShapeFormatOperation(
        shapes=PptxShapeSelector(
            targets=[
                PptxShapeTarget(
                    path="/slide[1]/shape[@id=7]",
                    expected_name="Styled copy",
                )
            ]
        ),
        formatting=PptxShapeFormatting(
            fill=_image_fill_formatting(path=image_path),
        ),
    )
    document = _pptx(slide2=_slide(_formatted_shape()))
    with pytest.raises(OfficeOperationError, match="missing a required image asset"):
        edit_pptx(document, [operation])
    with pytest.raises(OfficeOperationError, match="not a PNG image"):
        edit_pptx(
            document,
            [operation],
            image_assets={image_path: b"not-a-png"},
        )
    corrupted_png = bytearray(_png())
    corrupted_png[-5] ^= 0x01
    with pytest.raises(OfficeOperationError, match="chunk checksum"):
        edit_pptx(
            document,
            [operation],
            image_assets={image_path: bytes(corrupted_png)},
        )

    wrong_relationship = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../media/image1.png"/>
    </Relationships>"""
    content_types = _CONTENT_TYPES.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
    )
    invalid_existing = _pptx(
        slide2=_slide(_image_fill_shape()),
        slide2_relationships=wrong_relationship,
        content_types=content_types,
        extra_parts={"ppt/media/image1.png": _png()},
    )
    with pytest.raises(OfficeOperationError, match="invalid embedded image relationship"):
        edit_pptx(
            invalid_existing,
            [operation],
            image_assets={image_path: _png(color=(192, 43, 58))},
        )


def test_edit_pptx_shape_formatting_supports_no_fill_and_line_creation() -> None:
    document = _pptx(slide2=_slide(_shape("Target")))
    edited, _ = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=2]",
                            expected_name="Text",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=PptxShapeFillFormatting(type="none"),
                    line=PptxShapeLineFormatting(
                        fill=PptxShapeFillFormatting(type="solid", color="445566"),
                        width_points=2.5,
                    ),
                    text_box=PptxTextBoxFormatting(margin_left=-0.05),
                ),
            )
        ],
    )

    style = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["style"]
    assert style["fill"] == {"type": "none"}
    assert style["line"] == {
        "width_emu": 31_750,
        "fill": {
            "type": "solid",
            "color": {"type": "rgb", "value": "#445566"},
        },
    }
    assert style["text_box"] == {"margins": {"left_emu": -635}}
    with zipfile.ZipFile(io.BytesIO(edited)) as result:
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert slide_xml.index(b"<a:noFill") < slide_xml.index(b"<a:ln")


def test_edit_pptx_shape_formatting_rejects_duplicate_authored_ids() -> None:
    document = _pptx(slide2=_slide(_shape("One") + _shape("Two")))

    with pytest.raises(OfficeOperationError, match="stale or missing paths"):
        edit_pptx(
            document,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=2]",
                                expected_name="Text",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="445566")),
                )
            ],
        )


def test_edit_pptx_shape_formatting_guards_null_and_truncated_names() -> None:
    unnamed = _shape("Unnamed").replace(' name="Text"', "")
    edited, _ = edit_pptx(
        _pptx(slide2=_slide(unnamed)),
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=2]",
                            expected_name=None,
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="445566")),
            )
        ],
    )
    assert (
        inspect_pptx(
            edited,
            max_slides=1,
            include_formatting=True,
        )["slides"][0]["objects"][0]["style"]["fill"]["color"]["value"]
        == "#445566"
    )

    long_name = "N" * 300
    document = _pptx(slide2=_slide(_shape("Long name").replace('name="Text"', f'name="{long_name}"')))
    with pytest.raises(OfficeOperationError, match="expected_name no longer matches"):
        edit_pptx(
            document,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=2]",
                                expected_name=long_name[:256],
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="445566")),
                )
            ],
        )


def test_edit_pptx_shape_formatting_uses_stable_group_paths() -> None:
    group = f"""<p:grpSp>
      <p:nvGrpSpPr><p:cNvPr id="8" name="Stable group"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr/>{_shape("Grouped target")}
    </p:grpSp>"""
    document = _pptx(slide2=_slide(group))
    edited, _ = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/group[@id=8]/shape[@id=2]",
                            expected_name="Text",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="778899")),
            )
        ],
    )

    objects = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"]
    inner = next(item for item in objects if item["path"].endswith("/shape[@id=2]"))
    assert inner["style"]["fill"]["color"]["value"] == "#778899"


def test_edit_pptx_shape_formatting_preflights_guards_and_unsupported_fills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gradient_shape = _formatted_shape().replace(
        '<a:solidFill><a:srgbClr val="336699"><a:alpha val="75000"/></a:srgbClr></a:solidFill>',
        '<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="336699"/></a:gs></a:gsLst></a:gradFill>',
    )
    document = _pptx(slide2=_slide(gradient_shape))
    called = False
    apply_run = pptx_module._apply_pptx_run_formatting

    def record_run(run, formatting):
        nonlocal called
        called = True
        return apply_run(run, formatting)

    monkeypatch.setattr(pptx_module, "_apply_pptx_run_formatting", record_run)
    with pytest.raises(OfficeOperationError, match="expected_name no longer matches"):
        edit_pptx(
            document,
            [
                PptxRunFormatOperation(
                    runs=PptxRunSelector(
                        targets=[
                            PptxRunTarget(
                                path="/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
                                expected_text="Alpha",
                            )
                        ]
                    ),
                    formatting=PptxRunFormatting(bold=False),
                ),
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Outdated name",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="112233")),
                ),
            ],
        )
    assert called is False

    with pytest.raises(OfficeOperationError, match="cannot replace a gradient"):
        edit_pptx(
            document,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="112233")),
                )
            ],
        )
    with pytest.raises(OfficeOperationError, match="cannot create an implicit line"):
        edit_pptx(
            _pptx(slide2=_slide(_shape("No line"))),
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=2]",
                                expected_name="Text",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(line=PptxShapeLineFormatting(width_points=2)),
                )
            ],
        )


def test_edit_pptx_shape_formatting_preflights_every_color_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _formatted_shape()
    second = (
        _formatted_shape()
        .replace('id="7" name="Styled copy"', 'id="8" name="Invalid color"')
        .replace(
            '<a:solidFill><a:srgbClr val="336699"><a:alpha val="75000"/></a:srgbClr></a:solidFill>',
            '<a:solidFill><a:srgbClr val="336699"/><a:schemeClr val="accent1"/></a:solidFill>',
            1,
        )
    )
    document = _pptx(slide2=_slide(first + second))
    called = False
    apply_shape = pptx_module._apply_pptx_shape_formatting

    def record_shape(shape, formatting):
        nonlocal called
        called = True
        return apply_shape(shape, formatting)

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_shape_formatting",
        record_shape,
    )
    with pytest.raises(OfficeOperationError, match="multiple colors"):
        edit_pptx(
            document,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            ),
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=8]",
                                expected_name="Invalid color",
                            ),
                        ]
                    ),
                    formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="112233")),
                )
            ],
        )
    assert called is False


def test_inspect_pptx_normalizes_typed_connector_line_formatting() -> None:
    document = _pptx(slide2=_slide(_formatted_connector()))

    connector = inspect_pptx(
        document,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]

    assert connector["kind"] == "connector"
    assert connector["path"] == "/slide[1]/connector[@id=9]"
    assert connector["identity_source"] == "cNvPr.id"
    assert connector["style"]["line"] == {
        "width_emu": 38_100,
        "cap": "round",
        "compound": "double",
        "alignment": "center",
        "fill": {
            "type": "solid",
            "color": {"type": "rgb", "value": "#4472C4"},
        },
        "dash": "dash",
        "join": "miter",
        "miter_limit_percent": 800.0,
        "head_end": {
            "type": "diamond",
            "width": "small",
            "length": "medium",
        },
        "tail_end": {
            "type": "triangle",
            "width": "large",
            "length": "large",
        },
    }


def test_edit_pptx_formats_exact_shape_and_connector_lines() -> None:
    document = _pptx(slide2=_slide(_formatted_shape() + _formatted_connector()))
    before = {
        item["name"]: item
        for item in inspect_pptx(
            document,
            max_slides=1,
            include_formatting=True,
        )["slides"][0]["objects"]
    }

    edited, reports = edit_pptx(
        document,
        [
            PptxLineFormatOperation(
                lines=PptxLineSelector(
                    targets=[
                        PptxLineTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        ),
                        PptxLineTarget(
                            path="/slide[1]/connector[@id=9]",
                            expected_name="Authored connector",
                        ),
                    ]
                ),
                formatting=PptxLineFormatting(
                    compound="thick_thin",
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
            "match_count": 2,
            "matched_paths": [
                "/slide[1]/shape[@id=7]",
                "/slide[1]/connector[@id=9]",
            ],
            "matched_paths_truncated": False,
        }
    ]
    after = {
        item["name"]: item
        for item in inspect_pptx(
            edited,
            max_slides=1,
            include_formatting=True,
        )["slides"][0]["objects"]
    }
    for name in ("Styled copy", "Authored connector"):
        assert after[name]["geometry"] == before[name]["geometry"]
        assert after[name]["style"]["geometry"] == before[name]["style"]["geometry"]
        line = after[name]["style"]["line"]
        assert line["compound"] == "thick_thin"
        assert line["alignment"] == "inset"
        assert line["head_end"] == {
            "type": "stealth",
            "width": "large",
            "length": "small",
        }
        assert line["tail_end"] == {
            "type": "oval",
            "width": "medium",
            "length": "large",
        }
    assert after["Styled copy"]["text_body"] == before["Styled copy"]["text_body"]
    assert after["Styled copy"]["style"]["fill"] == before["Styled copy"]["style"]["fill"]
    assert after["Authored connector"]["style"]["line"]["fill"] == before["Authored connector"]["style"]["line"]["fill"]
    with (
        zipfile.ZipFile(io.BytesIO(document)) as source,
        zipfile.ZipFile(io.BytesIO(edited)) as result,
    ):
        changed = [name for name in source.namelist() if source.read(name) != result.read(name)]
        slide_xml = result.read("ppt/slides/slide2.xml")
    assert changed == ["ppt/slides/slide2.xml"]
    root = pptx_module.etree.fromstring(slide_xml)
    lines = [element for element in root.iter() if pptx_module._local_name(element) == "ln"]
    assert len(lines) == 2
    for line in lines:
        child_names = [pptx_module._local_name(child) for child in line]
        join_index = next(child_names.index(name) for name in ("round", "bevel", "miter") if name in child_names)
        assert join_index < child_names.index("headEnd") < child_names.index("tailEnd")


def test_edit_pptx_line_formatting_requires_explicit_creation_and_existing_line_end() -> None:
    document = _pptx(slide2=_slide(_shape("No direct line")))
    target = PptxLineSelector(
        targets=[
            PptxLineTarget(
                path="/slide[1]/shape[@id=2]",
                expected_name="Text",
            )
        ]
    )

    with pytest.raises(OfficeOperationError, match="cannot create an implicit line"):
        edit_pptx(
            document,
            [
                PptxLineFormatOperation(
                    lines=target,
                    formatting=PptxLineFormatting(compound="double"),
                )
            ],
        )

    with pytest.raises(OfficeOperationError, match="requires an existing line end"):
        edit_pptx(
            document,
            [
                PptxLineFormatOperation(
                    lines=target,
                    formatting=PptxLineFormatting(
                        fill=PptxShapeFillFormatting(type="solid", color="112233"),
                        head_end=PptxLineEndFormatting(width="large"),
                    ),
                )
            ],
        )

    edited, _ = edit_pptx(
        document,
        [
            PptxLineFormatOperation(
                lines=target,
                formatting=PptxLineFormatting(
                    fill=PptxShapeFillFormatting(type="solid", color="112233"),
                    width_points=2,
                    compound="double",
                    alignment="center",
                    head_end=PptxLineEndFormatting(type="arrow", width="large"),
                ),
            )
        ],
    )
    line = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )["slides"][0]["objects"][0]["style"]["line"]
    assert line == {
        "width_emu": 25_400,
        "compound": "double",
        "alignment": "center",
        "fill": {
            "type": "solid",
            "color": {"type": "rgb", "value": "#112233"},
        },
        "head_end": {"type": "arrow", "width": "large"},
    }


def test_edit_pptx_line_formatting_preflights_stale_and_ambiguous_targets() -> None:
    document = _pptx(slide2=_slide(_formatted_connector()))
    with pytest.raises(OfficeOperationError, match="expected_name no longer matches"):
        edit_pptx(
            document,
            [
                PptxLineFormatOperation(
                    lines=PptxLineSelector(
                        targets=[
                            PptxLineTarget(
                                path="/slide[1]/connector[@id=9]",
                                expected_name="Old name",
                            )
                        ]
                    ),
                    formatting=PptxLineFormatting(compound="single"),
                )
            ],
        )

    duplicate = _formatted_connector() + _formatted_connector(name="Duplicate connector")
    with pytest.raises(OfficeOperationError, match="stale or missing paths"):
        edit_pptx(
            _pptx(slide2=_slide(duplicate)),
            [
                PptxLineFormatOperation(
                    lines=PptxLineSelector(
                        targets=[
                            PptxLineTarget(
                                path="/slide[1]/connector[@id=9]",
                                expected_name="Authored connector",
                            )
                        ]
                    ),
                    formatting=PptxLineFormatting(compound="single"),
                )
            ],
        )

    duplicate_end = _formatted_connector().replace(
        '<a:headEnd type="diamond" w="sm" len="med"/>',
        '<a:headEnd type="diamond"/><a:headEnd type="arrow"/>',
    )
    with pytest.raises(OfficeOperationError, match="multiple headEnd"):
        edit_pptx(
            _pptx(slide2=_slide(duplicate_end)),
            [
                PptxLineFormatOperation(
                    lines=PptxLineSelector(
                        targets=[
                            PptxLineTarget(
                                path="/slide[1]/connector[@id=9]",
                                expected_name="Authored connector",
                            )
                        ]
                    ),
                    formatting=PptxLineFormatting(alignment="inset"),
                )
            ],
        )


def test_edit_pptx_line_formatting_preflights_every_target_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = _formatted_connector()
    malformed = _formatted_connector(object_id=10, name="Malformed connector").replace(
        '<a:headEnd type="diamond" w="sm" len="med"/>',
        '<a:headEnd type="diamond"/><a:headEnd type="arrow"/>',
    )
    called = False
    apply_line = pptx_module._apply_pptx_line_formatting

    def record_line(owner, formatting):
        nonlocal called
        called = True
        return apply_line(owner, formatting)

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_line_formatting",
        record_line,
    )
    with pytest.raises(OfficeOperationError, match="multiple headEnd"):
        edit_pptx(
            _pptx(slide2=_slide(valid + malformed)),
            [
                PptxLineFormatOperation(
                    lines=PptxLineSelector(
                        targets=[
                            PptxLineTarget(
                                path="/slide[1]/connector[@id=9]",
                                expected_name="Authored connector",
                            ),
                            PptxLineTarget(
                                path="/slide[1]/connector[@id=10]",
                                expected_name="Malformed connector",
                            ),
                        ]
                    ),
                    formatting=PptxLineFormatting(alignment="inset"),
                )
            ],
        )
    assert called is False


def test_edit_pptx_line_formatting_noop_returns_exact_source() -> None:
    document = _pptx(slide2=_slide(_formatted_connector()))
    edited, reports = edit_pptx(
        document,
        [
            PptxLineFormatOperation(
                lines=PptxLineSelector(
                    targets=[
                        PptxLineTarget(
                            path="/slide[1]/connector[@id=9]",
                            expected_name="Authored connector",
                        )
                    ]
                ),
                formatting=PptxLineFormatting(
                    compound="double",
                    alignment="center",
                    head_end=PptxLineEndFormatting(
                        type="diamond",
                        width="small",
                        length="medium",
                    ),
                    tail_end=PptxLineEndFormatting(
                        type="triangle",
                        width="large",
                        length="large",
                    ),
                ),
            )
        ],
    )

    assert edited == document
    assert reports[0]["match_count"] == 1


def test_edit_pptx_line_formatting_gate_rejects_geometry_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_formatted_connector()))
    apply_line = pptx_module._apply_pptx_line_formatting

    def mutate_geometry(owner, formatting):
        changed = apply_line(owner, formatting)
        properties = pptx_module._line_owner_properties(owner)
        pptx_module._first_drawing_child(properties, "prstGeom").set("prst", "bentConnector3")
        return changed

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_line_formatting",
        mutate_geometry,
    )
    with pytest.raises(OfficeOperationError, match="unsupported structure"):
        edit_pptx(
            document,
            [
                PptxLineFormatOperation(
                    lines=PptxLineSelector(
                        targets=[
                            PptxLineTarget(
                                path="/slide[1]/connector[@id=9]",
                                expected_name="Authored connector",
                            )
                        ]
                    ),
                    formatting=PptxLineFormatting(compound="single"),
                )
            ],
        )


def test_edit_pptx_line_style_rejects_multiple_authored_choices() -> None:
    ambiguous_dash = _formatted_shape().replace(
        '<a:prstDash val="dash"/>',
        '<a:prstDash val="dash"/><a:custDash><a:ds d="200000" sp="100000"/></a:custDash>',
        1,
    )
    with pytest.raises(OfficeOperationError, match="multiple dash choices"):
        edit_pptx(
            _pptx(slide2=_slide(ambiguous_dash)),
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(line=PptxShapeLineFormatting(cap="square")),
                )
            ],
        )

    ambiguous_join = _formatted_shape().replace(
        "<a:round/>",
        '<a:round/><a:miter lim="800000"/>',
        1,
    )
    with pytest.raises(OfficeOperationError, match="multiple join choices"):
        edit_pptx(
            _pptx(slide2=_slide(ambiguous_join)),
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(line=PptxShapeLineFormatting(dash="dot")),
                )
            ],
        )


def test_edit_pptx_shape_formatting_rejects_post_mutation_fill_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    apply_shape = pptx_module._apply_pptx_shape_formatting

    def reorder_no_fill(shape, formatting):
        changed = apply_shape(shape, formatting)
        properties = pptx_module._shape_properties(shape)
        no_fill = pptx_module._first_drawing_child(properties, "noFill")
        line = pptx_module._first_drawing_child(properties, "ln")
        properties.remove(no_fill)
        properties.insert(properties.index(line) + 1, no_fill)
        return changed

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_shape_formatting",
        reorder_no_fill,
    )
    with pytest.raises(OfficeOperationError, match="unsupported DrawingML child order"):
        edit_pptx(
            document,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="none")),
                )
            ],
        )


def test_edit_pptx_shape_formatting_noop_returns_exact_source() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="336699")),
            )
        ],
    )

    assert edited == document
    assert reports[0]["match_count"] == 1


def test_edit_pptx_gradient_formatting_noop_returns_exact_source() -> None:
    document = _pptx(slide2=_slide(_formatted_gradient_shape()))
    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_matching_gradient_formatting(),
                ),
            )
        ],
    )

    assert edited == document
    assert reports[0]["match_count"] == 1


def test_edit_pptx_pattern_formatting_noop_returns_exact_source() -> None:
    document = _pptx(slide2=_slide(_formatted_pattern_shape()))
    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_matching_pattern_formatting(),
                ),
            )
        ],
    )

    assert edited == document
    assert reports[0]["match_count"] == 1


def test_edit_pptx_radial_gradient_and_geometry_noop_returns_exact_source() -> None:
    document = _pptx(slide2=_slide(_formatted_path_gradient_shape()))
    edited, reports = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    fill=_matching_path_gradient_formatting(),
                    geometry=PptxPresetGeometryFormatting(preset="roundRect"),
                ),
            )
        ],
    )

    assert edited == document
    assert reports[0]["match_count"] == 1


def test_edit_pptx_gradient_preflights_every_target_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = _formatted_gradient_shape()
    unsupported = _formatted_gradient_shape(gradient_attributes=' rotWithShape="1" flip="x"').replace('id="7" name="Styled copy"', 'id="8" name="Unsupported gradient"')
    document = _pptx(slide2=_slide(valid + unsupported))
    called = False
    apply_shape = pptx_module._apply_pptx_shape_formatting

    def record_shape(shape, formatting):
        nonlocal called
        called = True
        return apply_shape(shape, formatting)

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_shape_formatting",
        record_shape,
    )
    with pytest.raises(OfficeOperationError, match="unsupported gradient attributes"):
        edit_pptx(
            document,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            ),
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=8]",
                                expected_name="Unsupported gradient",
                            ),
                        ]
                    ),
                    formatting=PptxShapeFormatting(
                        fill=_matching_gradient_formatting(),
                    ),
                )
            ],
        )
    assert called is False


@pytest.mark.parametrize(
    ("source_fragment", "replacement", "message"),
    [
        (
            '<a:srgbClr val="203864"/>',
            '<a:schemeClr val="accent1"/>',
            "requires exactly one direct RGB color",
        ),
        (
            '<a:srgbClr val="203864"/>',
            '<!--preserved metadata--><a:srgbClr val="203864"/>',
            "unsupported content",
        ),
        (
            '<a:lin ang="2250000" scaled="1"/>',
            '<a:path path="rect"><a:fillToRect l="50000" t="50000" r="50000" b="50000"/></a:path>',
            "only radial circle path geometry",
        ),
        (
            '<a:gs pos="100000"><a:srgbClr val="70AD47"/></a:gs>',
            '<a:gs pos="37500"><a:srgbClr val="70AD47"/></a:gs>',
            "strictly increasing",
        ),
    ],
)
def test_edit_pptx_gradient_rejects_unsupported_existing_structure(
    source_fragment: str,
    replacement: str,
    message: str,
) -> None:
    shape = _formatted_gradient_shape().replace(
        source_fragment,
        replacement,
        1,
    )
    with pytest.raises(OfficeOperationError, match=message):
        edit_pptx(
            _pptx(slide2=_slide(shape)),
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(
                        fill=_matching_gradient_formatting(),
                    ),
                )
            ],
        )


@pytest.mark.parametrize(
    ("source_fragment", "replacement", "message"),
    [
        (
            '<a:pattFill prst="diagCross">',
            '<a:pattFill prst="notARealPattern">',
            "unsupported pattern preset",
        ),
        (
            '<a:fgClr><a:srgbClr val="4472C4"/></a:fgClr>',
            '<a:fgClr><a:schemeClr val="accent1"/></a:fgClr>',
            "requires exactly one direct RGB color",
        ),
        (
            '<a:fgClr><a:srgbClr val="4472C4"/></a:fgClr>',
            '<a:fgClr><a:srgbClr val="4472C4"><a:alpha val="80000"/></a:srgbClr></a:fgClr>',
            "unsupported direct RGB color",
        ),
        (
            '<a:fgClr><a:srgbClr val="4472C4"/></a:fgClr>\n          <a:bgClr><a:srgbClr val="D9EAF7"/></a:bgClr>',
            '<a:bgClr><a:srgbClr val="D9EAF7"/></a:bgClr>\n          <a:fgClr><a:srgbClr val="4472C4"/></a:fgClr>',
            "requires ordered foreground and background colors",
        ),
        (
            '<a:pattFill prst="diagCross">',
            '<a:pattFill prst="diagCross"><!--metadata-->',
            "unsupported pattern content",
        ),
    ],
)
def test_edit_pptx_pattern_rejects_unsupported_existing_structure(
    source_fragment: str,
    replacement: str,
    message: str,
) -> None:
    shape = _formatted_pattern_shape().replace(
        source_fragment,
        replacement,
        1,
    )
    with pytest.raises(OfficeOperationError, match=message):
        edit_pptx(
            _pptx(slide2=_slide(shape)),
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(
                        fill=_matching_pattern_formatting(),
                    ),
                )
            ],
        )


@pytest.mark.parametrize(
    ("source_fragment", "replacement", "message"),
    [
        (
            'l="35000" t="25000" r="65000" b="75000"',
            'l="34000" t="25000" r="65000" b="75000"',
            "must sum to 100 percent",
        ),
        (
            '<a:fillToRect l="35000" t="25000" r="65000" b="75000"/>',
            '<a:fillToRect l="35000" t="25000" r="65000" b="75000" flip="x"/>',
            "unsupported radial fill-rectangle metadata",
        ),
        (
            '<a:path path="circle">',
            '<a:path path="circle"><!--metadata-->',
            "unsupported radial path content",
        ),
    ],
)
def test_edit_pptx_radial_gradient_rejects_unsupported_existing_structure(
    source_fragment: str,
    replacement: str,
    message: str,
) -> None:
    shape = _formatted_path_gradient_shape().replace(
        source_fragment,
        replacement,
        1,
    )
    with pytest.raises(OfficeOperationError, match=message):
        edit_pptx(
            _pptx(slide2=_slide(shape)),
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(
                        fill=_matching_path_gradient_formatting(),
                    ),
                )
            ],
        )


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        (
            '<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="l" t="t" r="r" b="b"/><a:pathLst/></a:custGeom>',
            "cannot replace custom geometry",
        ),
        (
            '<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 25000"/></a:avLst></a:prstGeom>',
            "authored adjustments is not writable",
        ),
    ],
)
def test_edit_pptx_preset_geometry_rejects_custom_or_adjusted_source(
    geometry: str,
    message: str,
) -> None:
    shape = _formatted_shape().replace(
        '<a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>',
        geometry,
        1,
    )
    with pytest.raises(OfficeOperationError, match=message):
        edit_pptx(
            _pptx(slide2=_slide(shape)),
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(geometry=PptxPresetGeometryFormatting(preset="hexagon")),
                )
            ],
        )


def test_edit_pptx_line_style_noop_returns_exact_source() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    edited, _ = edit_pptx(
        document,
        [
            PptxShapeFormatOperation(
                shapes=PptxShapeSelector(
                    targets=[
                        PptxShapeTarget(
                            path="/slide[1]/shape[@id=7]",
                            expected_name="Styled copy",
                        )
                    ]
                ),
                formatting=PptxShapeFormatting(
                    line=PptxShapeLineFormatting(
                        cap="round",
                        dash="dash",
                        join="round",
                    )
                ),
            )
        ],
    )

    assert edited == document


def test_edit_pptx_shape_formatting_gate_rejects_metadata_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    apply_shape = pptx_module._apply_pptx_shape_formatting

    def drop_alpha(shape, formatting):
        changed = apply_shape(shape, formatting)
        for element in shape.iter():
            if isinstance(element.tag, str) and pptx_module._local_name(element) == "alpha":
                element.getparent().remove(element)
                break
        return changed

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_shape_formatting",
        drop_alpha,
    )
    with pytest.raises(OfficeOperationError, match="unsupported structure"):
        edit_pptx(
            document,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="112233")),
                )
            ],
        )


def test_edit_pptx_line_style_gate_rejects_unrequested_compound_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))
    apply_shape = pptx_module._apply_pptx_shape_formatting

    def mutate_compound(shape, formatting):
        changed = apply_shape(shape, formatting)
        line = pptx_module._shape_line(
            pptx_module._shape_properties(shape),
            create=False,
        )
        line.set("cmpd", "dbl")
        return changed

    monkeypatch.setattr(
        pptx_module,
        "_apply_pptx_shape_formatting",
        mutate_compound,
    )
    with pytest.raises(OfficeOperationError, match="unsupported structure"):
        edit_pptx(
            document,
            [
                PptxShapeFormatOperation(
                    shapes=PptxShapeSelector(
                        targets=[
                            PptxShapeTarget(
                                path="/slide[1]/shape[@id=7]",
                                expected_name="Styled copy",
                            )
                        ]
                    ),
                    formatting=PptxShapeFormatting(line=PptxShapeLineFormatting(cap="square")),
                )
            ],
        )


def test_pptx_shape_formatting_creates_strict_drawingml_children() -> None:
    shape = pptx_module.etree.fromstring(
        b"""<p:sp xmlns:p="http://purl.oclc.org/ooxml/presentationml/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:as="http://purl.oclc.org/ooxml/drawingml/main"><p:spPr/><p:txBody><as:bodyPr/><as:lstStyle/><as:p/></p:txBody></p:sp>"""
    )

    assert pptx_module._apply_pptx_shape_formatting(
        shape,
        PptxShapeFormatting(
            fill=PptxShapeFillFormatting(type="solid", color="112233"),
            line=PptxShapeLineFormatting(
                fill=PptxShapeFillFormatting(type="none"),
                width_points=1,
                cap="square",
                dash="large_dash",
                join="miter",
                miter_limit_percent=800,
            ),
        ),
    )
    children = list(pptx_module._shape_properties(shape))
    assert [pptx_module._qname(child).namespace for child in children] == [
        "http://purl.oclc.org/ooxml/drawingml/main",
        "http://purl.oclc.org/ooxml/drawingml/main",
    ]
    line = children[1]
    assert [pptx_module._local_name(child) for child in line] == [
        "noFill",
        "prstDash",
        "miter",
    ]
    assert {pptx_module._qname(child).namespace for child in line} == {"http://purl.oclc.org/ooxml/drawingml/main"}


@pytest.mark.parametrize(
    ("fill", "framing_name"),
    [
        (_image_fill_formatting(), "stretch"),
        (
            PptxShapeFillFormatting(
                type="image",
                image_path="/mnt/user-data/uploads/center.png",
                rotate_with_shape=False,
                mode="center",
            ),
            "tile",
        ),
        (
            PptxShapeFillFormatting(
                type="image",
                image_path="/mnt/user-data/uploads/tile.png",
                rotate_with_shape=False,
                mode="tile",
                tile=PptxImageTileFormatting(
                    offset_x_emu=0,
                    offset_y_emu=0,
                    scale_x_percent=50,
                    scale_y_percent=75,
                    alignment="top_left",
                    flip="none",
                ),
            ),
            "tile",
        ),
    ],
)
def test_pptx_image_fill_creates_strict_drawing_and_relationship_namespaces(
    fill: PptxShapeFillFormatting,
    framing_name: str,
) -> None:
    shape = pptx_module.etree.fromstring(
        b"""<p:sp xmlns:p="http://purl.oclc.org/ooxml/presentationml/main"
          xmlns:as="http://purl.oclc.org/ooxml/drawingml/main">
          <p:spPr/><p:txBody><as:bodyPr/><as:lstStyle/><as:p/></p:txBody>
        </p:sp>"""
    )

    assert pptx_module._apply_pptx_shape_formatting(
        shape,
        PptxShapeFormatting(fill=fill),
        image_relationship_id="rId9",
    )
    image_fill = pptx_module._first_drawing_child(
        pptx_module._shape_properties(shape),
        "blipFill",
    )
    assert pptx_module._qname(image_fill).namespace == "http://purl.oclc.org/ooxml/drawingml/main"
    blip = pptx_module._first_drawing_child(image_fill, "blip")
    assert blip.get("{http://purl.oclc.org/ooxml/officeDocument/relationships}embed") == "rId9"
    framing = pptx_module._first_drawing_child(image_fill, framing_name)
    assert pptx_module._qname(framing).namespace == "http://purl.oclc.org/ooxml/drawingml/main"


def test_pptx_gradient_formatting_creates_strict_drawingml_children() -> None:
    shape = pptx_module.etree.fromstring(
        b"""<p:sp xmlns:p="http://purl.oclc.org/ooxml/presentationml/main"
          xmlns:as="http://purl.oclc.org/ooxml/drawingml/main">
          <p:spPr><as:solidFill><as:srgbClr val="112233"/></as:solidFill></p:spPr>
        </p:sp>"""
    )

    assert pptx_module._apply_pptx_shape_formatting(
        shape,
        PptxShapeFormatting(fill=_matching_gradient_formatting()),
    )
    gradient = pptx_module._first_drawing_child(
        pptx_module._shape_properties(shape),
        "gradFill",
    )
    descendants = [gradient, *gradient.iterdescendants()]
    assert {pptx_module._qname(child).namespace for child in descendants} == {"http://purl.oclc.org/ooxml/drawingml/main"}
    assert [pptx_module._local_name(child) for child in gradient] == [
        "gsLst",
        "lin",
    ]


def test_pptx_pattern_formatting_creates_strict_drawingml_children() -> None:
    shape = pptx_module.etree.fromstring(
        b"""<p:sp xmlns:p="http://purl.oclc.org/ooxml/presentationml/main"
          xmlns:as="http://purl.oclc.org/ooxml/drawingml/main">
          <p:spPr><as:solidFill><as:srgbClr val="112233"/></as:solidFill></p:spPr>
        </p:sp>"""
    )

    assert pptx_module._apply_pptx_shape_formatting(
        shape,
        PptxShapeFormatting(fill=_matching_pattern_formatting()),
    )
    pattern = pptx_module._first_drawing_child(
        pptx_module._shape_properties(shape),
        "pattFill",
    )
    descendants = [pattern, *pattern.iterdescendants()]
    assert {pptx_module._qname(child).namespace for child in descendants} == {"http://purl.oclc.org/ooxml/drawingml/main"}
    assert [pptx_module._local_name(child) for child in pattern] == [
        "fgClr",
        "bgClr",
    ]


def test_pptx_radial_gradient_and_geometry_keep_strict_drawingml() -> None:
    shape = pptx_module.etree.fromstring(
        b"""<p:sp xmlns:p="http://purl.oclc.org/ooxml/presentationml/main"
          xmlns:as="http://purl.oclc.org/ooxml/drawingml/main">
          <p:spPr>
            <as:prstGeom prst="roundRect"><as:avLst/></as:prstGeom>
            <as:solidFill><as:srgbClr val="112233"/></as:solidFill>
          </p:spPr>
        </p:sp>"""
    )

    assert pptx_module._apply_pptx_shape_formatting(
        shape,
        PptxShapeFormatting(
            fill=_matching_path_gradient_formatting(),
            geometry=PptxPresetGeometryFormatting(preset="hexagon"),
        ),
    )
    properties = pptx_module._shape_properties(shape)
    geometry = pptx_module._first_drawing_child(properties, "prstGeom")
    gradient = pptx_module._first_drawing_child(properties, "gradFill")
    descendants = [geometry, gradient, *geometry.iterdescendants(), *gradient.iterdescendants()]
    assert {pptx_module._qname(child).namespace for child in descendants} == {"http://purl.oclc.org/ooxml/drawingml/main"}
    assert geometry.get("prst") == "hexagon"
    assert [pptx_module._local_name(child) for child in gradient] == [
        "gsLst",
        "path",
    ]


def test_pptx_line_formatting_creates_strict_drawingml_line_ends() -> None:
    connector = pptx_module.etree.fromstring(
        b"""<p:cxnSp xmlns:p="http://purl.oclc.org/ooxml/presentationml/main"
          xmlns:as="http://purl.oclc.org/ooxml/drawingml/main">
          <p:spPr>
            <as:xfrm/><as:prstGeom prst="line"><as:avLst/></as:prstGeom>
            <as:ln><as:solidFill><as:srgbClr val="4472C4"/></as:solidFill></as:ln>
          </p:spPr>
        </p:cxnSp>"""
    )

    assert pptx_module._apply_pptx_line_formatting(
        connector,
        PptxLineFormatting(
            compound="triple",
            alignment="inset",
            head_end=PptxLineEndFormatting(type="stealth", width="large"),
            tail_end=PptxLineEndFormatting(type="oval", length="small"),
        ),
    )
    line = pptx_module._shape_line(
        pptx_module._line_owner_properties(connector),
        create=False,
    )
    assert line.get("cmpd") == "tri"
    assert line.get("algn") == "in"
    assert [pptx_module._local_name(child) for child in line] == [
        "solidFill",
        "headEnd",
        "tailEnd",
    ]
    assert {pptx_module._qname(child).namespace for child in line} == {"http://purl.oclc.org/ooxml/drawingml/main"}


def test_pptx_shape_formatting_rejects_mixed_strict_structure() -> None:
    wrong_properties = pptx_module.etree.fromstring(
        b"""<p:sp xmlns:p="http://purl.oclc.org/ooxml/presentationml/main" xmlns:pt="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:as="http://purl.oclc.org/ooxml/drawingml/main"><pt:spPr/><p:txBody><as:bodyPr/><as:lstStyle/><as:p/></p:txBody></p:sp>"""
    )
    with pytest.raises(OfficeOperationError, match="exactly one shape-properties"):
        pptx_module._apply_pptx_shape_formatting(
            wrong_properties,
            PptxShapeFormatting(fill=PptxShapeFillFormatting(type="solid", color="112233")),
        )

    wrong_body_properties = pptx_module.etree.fromstring(
        b"""<p:sp xmlns:p="http://purl.oclc.org/ooxml/presentationml/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:as="http://purl.oclc.org/ooxml/drawingml/main"><p:spPr/><p:txBody><a:bodyPr/><as:lstStyle/><as:p/></p:txBody></p:sp>"""
    )
    with pytest.raises(OfficeOperationError, match="exactly one body-properties"):
        pptx_module._apply_pptx_shape_formatting(
            wrong_body_properties,
            PptxShapeFormatting(text_box=PptxTextBoxFormatting(vertical_anchor="middle")),
        )


def test_edit_pptx_rejects_active_content() -> None:
    unsafe = _shape("Unsafe").replace(
        '<p:cNvPr id="2" name="Text"/>',
        '<p:cNvPr id="2" name="Text"><a:hlinkClick r:id="" action="javascript:alert(1)"/></p:cNvPr>',
    )
    document = _pptx(slide2=_slide(unsafe))

    with pytest.raises(OfficeOperationError, match="unsafe actions"):
        edit_pptx(
            document,
            [
                PptxTextReplacement(
                    paths=["/slide[1]/shape[@id=2]"],
                    find="Unsafe",
                    replace="Blocked",
                )
            ],
        )


def test_office_engine_dispatches_pptx_inspect_validate_and_edit() -> None:
    document = _pptx(slide2=_slide(_formatted_shape()))

    assert office_engine.inspect(document, suffix=".pptx")["format"] == "pptx"
    assert office_engine.validate(document, suffix=".pptx")["slide_count"] == 2
    edited, reports = office_engine.edit(
        document,
        suffix=".pptx",
        operations=[
            PptxTextReplacement(
                paths=["/slide[1]/shape[@id=7]"],
                find="Alpha",
                replace="Updated",
                occurrence="first",
            )
        ],
    )
    assert reports[0]["match_count"] == 1
    inspected = inspect_pptx(
        edited,
        max_slides=1,
        include_formatting=True,
    )
    assert inspected["slides"][0]["objects"][0]["text_body"]["paragraphs"][0]["text"].startswith("Updated")

    with pytest.raises(OfficeOperationError, match="Unsupported Office operation"):
        office_engine.edit(
            document,
            suffix=".pptx",
            operations=[DocxTextReplacement(find="old", replace="new")],
        )

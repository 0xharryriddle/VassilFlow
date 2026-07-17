from __future__ import annotations

import hashlib
import io
import json
import warnings
import zipfile

import pytest
from lxml import etree

from vassilflow.community.office import docx as docx_module
from vassilflow.community.office.docx import (
    edit_docx,
    inspect_docx,
    validate_docx,
    validate_docx_renderable,
)
from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.errors import OfficeError, OfficeOperationError, OfficePackageError
from vassilflow.community.office.models import (
    DocxParagraphFormatOperation,
    DocxParagraphFormatting,
    DocxParagraphSelector,
    DocxRunFormatOperation,
    DocxRunFormatting,
    DocxRunSelector,
    DocxTextReplacement,
)
from vassilflow.community.office.policy import (
    normalize_office_image_path,
    normalize_office_output_dir,
    normalize_office_path,
)

_CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
_DEFAULT_MAIN_CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
_ROOT_RELS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
_EMPTY_RELS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
_EMPTY_PARAGRAPH_FORMATTING = {
    "alignment": None,
    "space_before": None,
    "space_after": None,
    "left_indent": None,
    "right_indent": None,
    "first_line_indent": None,
    "hanging_indent": None,
    "keep_with_next": None,
    "keep_lines": None,
    "page_break_before": None,
}


def _document(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    ).encode()


def _docx(
    body: str,
    *,
    document_relationships: bytes = _EMPTY_RELS,
    extra_parts: dict[str, bytes] | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("word/document.xml", _document(body))
        archive.writestr(
            "word/_rels/document.xml.rels",
            document_relationships,
        )
        for name, payload in (extra_parts or {}).items():
            archive.writestr(name, payload)
    return output.getvalue()


def _document_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read("word/document.xml").decode()


def test_inspect_returns_split_run_text_and_table_context() -> None:
    data = _docx('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Hello </w:t></w:r><w:r><w:t>world</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell value</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')

    result = inspect_docx(data)

    assert result["paragraph_count"] == 2
    assert result["paragraphs"] == [
        {
            "index": 1,
            "path": "/document/paragraph[1]",
            "context": "body",
            "style": "Heading1",
            "text": "Hello world",
            "truncated": False,
            "formatting": _EMPTY_PARAGRAPH_FORMATTING,
        },
        {
            "index": 2,
            "path": "/document/paragraph[2]",
            "context": "table_cell",
            "style": None,
            "text": "Cell value",
            "truncated": False,
            "formatting": _EMPTY_PARAGRAPH_FORMATTING,
        },
    ]


def test_inspect_can_include_bounded_run_paths_and_direct_formatting() -> None:
    data = _docx('<w:p><w:r><w:rPr><w:b/><w:color w:val="00AAFF"/><w:sz w:val="24"/></w:rPr><w:t>Styled</w:t></w:r><w:r><w:t> plain</w:t></w:r></w:p>')

    result = inspect_docx(data, include_runs=True)

    runs = result["paragraphs"][0]["runs"]
    assert result["include_runs"] is True
    assert [run["path"] for run in runs] == [
        "/document/paragraph[1]/run[1]",
        "/document/paragraph[1]/run[2]",
    ]
    assert runs[0]["formatting"]["bold"] is True
    assert runs[0]["formatting"]["color"] == "#00AAFF"
    assert runs[0]["formatting"]["font_size"] == 12
    assert runs[1]["formatting"]["bold"] is None


def test_inspect_run_details_are_globally_bounded() -> None:
    runs = "".join(f"<w:r><w:t>r{index}</w:t></w:r>" for index in range(205))

    result = inspect_docx(_docx(f"<w:p>{runs}</w:p>"), include_runs=True)

    paragraph = result["paragraphs"][0]
    assert len(paragraph["runs"]) == 200
    assert paragraph["runs_truncated"] is True


def test_ruby_annotation_has_stable_base_text_run_and_is_not_editable() -> None:
    data = _docx("<w:p><w:r><w:ruby><w:rubyPr/><w:rt><w:r><w:t>kanji</w:t></w:r></w:rt><w:rubyBase><w:r><w:t>&#28450;&#23383;</w:t></w:r></w:rubyBase></w:ruby></w:r><w:r><w:t> tail</w:t></w:r></w:p>")

    result = inspect_docx(data, include_runs=True)

    paragraph = result["paragraphs"][0]
    assert paragraph["text"] == "\u6f22\u5b57 tail"
    assert [(run["index"], run["text"]) for run in paragraph["runs"]] == [
        (1, "\u6f22\u5b57"),
        (2, " tail"),
    ]
    assert paragraph["runs"][0]["editable"] is False

    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        runs=DocxRunSelector(run_indices=[1]),
        formatting=DocxRunFormatting(bold=True),
    )
    with pytest.raises(OfficeOperationError, match="ruby annotation"):
        edit_docx(data, [operation])
    with pytest.raises(OfficeOperationError, match="ruby annotation"):
        edit_docx(data, [DocxTextReplacement(find="kanji", replace="hidden change")])
    with pytest.raises(OfficeOperationError, match="ruby annotation"):
        edit_docx(data, [DocxTextReplacement(find="\u6f22\u5b57", replace="base change")])


def test_replace_across_runs_preserves_package_and_first_run_formatting() -> None:
    data = _docx("<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Hello </w:t></w:r><w:r><w:t>world</w:t></w:r></w:p>")
    operation = DocxTextReplacement(find="Hello world", replace="Hi")

    edited, reports = edit_docx(data, [operation])

    assert reports[0]["match_count"] == 1
    assert inspect_docx(edited)["paragraphs"][0]["text"] == "Hi"
    xml = _document_xml(edited)
    assert "<w:b/>" in xml
    assert validate_docx(edited)["valid"] is True
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        assert set(archive.namelist()) == {
            "[Content_Types].xml",
            "_rels/.rels",
            "word/document.xml",
            "word/_rels/document.xml.rels",
        }


def test_docx_edit_receipt_records_hashes_paths_and_net_semantic_delta() -> None:
    source = _docx("<w:p><w:r><w:t>old value</w:t></w:r></w:p>")
    operation = DocxTextReplacement(find="old", replace="new")

    edited, reports, receipt = office_engine.edit_with_receipt(
        source,
        suffix=".docx",
        operations=[operation],
    )

    operation_id = reports[0]["operation_id"]
    assert operation_id.startswith("op-0001-")
    assert receipt["schema"] == "vassilflow.office.semantic_change_receipt.v1"
    assert receipt["status"] == "changed"
    assert receipt["source"] == {
        "sha256": hashlib.sha256(source).hexdigest(),
        "size_bytes": len(source),
    }
    assert receipt["result"] == {
        "sha256": hashlib.sha256(edited).hexdigest(),
        "size_bytes": len(edited),
    }
    assert receipt["applied_operation_ids"] == [operation_id]
    assert receipt["operations"] == [
        {
            "operation_id": operation_id,
            "position": 1,
            "type": "replace_text",
            "match_count": 1,
            "target_path_count": 1,
            "target_paths_returned": 1,
            "target_paths_truncated": False,
            "target_paths": ["/document/paragraph[1]"],
        }
    ]
    assert receipt["semantic_changes"]["semantic_deltas"] == [
        {
            "path": "/document/paragraph[1]",
            "semantic_kind": "docx_paragraph_text",
            "property": "text",
            "before": "old value",
            "after": "new value",
        }
    ]
    assert receipt["package_changes"]["parts"] == [
        {
            "part_name": "word/document.xml",
            "status": "changed",
            "before": {
                "sha256": hashlib.sha256(_document("<w:p><w:r><w:t>old value</w:t></w:r></w:p>")).hexdigest(),
                "size_bytes": len(_document("<w:p><w:r><w:t>old value</w:t></w:r></w:p>")),
            },
            "after": receipt["package_changes"]["parts"][0]["after"],
        }
    ]
    assert receipt["package_changes"]["relationship_change_count"] == 0
    json.dumps(receipt, allow_nan=False)


def test_docx_edit_receipt_covers_run_and_paragraph_formatting() -> None:
    source = _docx("<w:p><w:r><w:t>target</w:t></w:r></w:p>")

    _, reports, receipt = office_engine.edit_with_receipt(
        source,
        suffix=".docx",
        operations=[
            DocxRunFormatOperation(
                paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
                runs=DocxRunSelector(run_indices=[1]),
                formatting=DocxRunFormatting(bold=True),
            ),
            DocxParagraphFormatOperation(
                paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
                formatting=DocxParagraphFormatting(alignment="center"),
            ),
        ],
    )

    assert receipt["applied_operation_ids"] == [report["operation_id"] for report in reports]
    assert [record["target_paths"] for record in receipt["operations"]] == [
        ["/document/paragraph[1]/run[1]"],
        ["/document/paragraph[1]"],
    ]
    assert {delta["semantic_kind"] for delta in receipt["semantic_changes"]["semantic_deltas"]} == {"docx_run_format", "docx_paragraph_format"}
    assert {delta["property"] for delta in receipt["semantic_changes"]["semantic_deltas"]} >= {"formatting.bold", "formatting.alignment"}


def test_docx_edit_receipt_bounds_operation_and_semantic_evidence_explicitly() -> None:
    source = _docx("".join(f"<w:p><w:r><w:t>old {index}</w:t></w:r></w:p>" for index in range(1_001)))

    _, _, receipt = office_engine.edit_with_receipt(
        source,
        suffix=".docx",
        operations=[DocxTextReplacement(find="old", replace="new")],
    )

    operation = receipt["operations"][0]
    assert operation["match_count"] == 1_001
    assert operation["target_path_count"] == 1_001
    assert operation["target_paths_returned"] == 200
    assert operation["target_paths_truncated"] is True
    assert receipt["semantic_changes"]["coverage"] == "partial"
    assert receipt["semantic_changes"]["evaluated_target_count"] == 1_000
    assert receipt["semantic_changes"]["changed_target_count"] == 1_000
    assert receipt["semantic_changes"]["changed_target_paths_returned"] == 500
    assert receipt["semantic_changes"]["changed_target_paths_truncated"] is True


def test_docx_edit_receipt_represents_successful_no_match_as_unchanged() -> None:
    source = _docx("<w:p><w:r><w:t>original</w:t></w:r></w:p>")

    edited, reports, receipt = office_engine.edit_with_receipt(
        source,
        suffix=".docx",
        operations=[
            DocxTextReplacement(
                find="missing",
                replace="unused",
                require_match=False,
            )
        ],
    )

    assert edited == source
    assert reports[0]["match_count"] == 0
    assert receipt["status"] == "unchanged"
    assert receipt["source"] == receipt["result"]
    assert receipt["operations"][0]["target_path_count"] == 0
    assert receipt["semantic_changes"]["evaluated_target_count"] == 0
    assert receipt["semantic_changes"]["semantic_delta_count"] == 0
    assert receipt["package_changes"]["part_change_count"] == 0
    assert receipt["package_changes"]["relationship_change_count"] == 0


def test_validate_accepts_main_document_content_type_from_default_extension() -> None:
    source = io.BytesIO(_docx("<w:p><w:r><w:t>Valid</w:t></w:r></w:p>"))
    output = io.BytesIO()
    with zipfile.ZipFile(source) as input_archive, zipfile.ZipFile(output, "w") as output_archive:
        for info in input_archive.infolist():
            payload = input_archive.read(info)
            if info.filename == "[Content_Types].xml":
                payload = _DEFAULT_MAIN_CONTENT_TYPES
            output_archive.writestr(info, payload)

    assert validate_docx(output.getvalue())["valid"] is True


def test_occurrence_first_is_document_scoped() -> None:
    data = _docx("<w:p><w:r><w:t>alpha alpha</w:t></w:r></w:p><w:p><w:r><w:t>alpha</w:t></w:r></w:p>")

    edited, reports = edit_docx(
        data,
        [DocxTextReplacement(find="alpha", replace="beta", occurrence="first")],
    )

    assert reports[0]["match_count"] == 1
    assert [item["text"] for item in inspect_docx(edited)["paragraphs"]] == ["beta alpha", "alpha"]


def test_typed_run_selector_applies_allowlisted_formatting_in_schema_order() -> None:
    data = _docx('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Alpha </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>Beta</w:t></w:r></w:p>')
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(style="heading1", contains_text="Alpha"),
        runs=DocxRunSelector(run_indices=[2], bold=True),
        formatting=DocxRunFormatting(
            italic=True,
            color="#FF0000",
            font="Noto Sans",
            font_size=16,
            underline="wave",
        ),
    )

    edited, reports = edit_docx(data, [operation])

    assert reports[0]["match_count"] == 1
    runs = inspect_docx(edited, include_runs=True)["paragraphs"][0]["runs"]
    assert runs[0]["formatting"]["italic"] is None
    assert runs[1]["formatting"] == {
        "bold": True,
        "italic": True,
        "underline": "wave",
        "underline_color": None,
        "strike": None,
        "double_strike": None,
        "all_caps": None,
        "small_caps": None,
        "color": "#FF0000",
        "highlight": None,
        "font": "Noto Sans",
        "font_ascii": "Noto Sans",
        "font_high_ansi": "Noto Sans",
        "font_east_asia": "Noto Sans",
        "font_complex_script": None,
        "font_size": 16,
        "font_size_complex_script": None,
        "vertical_alignment": None,
    }

    root = etree.fromstring(_document_xml(edited).encode())
    properties = root.xpath("./w:body/w:p[1]/w:r[2]/w:rPr", namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"})[0]
    assert [etree.QName(child).localname for child in properties] == [
        "rFonts",
        "b",
        "i",
        "color",
        "sz",
        "u",
    ]


def test_run_formatting_preserves_unrelated_script_and_underline_metadata() -> None:
    data = _docx(
        '<w:p><w:r><w:rPr><w:rFonts w:asciiTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi" '
        'w:cs="Amiri" w:hint="eastAsia"/><w:sz w:val="20"/><w:szCs w:val="28"/>'
        '<w:u w:val="single" w:color="00FF00" w:themeColor="accent1"/></w:rPr>'
        "<w:t>Metadata</w:t></w:r></w:p>"
    )
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        formatting=DocxRunFormatting(font="Noto Sans", font_size=16, underline="double"),
    )

    edited, _ = edit_docx(data, [operation])

    root = etree.fromstring(_document_xml(edited).encode())
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    fonts = root.xpath("./w:body/w:p/w:r/w:rPr/w:rFonts", namespaces=namespace)[0]
    size_cs = root.xpath("./w:body/w:p/w:r/w:rPr/w:szCs", namespaces=namespace)[0]
    underline = root.xpath("./w:body/w:p/w:r/w:rPr/w:u", namespaces=namespace)[0]
    word = namespace["w"]
    assert fonts.get(f"{{{word}}}ascii") == "Noto Sans"
    assert fonts.get(f"{{{word}}}hAnsi") == "Noto Sans"
    assert fonts.get(f"{{{word}}}eastAsia") == "Noto Sans"
    assert fonts.get(f"{{{word}}}cs") == "Amiri"
    assert fonts.get(f"{{{word}}}asciiTheme") == "minorHAnsi"
    assert fonts.get(f"{{{word}}}hint") == "eastAsia"
    assert size_cs.get(f"{{{word}}}val") == "28"
    assert underline.get(f"{{{word}}}val") == "double"
    assert underline.get(f"{{{word}}}color") == "00FF00"
    assert underline.get(f"{{{word}}}themeColor") == "accent1"


def test_setting_underline_rgb_clears_previous_theme_binding() -> None:
    data = _docx('<w:p><w:r><w:rPr><w:u w:val="single" w:color="00FF00" w:themeColor="accent1" w:themeTint="80" w:themeShade="20"/></w:rPr><w:t>Theme-bound</w:t></w:r></w:p>')
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        formatting=DocxRunFormatting(underline_color="#008800"),
    )

    edited, _ = edit_docx(data, [operation])

    root = etree.fromstring(_document_xml(edited).encode())
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    underline = root.xpath("./w:body/w:p/w:r/w:rPr/w:u", namespaces=namespace)[0]
    word = namespace["w"]
    assert underline.get(f"{{{word}}}val") == "single"
    assert underline.get(f"{{{word}}}color") == "008800"
    assert underline.get(f"{{{word}}}themeColor") is None
    assert underline.get(f"{{{word}}}themeTint") is None
    assert underline.get(f"{{{word}}}themeShade") is None


def test_inspect_reports_extended_direct_run_and_paragraph_formatting() -> None:
    data = _docx(
        '<w:p><w:pPr><w:keepNext w:val="0"/><w:keepLines/><w:pageBreakBefore/>'
        '<w:spacing w:before="120" w:after="240"/><w:ind w:left="-20" w:right="40" '
        'w:firstLine="60"/><w:jc w:val="both"/></w:pPr><w:r><w:rPr>'
        '<w:rFonts w:ascii="Arial" w:hAnsi="Calibri" w:eastAsia="Noto Sans CJK SC" '
        'w:cs="Amiri"/><w:caps/><w:smallCaps w:val="0"/><w:dstrike/>'
        '<w:color w:val="AA00CC"/><w:sz w:val="24"/><w:szCs w:val="30"/>'
        '<w:u w:val="double" w:color="008800"/><w:vertAlign w:val="superscript"/>'
        "</w:rPr><w:t>Extended</w:t></w:r></w:p>"
    )

    paragraph = inspect_docx(data, include_runs=True)["paragraphs"][0]

    assert paragraph["formatting"] == {
        "alignment": "justify",
        "space_before": 6,
        "space_after": 12,
        "left_indent": -1,
        "right_indent": 2,
        "first_line_indent": 3,
        "hanging_indent": None,
        "keep_with_next": False,
        "keep_lines": True,
        "page_break_before": True,
    }
    formatting = paragraph["runs"][0]["formatting"]
    assert formatting["double_strike"] is True
    assert formatting["all_caps"] is True
    assert formatting["small_caps"] is False
    assert formatting["underline_color"] == "#008800"
    assert formatting["font_ascii"] == "Arial"
    assert formatting["font_high_ansi"] == "Calibri"
    assert formatting["font_east_asia"] == "Noto Sans CJK SC"
    assert formatting["font_complex_script"] == "Amiri"
    assert formatting["font_size_complex_script"] == 15
    assert formatting["vertical_alignment"] == "superscript"


def test_extended_run_selector_and_formatting_target_one_directly_formatted_run() -> None:
    data = _docx('<w:p><w:r><w:rPr><w:rFonts w:eastAsia="Noto Sans CJK SC"/><w:dstrike/><w:color w:val="AA00CC"/><w:vertAlign w:val="superscript"/></w:rPr><w:t>Target</w:t></w:r><w:r><w:t>Untouched</w:t></w:r></w:p>')
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        runs=DocxRunSelector(
            double_strike=True,
            color="#aa00cc",
            font_east_asia="Noto Sans CJK SC",
            vertical_alignment="superscript",
        ),
        formatting=DocxRunFormatting(
            underline="wave",
            underline_color="#008800",
            font_complex_script="Amiri",
            font_size_complex_script=15,
        ),
    )

    edited, reports = edit_docx(data, [operation])

    assert reports[0]["match_count"] == 1
    runs = inspect_docx(edited, include_runs=True)["paragraphs"][0]["runs"]
    assert runs[0]["formatting"]["underline"] == "wave"
    assert runs[0]["formatting"]["underline_color"] == "#008800"
    assert runs[0]["formatting"]["font_complex_script"] == "Amiri"
    assert runs[0]["formatting"]["font_size_complex_script"] == 15
    assert runs[1]["formatting"]["underline"] is None


def test_run_formatting_does_not_reorder_existing_known_properties() -> None:
    data = _docx('<w:p><w:r><w:rPr><w:u w:val="single"/><w:b/></w:rPr><w:t>Order</w:t></w:r></w:p>')
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        formatting=DocxRunFormatting(color="#123456"),
    )

    edited, _ = edit_docx(data, [operation])

    root = etree.fromstring(_document_xml(edited).encode())
    properties = root.xpath(
        "./w:body/w:p/w:r/w:rPr",
        namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"},
    )[0]
    assert [etree.QName(child).localname for child in properties] == ["color", "u", "b"]


def test_run_formatting_preserves_foreign_extension_placement() -> None:
    data = _docx(
        '<w:p><w:r><w:rPr><w:rFonts w:ascii="Arial"/>'
        '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">'
        '<mc:Choice Requires="w14"><w:b/></mc:Choice></mc:AlternateContent>'
        "<w:i/></w:rPr><w:t>Extension-safe</w:t></w:r></w:p>"
    )
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        formatting=DocxRunFormatting(color="#123456"),
    )

    edited, _ = edit_docx(data, [operation])

    root = etree.fromstring(_document_xml(edited).encode())
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    properties = root.xpath("./w:body/w:p/w:r/w:rPr", namespaces=namespace)[0]
    assert [etree.QName(child).localname for child in properties] == [
        "rFonts",
        "AlternateContent",
        "i",
        "color",
    ]
    assert etree.QName(properties[1]).namespace == "http://schemas.openxmlformats.org/markup-compatibility/2006"


def test_run_formatting_places_new_standard_property_before_word_2010_tail() -> None:
    data = _docx('<w:p><w:r><w:rPr><w:rFonts w:ascii="Arial"/><w14:textOutline xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"/></w:rPr><w:t>Extension-tail</w:t></w:r></w:p>')
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        formatting=DocxRunFormatting(color="#123456"),
    )

    edited, _ = edit_docx(data, [operation])

    root = etree.fromstring(_document_xml(edited).encode())
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    properties = root.xpath("./w:body/w:p/w:r/w:rPr", namespaces=namespace)[0]
    assert [etree.QName(child).localname for child in properties] == [
        "rFonts",
        "color",
        "textOutline",
    ]


def test_typed_paragraph_selector_formats_style_and_table_context() -> None:
    data = _docx('<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr><w:r><w:t>Body</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr><w:r><w:t>Cell target</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    operation = DocxParagraphFormatOperation(
        paragraphs=DocxParagraphSelector(style="bodytext", context="table_cell"),
        formatting=DocxParagraphFormatting(alignment="center"),
    )

    edited, reports = edit_docx(data, [operation])

    assert reports[0]["match_count"] == 1
    root = etree.fromstring(_document_xml(edited).encode())
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    assert not root.xpath("./w:body/w:p[1]/w:pPr/w:jc", namespaces=namespace)
    assert root.xpath("string(./w:body/w:tbl/w:tr/w:tc/w:p/w:pPr/w:jc/@w:val)", namespaces=namespace) == "center"


def test_paragraph_layout_formatting_preserves_sibling_metadata_and_schema_order() -> None:
    data = _docx('<w:p><w:pPr><w:pStyle w:val="BodyText"/><w:spacing w:beforeLines="60"/><w:ind w:leftChars="100" w:hanging="120"/><w:jc w:val="center"/></w:pPr><w:r><w:t>Layout target</w:t></w:r></w:p>')
    operation = DocxParagraphFormatOperation(
        paragraphs=DocxParagraphSelector(alignment="center"),
        formatting=DocxParagraphFormatting(
            space_before=6.5,
            space_after=12,
            left_indent=-1,
            right_indent=2,
            first_line_indent=18,
            keep_with_next=False,
            keep_lines=True,
            page_break_before=True,
        ),
    )

    edited, reports = edit_docx(data, [operation])

    assert reports[0]["match_count"] == 1
    root = etree.fromstring(_document_xml(edited).encode())
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    properties = root.xpath("./w:body/w:p/w:pPr", namespaces=namespace)[0]
    assert [etree.QName(child).localname for child in properties] == [
        "pStyle",
        "keepNext",
        "keepLines",
        "pageBreakBefore",
        "spacing",
        "ind",
        "jc",
    ]
    spacing = properties.xpath("./w:spacing", namespaces=namespace)[0]
    indentation = properties.xpath("./w:ind", namespaces=namespace)[0]
    word = namespace["w"]
    assert spacing.get(f"{{{word}}}before") == "130"
    assert spacing.get(f"{{{word}}}after") == "240"
    assert spacing.get(f"{{{word}}}beforeLines") == "60"
    assert indentation.get(f"{{{word}}}left") == "-20"
    assert indentation.get(f"{{{word}}}right") == "40"
    assert indentation.get(f"{{{word}}}firstLine") == "360"
    assert indentation.get(f"{{{word}}}hanging") is None
    assert indentation.get(f"{{{word}}}leftChars") == "100"
    formatting = inspect_docx(edited)["paragraphs"][0]["formatting"]
    assert formatting["space_before"] == 6.5
    assert formatting["left_indent"] == -1
    assert formatting["first_line_indent"] == 18
    assert formatting["keep_with_next"] is False
    assert formatting["keep_lines"] is True
    assert formatting["page_break_before"] is True


def test_run_formatting_writes_explicit_false_override() -> None:
    data = _docx("<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Inherited-safe</w:t></w:r></w:p>")
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        runs=DocxRunSelector(bold=True),
        formatting=DocxRunFormatting(bold=False),
    )

    edited, reports = edit_docx(data, [operation])

    assert reports[0]["match_count"] == 1
    run = inspect_docx(edited, include_runs=True)["paragraphs"][0]["runs"][0]
    assert run["formatting"]["bold"] is False
    assert 'w:b w:val="0"' in _document_xml(edited)


def test_run_formatting_rejects_tracked_change_target() -> None:
    data = _docx('<w:p><w:ins w:id="1" w:author="Editor"><w:r><w:t>inserted</w:t></w:r></w:ins></w:p>')
    operation = DocxRunFormatOperation(
        paragraphs=DocxParagraphSelector(paragraph_indices=[1]),
        formatting=DocxRunFormatting(bold=True),
    )

    with pytest.raises(OfficeOperationError, match="tracked insertion"):
        edit_docx(data, [operation])


def test_typed_selector_and_formatting_reject_unbounded_or_ambiguous_inputs() -> None:
    with pytest.raises(ValueError, match="at least one filter"):
        DocxParagraphSelector()
    with pytest.raises(ValueError, match="at least one property"):
        DocxRunFormatting()
    with pytest.raises(ValueError, match="0.5-point"):
        DocxRunFormatting(font_size=10.25)
    with pytest.raises(ValueError, match="cannot be combined"):
        DocxRunFormatting(font="Arial", font_ascii="Calibri")
    with pytest.raises(ValueError, match="cannot both be true"):
        DocxRunFormatting(all_caps=True, small_caps=True)
    with pytest.raises(ValueError, match="at least one property"):
        DocxParagraphFormatting()
    with pytest.raises(ValueError, match="mutually exclusive"):
        DocxParagraphFormatting(first_line_indent=12, hanging_indent=12)
    with pytest.raises(ValueError, match="0.05-point"):
        DocxParagraphFormatting(space_before=1.01)


def test_edit_transaction_fails_when_a_required_operation_does_not_match() -> None:
    data = _docx("<w:p><w:r><w:t>original</w:t></w:r></w:p>")

    with pytest.raises(OfficeOperationError, match="no document changes were written"):
        edit_docx(
            data,
            [
                DocxTextReplacement(find="original", replace="changed"),
                DocxTextReplacement(find="missing", replace="never written"),
            ],
        )

    assert inspect_docx(data)["paragraphs"][0]["text"] == "original"


def test_edit_no_match_returns_the_exact_source_package_when_allowed() -> None:
    data = _docx("<w:p><w:r><w:t>original</w:t></w:r></w:p>")

    edited, reports = edit_docx(
        data,
        [
            DocxTextReplacement(
                find="missing",
                replace="never written",
                require_match=False,
            )
        ],
    )

    assert edited == data
    assert reports[0]["match_count"] == 0


def test_replace_rejects_match_crossing_hyperlink_boundary() -> None:
    relationships = b"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="links/target.xml"/>
    </Relationships>"""
    data = _docx(
        '<w:p><w:hyperlink r:id="rId5"><w:r><w:t>linked</w:t></w:r></w:hyperlink><w:r><w:t> plain</w:t></w:r></w:p>',
        document_relationships=relationships,
        extra_parts={"word/links/target.xml": b"<target/>"},
    )

    with pytest.raises(OfficeOperationError, match="hyperlink boundary"):
        edit_docx(data, [DocxTextReplacement(find="linked plain", replace="unsafe")])


def test_replace_rejects_match_crossing_tab_boundary() -> None:
    data = _docx("<w:p><w:r><w:t>left</w:t><w:tab/><w:t>right</w:t></w:r></w:p>")

    assert inspect_docx(data)["paragraphs"][0]["text"] == "left\tright"
    with pytest.raises(OfficeOperationError, match="semantic document boundary"):
        edit_docx(data, [DocxTextReplacement(find="leftright", replace="unsafe")])


def test_replace_rejects_tracked_change_text() -> None:
    data = _docx('<w:p><w:ins w:id="1" w:author="Editor"><w:r><w:t>inserted</w:t></w:r></w:ins></w:p>')

    with pytest.raises(OfficeOperationError, match="tracked insertion"):
        edit_docx(data, [DocxTextReplacement(find="inserted", replace="changed")])


def test_textbox_paragraphs_are_outside_the_first_batch_contract() -> None:
    data = _docx("<w:p><w:r><w:t>body</w:t></w:r></w:p><w:p><w:r><w:drawing><w:txbxContent><w:p><w:r><w:t>textbox</w:t></w:r></w:p></w:txbxContent></w:drawing></w:r></w:p>")

    result = inspect_docx(data)

    assert result["paragraph_count"] == 2
    assert [paragraph["text"] for paragraph in result["paragraphs"]] == ["body", ""]


@pytest.mark.parametrize(
    ("path", "writable", "expected"),
    [
        ("/mnt/user-data/uploads/in.docx", False, "/mnt/user-data/uploads/in.docx"),
        ("/mnt/user-data/workspace/out.docx", True, "/mnt/user-data/workspace/out.docx"),
        ("/mnt/user-data/uploads/slides.pptx", False, "/mnt/user-data/uploads/slides.pptx"),
        ("\\mnt\\user-data\\outputs\\out.DOCX", True, "/mnt/user-data/outputs/out.DOCX"),
    ],
)
def test_office_path_policy_accepts_thread_scoped_docx(path: str, writable: bool, expected: str) -> None:
    assert normalize_office_path(path, writable=writable) == expected


@pytest.mark.parametrize(
    ("path", "writable"),
    [
        ("/mnt/user-data/uploads/../workspace/out.docx", True),
        ("/mnt/user-data/uploads/out.docx", True),
        ("/etc/report.docx", False),
        ("/mnt/user-data/workspace/report.pptm", True),
    ],
)
def test_office_path_policy_rejects_unsafe_or_unsupported_paths(path: str, writable: bool) -> None:
    with pytest.raises(OfficeError):
        normalize_office_path(path, writable=writable)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "/mnt/user-data/workspace/visual-qa",
            "/mnt/user-data/workspace/visual-qa",
        ),
        (
            "\\mnt\\user-data\\outputs\\report-render",
            "/mnt/user-data/outputs/report-render",
        ),
    ],
)
def test_office_render_output_dir_policy_accepts_writable_thread_paths(
    path: str,
    expected: str,
) -> None:
    assert normalize_office_output_dir(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/mnt/user-data/uploads/visual-qa",
        "/mnt/user-data/workspace/../outputs/visual-qa",
        "/mnt/user-data/workspace/page.png",
    ],
)
def test_office_render_output_dir_policy_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(OfficeError):
        normalize_office_output_dir(path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "/mnt/user-data/uploads/fill.png",
            "/mnt/user-data/uploads/fill.png",
        ),
        (
            "\\mnt\\user-data\\workspace\\fill.PNG",
            "/mnt/user-data/workspace/fill.PNG",
        ),
        (
            "/mnt/user-data/uploads/fill.jpg",
            "/mnt/user-data/uploads/fill.jpg",
        ),
        (
            "/mnt/user-data/outputs/fill.JPEG",
            "/mnt/user-data/outputs/fill.JPEG",
        ),
    ],
)
def test_office_image_path_policy_accepts_thread_images(
    path: str,
    expected: str,
) -> None:
    assert normalize_office_image_path(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "https://example.test/fill.png",
        "/mnt/user-data/uploads/../workspace/fill.png",
        "/mnt/user-data/uploads/fill.gif",
        "/etc/fill.png",
    ],
)
def test_office_image_path_policy_rejects_external_or_unsupported_paths(
    path: str,
) -> None:
    with pytest.raises(OfficeError):
        normalize_office_image_path(path)


def test_duplicate_package_entry_is_rejected() -> None:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
            archive.writestr("word/document.xml", _document("<w:p/>"))
            archive.writestr("word/document.xml", _document("<w:p/>"))

    with pytest.raises(OfficePackageError, match="duplicate package entry"):
        inspect_docx(output.getvalue())


def test_docx_validation_rejects_missing_opc_main_document_declarations() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", _EMPTY_RELS)
        archive.writestr("word/document.xml", _document("<w:p/>"))

    with pytest.raises(OfficePackageError, match="Content_Types"):
        validate_docx(output.getvalue())


def test_docx_validation_rejects_dangling_relationship_references() -> None:
    source = _docx('<w:p><w:hyperlink r:id="rIdMissing"><w:r><w:t>link</w:t></w:r></w:hyperlink></w:p>')

    with pytest.raises(
        OfficePackageError,
        match="references missing relationships: rIdMissing",
    ):
        validate_docx(source)


def test_docx_active_content_is_inspectable_but_not_editable_or_renderable() -> None:
    relationships = b"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.test" TargetMode="External"/>
    </Relationships>"""
    source = _docx(
        '<w:p><w:hyperlink r:id="rId5"><w:r><w:t>linked</w:t></w:r></w:hyperlink></w:p>',
        document_relationships=relationships,
    )

    validation = validate_docx(source)
    assert validation["risky_features"] == ["external relationships"]
    assert inspect_docx(source)["paragraphs"][0]["text"] == "linked"
    with pytest.raises(OfficeOperationError, match="editing is disabled"):
        edit_docx(
            source,
            [DocxTextReplacement(find="linked", replace="changed")],
        )
    with pytest.raises(OfficeOperationError, match="rendering is disabled"):
        validate_docx_renderable(source)


def test_docx_document_structure_is_preflight_bounded(monkeypatch) -> None:
    source = _docx("<w:p><w:r><w:t>bounded</w:t></w:r></w:p>")
    monkeypatch.setattr(docx_module, "_MAX_DOCUMENT_XML_ELEMENTS", 3)

    with pytest.raises(OfficePackageError, match="element limit"):
        validate_docx(source)

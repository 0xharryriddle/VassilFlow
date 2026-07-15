"""Structured contracts exposed by VassilFlow Office tools."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ParagraphIndex = Annotated[int, Field(ge=1)]
RunIndex = Annotated[int, Field(ge=1)]
ParagraphAlignment = Literal["left", "center", "right", "justify"]
UnderlineStyle = Literal["none", "single", "double", "thick", "dotted", "dash", "wave"]
VerticalAlignment = Literal["baseline", "superscript", "subscript"]
HighlightColor = Literal[
    "none",
    "yellow",
    "green",
    "cyan",
    "magenta",
    "blue",
    "red",
    "darkBlue",
    "darkCyan",
    "darkGreen",
    "darkMagenta",
    "darkRed",
    "darkYellow",
    "darkGray",
    "lightGray",
    "black",
    "white",
]
XlsxCellDataType = Literal["blank", "string", "number", "boolean", "date", "error", "formula"]
XlsxHorizontalAlignment = Literal["general", "left", "center", "right", "justify", "distributed"]
XlsxVerticalAlignment = Literal["top", "center", "bottom", "justify", "distributed"]
XlsxUnderlineStyle = Literal["none", "single", "double"]
PptxObjectKind = Literal[
    "shape",
    "title",
    "placeholder",
    "text_box",
    "picture",
    "video",
    "audio",
    "group",
    "connector",
    "table",
    "chart",
    "ole",
    "smartart",
    "model3d",
    "graphic_frame",
]
PptxUnderlineStyle = Literal["none", "single", "double"]
PptxStrikeStyle = Literal["none", "single", "double"]
PptxVerticalAnchor = Literal["top", "middle", "bottom"]
PptxLineCap = Literal["flat", "round", "square"]
PptxPresetLineDash = Literal[
    "solid",
    "dot",
    "dash",
    "dash_dot",
    "large_dash",
    "large_dash_dot",
    "large_dash_dot_dot",
    "system_dot",
    "system_dash",
    "system_dash_dot",
    "system_dash_dot_dot",
]
PptxLineJoin = Literal["round", "bevel", "miter"]
PptxLineCompound = Literal[
    "single",
    "double",
    "thick_thin",
    "thin_thick",
    "triple",
]
PptxLineAlignment = Literal["center", "inset"]
PptxLineEndType = Literal["none", "triangle", "stealth", "diamond", "oval", "arrow"]
PptxLineEndSize = Literal["small", "medium", "large"]
PptxImageFillMode = Literal["stretch", "tile", "center"]
PptxImageTileAlignment = Literal[
    "top_left",
    "top",
    "top_right",
    "left",
    "center",
    "right",
    "bottom_left",
    "bottom",
    "bottom_right",
]
PptxImageTileFlip = Literal["none", "horizontal", "vertical", "both"]
PptxPresetGeometry = Literal[
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
]
PptxPresetPattern = Literal[
    "pct5",
    "pct10",
    "pct20",
    "pct25",
    "pct30",
    "pct40",
    "pct50",
    "pct60",
    "pct70",
    "pct75",
    "pct80",
    "pct90",
    "horz",
    "vert",
    "ltHorz",
    "ltVert",
    "dkHorz",
    "dkVert",
    "narHorz",
    "narVert",
    "dnDiag",
    "upDiag",
    "ltDnDiag",
    "ltUpDiag",
    "dkDnDiag",
    "dkUpDiag",
    "wdDnDiag",
    "wdUpDiag",
    "dashHorz",
    "dashVert",
    "dashDnDiag",
    "dashUpDiag",
    "cross",
    "diagCross",
    "smGrid",
    "lgGrid",
    "smCheck",
    "lgCheck",
    "smConfetti",
    "lgConfetti",
    "zigZag",
    "wave",
    "diagBrick",
    "horzBrick",
    "weave",
    "plaid",
    "divot",
    "dotGrid",
    "dotDmnd",
    "shingle",
    "trellis",
    "sphere",
    "openDmnd",
    "solidDmnd",
]

_XLSX_RANGE_RE = re.compile(
    r"^(?P<start_col>[A-Za-z]{1,3})(?P<start_row>[1-9][0-9]{0,6})"
    r"(?::(?P<end_col>[A-Za-z]{1,3})(?P<end_row>[1-9][0-9]{0,6}))?$"
)
_MAX_XLSX_ROWS = 1_048_576
_MAX_XLSX_COLUMNS = 16_384
_MAX_XLSX_SELECTED_CELLS = 10_000
_MAX_PPTX_OBJECT_PATH_CHARS = 16_384
_PPTX_SLIDE_PATH_RE = re.compile(r"^/slide\[(?:[1-9][0-9]{0,3})\]$")
_PPTX_OBJECT_PATH_RE = re.compile(
    r"^/slide\[(?:[1-9][0-9]{0,3})\]"
    r"(?:/(?:shape|picture|group|connector|table|chart|ole|smartart|model3d|graphic_frame)"
    r"\[(?:@id=(?:0|[1-9][0-9]{0,9})|[1-9][0-9]{0,3})\])+$"
)
_PPTX_STABLE_PARAGRAPH_PATH_RE = re.compile(
    r"^/slide\[(?:[1-9][0-9]{0,3})\]"
    r"(?:/group\[@id=(?:0|[1-9][0-9]{0,9})\])*"
    r"/shape\[@id=(?:0|[1-9][0-9]{0,9})\]"
    r"/paragraph\[(?:[1-9][0-9]{0,3})\]$"
)
_PPTX_STABLE_RUN_PATH_RE = re.compile(
    r"^/slide\[(?:[1-9][0-9]{0,3})\]"
    r"(?:/group\[@id=(?:0|[1-9][0-9]{0,9})\])*"
    r"/shape\[@id=(?:0|[1-9][0-9]{0,9})\]"
    r"/paragraph\[(?:[1-9][0-9]{0,3})\]"
    r"/run\[(?:[1-9][0-9]{0,3})\]$"
)
_PPTX_STABLE_SHAPE_PATH_RE = re.compile(
    r"^/slide\[(?:[1-9][0-9]{0,3})\]"
    r"(?:/group\[@id=(?:0|[1-9][0-9]{0,9})\])*"
    r"/shape\[@id=(?:0|[1-9][0-9]{0,9})\]$"
)
_PPTX_STABLE_PICTURE_PATH_RE = re.compile(
    r"^/slide\[(?:[1-9][0-9]{0,3})\]"
    r"(?:/group\[@id=(?:0|[1-9][0-9]{0,9})\])*"
    r"/picture\[@id=(?:0|[1-9][0-9]{0,9})\]$"
)
_PPTX_STABLE_LINE_PATH_RE = re.compile(
    r"^/slide\[(?:[1-9][0-9]{0,3})\]"
    r"(?:/group\[@id=(?:0|[1-9][0-9]{0,9})\])*"
    r"/(?:shape|connector)\[@id=(?:0|[1-9][0-9]{0,9})\]$"
)


def _normalize_font_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or any(ord(char) < 32 for char in normalized):
        raise ValueError("font must be a printable non-empty name")
    return normalized


def _validate_half_points(value: float | None) -> float | None:
    if value is not None and not (value * 2).is_integer():
        raise ValueError("font size must use 0.5-point increments")
    return value


def _validate_twentieth_points(value: float | None) -> float | None:
    if value is not None and abs(value * 20 - round(value * 20)) > 1e-8:
        raise ValueError("paragraph measurements must use 0.05-point increments")
    return value


def _validate_hundredth_points(value: float | None) -> float | None:
    if value is not None and abs(value * 100 - round(value * 100)) > 1e-8:
        raise ValueError("PPTX point measurements must use 0.01-point increments")
    return value


def _validate_thousandth_percent(value: float | None) -> float | None:
    if value is not None and abs(value * 1_000 - round(value * 1_000)) > 1e-8:
        raise ValueError("PPTX percentages must use 0.001-percent increments")
    return value


def _validate_pptx_expected_text(value: str) -> str:
    if any(not (character in {"\t", "\n", "\r"} or "\u0020" <= character <= "\ud7ff" or "\ue000" <= character <= "\ufffd" or "\U00010000" <= character <= "\U0010ffff") for character in value):
        raise ValueError("expected_text contains invalid XML text")
    return value


def _normalize_pptx_exact_selector_compat(value: object) -> object:
    """Drop only inert union fields that some tool-call models emit."""
    if not isinstance(value, dict):
        return value

    normalized = dict(value)
    if normalized.get("contains_text") is None:
        normalized.pop("contains_text", None)
    if normalized.get("occurrence") in {None, "all"}:
        normalized.pop("occurrence", None)
    require_match = normalized.get("require_match")
    if require_match is None or require_match is True:
        normalized.pop("require_match", None)
    return normalized


def _xlsx_column_index(label: str) -> int:
    value = 0
    for char in label.upper():
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def _normalize_xlsx_range(value: str) -> tuple[str, tuple[int, int, int, int]]:
    match = _XLSX_RANGE_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError("ranges must contain A1 cells or rectangular A1:B10 ranges")
    start_col = match.group("start_col").upper()
    start_row = int(match.group("start_row"))
    end_col = (match.group("end_col") or start_col).upper()
    end_row = int(match.group("end_row") or start_row)
    start_col_index = _xlsx_column_index(start_col)
    end_col_index = _xlsx_column_index(end_col)
    if end_row > _MAX_XLSX_ROWS or end_col_index > _MAX_XLSX_COLUMNS:
        raise ValueError("ranges must stay within Excel's XFD1048576 worksheet bounds")
    if end_row < start_row or end_col_index < start_col_index:
        raise ValueError("ranges must run from the top-left cell to the bottom-right cell")
    normalized = f"{start_col}{start_row}"
    if start_col != end_col or start_row != end_row:
        normalized += f":{end_col}{end_row}"
    return normalized, (start_col_index, start_row, end_col_index, end_row)


def _xlsx_range_union_cell_count(
    bounds: list[tuple[int, int, int, int]],
) -> int:
    column_boundaries = sorted({boundary for min_col, _, max_col, _ in bounds for boundary in (min_col, max_col + 1)})
    selected_cells = 0
    for min_col, next_col in zip(column_boundaries, column_boundaries[1:]):
        row_intervals = sorted((min_row, max_row) for range_min_col, min_row, range_max_col, max_row in bounds if range_min_col <= min_col <= range_max_col)
        if not row_intervals:
            continue
        covered_rows = 0
        interval_start, interval_end = row_intervals[0]
        for next_start, next_end in row_intervals[1:]:
            if next_start <= interval_end + 1:
                interval_end = max(interval_end, next_end)
                continue
            covered_rows += interval_end - interval_start + 1
            interval_start, interval_end = next_start, next_end
        covered_rows += interval_end - interval_start + 1
        selected_cells += (next_col - min_col) * covered_rows
        if selected_cells > _MAX_XLSX_SELECTED_CELLS:
            return selected_cells
    return selected_cells


def _validate_xlsx_number_format(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > 255:
        raise ValueError("number_format may contain at most 255 characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError("number_format must not contain control characters")

    in_quote = False
    bracket_depth = 0
    section_count = 1
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            in_quote = not in_quote
        elif not in_quote and char == "[":
            bracket_depth += 1
        elif not in_quote and char == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                raise ValueError("number_format must use balanced square brackets")
        elif not in_quote and bracket_depth == 0 and char == ";":
            section_count += 1
        index += 1

    if in_quote:
        raise ValueError("number_format must use balanced double quotes")
    if bracket_depth:
        raise ValueError("number_format must use balanced square brackets")
    if section_count > 4:
        raise ValueError("number_format may contain at most four semicolon-separated sections")
    return value


class PptxObjectSelector(BaseModel):
    """Typed, conjunctive selector over stable PPTX object paths."""

    model_config = ConfigDict(extra="forbid")

    paths: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description=("Exact stable object paths returned by office_inspect; wildcards and combinators are not accepted"),
    )
    kinds: list[PptxObjectKind] | None = Field(
        default=None,
        min_length=1,
        max_length=15,
        description="Object kinds to include; values within this field are OR-matched",
    )
    contains_text: str | None = Field(
        default=None,
        min_length=1,
        max_length=1_000,
        description="Case-sensitive literal substring required in object text",
    )
    has_text: bool | None = Field(
        default=None,
        description="Match whether the object has non-whitespace visible text",
    )
    name_equals: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Case-sensitive exact object name returned by inspection",
    )
    has_alt_text: bool | None = Field(
        default=None,
        description="Match whether the object has non-whitespace authored alt text",
    )

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if len(set(values)) != len(values):
            raise ValueError("paths must not contain duplicates")
        if any(len(value) > _MAX_PPTX_OBJECT_PATH_CHARS for value in values):
            raise ValueError(f"paths may contain at most {_MAX_PPTX_OBJECT_PATH_CHARS:,} characters")
        if any(_PPTX_OBJECT_PATH_RE.fullmatch(value) is None for value in values):
            raise ValueError("paths must be exact stable PPTX object paths returned by office_inspect")
        return values

    @field_validator("kinds")
    @classmethod
    def validate_kinds(
        cls,
        values: list[PptxObjectKind] | None,
    ) -> list[PptxObjectKind] | None:
        if values is not None and len(set(values)) != len(values):
            raise ValueError("kinds must not contain duplicates")
        return values

    @field_validator("name_equals")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("name_equals must be printable")
        return value

    @model_validator(mode="after")
    def require_filter(self) -> "PptxObjectSelector":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("PPTX object selector must define at least one filter")
        return self


class PptxTextReplacement(BaseModel):
    """Replace paragraph-local literal text in exact stable PPTX shapes."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["replace_pptx_text"] = "replace_pptx_text"
    paths: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description=("Exact authored-ID shape paths returned by office_inspect"),
    )
    find: str = Field(..., min_length=1, max_length=4_000)
    replace: str = Field(..., max_length=4_000)
    occurrence: Literal["first", "all"] = "all"
    require_match: bool = True

    @field_validator("paths")
    @classmethod
    def validate_stable_shape_paths(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("paths must not contain duplicates")
        if any(len(value) > _MAX_PPTX_OBJECT_PATH_CHARS for value in values):
            raise ValueError(f"paths may contain at most {_MAX_PPTX_OBJECT_PATH_CHARS:,} characters")
        for value in values:
            if _PPTX_OBJECT_PATH_RE.fullmatch(value) is None:
                raise ValueError("paths must be exact PPTX object paths returned by office_inspect")
            segments = value.split("/")[2:]
            if not segments or segments[-1].partition("[")[0] != "shape":
                raise ValueError("PPTX text replacement targets shapes only")
            if any("[@id=" not in segment for segment in segments):
                raise ValueError("PPTX text replacement requires authored-ID stable paths")
        return values

    @field_validator("find", "replace")
    @classmethod
    def validate_literal_text(cls, value: str) -> str:
        if any(character in value for character in ("\r", "\n", "\t")):
            raise ValueError("PPTX literal replacement does not accept tabs or line breaks")
        if any(not (character == "\u0009" or character == "\u000a" or character == "\u000d" or "\u0020" <= character <= "\ud7ff" or "\ue000" <= character <= "\ufffd" or "\U00010000" <= character <= "\U0010ffff") for character in value):
            raise ValueError("PPTX literal replacement contains invalid XML text")
        return value


class PptxParagraphTarget(BaseModel):
    """One exact paragraph target under an authored-ID shape path."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        max_length=_MAX_PPTX_OBJECT_PATH_CHARS,
        description="Exact paragraph path returned by formatting-enabled PPTX inspection",
    )
    expected_text: str = Field(
        ...,
        max_length=4_000,
        description=("Exact paragraph text from the original inspected presentation, used to reject a stale positional path"),
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if _PPTX_STABLE_PARAGRAPH_PATH_RE.fullmatch(value) is None:
            raise ValueError("path must be an exact PPTX paragraph path under an authored-ID shape")
        return value

    @field_validator("expected_text")
    @classmethod
    def validate_expected_text(cls, value: str) -> str:
        return _validate_pptx_expected_text(value)


class PptxShapeTarget(BaseModel):
    """One exact authored-ID shape target with an authored-name stale guard."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        max_length=_MAX_PPTX_OBJECT_PATH_CHARS,
        description="Exact authored-ID shape path returned by office_inspect",
    )
    expected_name: str | None = Field(
        ...,
        max_length=256,
        description="Exact object name, including null or empty, from the original inspection",
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if _PPTX_STABLE_SHAPE_PATH_RE.fullmatch(value) is None:
            raise ValueError("path must be an exact authored-ID PPTX shape path")
        return value

    @field_validator("expected_name")
    @classmethod
    def validate_expected_name(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("expected_name must be printable")
        return value


class PptxSlideTarget(BaseModel):
    """One exact slide target with a package-part stale guard."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        max_length=32,
        description="Exact slide path returned by office_inspect",
    )
    expected_part_name: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Exact slide part_name from the original inspection",
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if _PPTX_SLIDE_PATH_RE.fullmatch(value) is None:
            raise ValueError("path must be an exact PPTX slide path")
        return value

    @field_validator("expected_part_name")
    @classmethod
    def validate_expected_part_name(cls, value: str) -> str:
        if not value.startswith("ppt/slides/") or not value.endswith(".xml") or "\\" in value or "//" in value or any(part in {"", ".", ".."} for part in value.split("/")) or any(ord(char) < 32 for char in value):
            raise ValueError("expected_part_name must be an inspected PPTX slide part")
        return value


class PptxPictureTarget(BaseModel):
    """One exact authored-ID picture with name and source-digest guards."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        max_length=_MAX_PPTX_OBJECT_PATH_CHARS,
        description="Exact authored-ID picture path returned by office_inspect",
    )
    expected_name: str | None = Field(
        ...,
        max_length=256,
        description="Exact object name, including null or empty, from the original inspection",
    )
    expected_source_sha256: str = Field(
        ...,
        pattern=r"^[0-9a-f]{64}$",
        description="Exact lowercase source SHA-256 returned by the original inspection",
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if _PPTX_STABLE_PICTURE_PATH_RE.fullmatch(value) is None:
            raise ValueError("path must be an exact authored-ID PPTX picture path")
        return value

    @field_validator("expected_name")
    @classmethod
    def validate_expected_name(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("expected_name must be printable")
        return value


class PptxLineTarget(BaseModel):
    """One exact authored-ID shape or connector line target."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        max_length=_MAX_PPTX_OBJECT_PATH_CHARS,
        description="Exact authored-ID shape or connector path returned by office_inspect",
    )
    expected_name: str | None = Field(
        ...,
        max_length=256,
        description="Exact object name, including null or empty, from the original inspection",
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if _PPTX_STABLE_LINE_PATH_RE.fullmatch(value) is None:
            raise ValueError("path must be an exact authored-ID PPTX shape or connector path")
        return value

    @field_validator("expected_name")
    @classmethod
    def validate_expected_name(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("expected_name must be printable")
        return value


class PptxRunTarget(BaseModel):
    """One exact text-run target under an authored-ID shape path."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        max_length=_MAX_PPTX_OBJECT_PATH_CHARS,
        description="Exact run path returned by formatting-enabled PPTX inspection",
    )
    expected_text: str = Field(
        ...,
        max_length=4_000,
        description=("Exact run text from the original inspected presentation, used to reject a stale positional path"),
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if _PPTX_STABLE_RUN_PATH_RE.fullmatch(value) is None:
            raise ValueError("path must be an exact PPTX run path under an authored-ID shape")
        return value

    @field_validator("expected_text")
    @classmethod
    def validate_expected_text(cls, value: str) -> str:
        return _validate_pptx_expected_text(value)


class PptxParagraphSelector(BaseModel):
    """Exact PPTX paragraph targets; this selector accepts only ``targets``."""

    model_config = ConfigDict(extra="forbid")

    targets: list[PptxParagraphTarget] = Field(..., min_length=1, max_length=100)

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[PptxParagraphTarget]) -> list[PptxParagraphTarget]:
        paths = [target.path for target in values]
        if len(set(paths)) != len(paths):
            raise ValueError("paragraph target paths must not contain duplicates")
        return values


class PptxRunSelector(BaseModel):
    """Exact PPTX text-run targets; this selector accepts only ``targets``."""

    model_config = ConfigDict(extra="forbid")

    targets: list[PptxRunTarget] = Field(..., min_length=1, max_length=200)

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[PptxRunTarget]) -> list[PptxRunTarget]:
        paths = [target.path for target in values]
        if len(set(paths)) != len(paths):
            raise ValueError("run target paths must not contain duplicates")
        return values


class PptxShapeSelector(BaseModel):
    """Exact authored-ID PPTX shape targets; this selector accepts only ``targets``."""

    model_config = ConfigDict(extra="forbid")

    targets: list[PptxShapeTarget] = Field(..., min_length=1, max_length=100)

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[PptxShapeTarget]) -> list[PptxShapeTarget]:
        paths = [target.path for target in values]
        if len(set(paths)) != len(paths):
            raise ValueError("shape target paths must not contain duplicates")
        return values


class PptxSlideSelector(BaseModel):
    """Exact PPTX slide targets; this selector accepts only ``targets``."""

    model_config = ConfigDict(extra="forbid")

    targets: list[PptxSlideTarget] = Field(..., min_length=1, max_length=50)

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[PptxSlideTarget]) -> list[PptxSlideTarget]:
        paths = [target.path for target in values]
        if len(set(paths)) != len(paths):
            raise ValueError("slide target paths must not contain duplicates")
        return values


class PptxPictureSelector(BaseModel):
    """Exact authored-ID PPTX pictures; this selector accepts only ``targets``."""

    model_config = ConfigDict(extra="forbid")

    targets: list[PptxPictureTarget] = Field(..., min_length=1, max_length=100)

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[PptxPictureTarget]) -> list[PptxPictureTarget]:
        paths = [target.path for target in values]
        if len(set(paths)) != len(paths):
            raise ValueError("picture target paths must not contain duplicates")
        return values


class PptxLineSelector(BaseModel):
    """Exact authored-ID shape or connector targets; this selector accepts only ``targets``."""

    model_config = ConfigDict(extra="forbid")

    targets: list[PptxLineTarget] = Field(..., min_length=1, max_length=100)

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: list[PptxLineTarget]) -> list[PptxLineTarget]:
        paths = [target.path for target in values]
        if len(set(paths)) != len(paths):
            raise ValueError("line target paths must not contain duplicates")
        return values


class PptxRunFormatting(BaseModel):
    """Direct DrawingML formatting allowlist for existing text runs."""

    model_config = ConfigDict(extra="forbid")

    bold: bool | None = None
    italic: bool | None = None
    underline: PptxUnderlineStyle | None = None
    strike: PptxStrikeStyle | None = None
    color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    font: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Latin and East Asian font; complex-script metadata is preserved",
    )
    font_latin: str | None = Field(default=None, min_length=1, max_length=100)
    font_east_asia: str | None = Field(default=None, min_length=1, max_length=100)
    font_complex_script: str | None = Field(default=None, min_length=1, max_length=100)
    font_size: float | None = Field(default=None, ge=1, le=400)

    @field_validator(
        "font",
        "font_latin",
        "font_east_asia",
        "font_complex_script",
    )
    @classmethod
    def normalize_font(cls, value: str | None) -> str | None:
        return _normalize_font_name(value)

    @field_validator("font_size")
    @classmethod
    def validate_half_points(cls, value: float | None) -> float | None:
        return _validate_half_points(value)

    @model_validator(mode="after")
    def require_property(self) -> "PptxRunFormatting":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("PPTX run formatting must define at least one property")
        if self.font is not None and any(value is not None for value in (self.font_latin, self.font_east_asia)):
            raise ValueError("font cannot be combined with explicit Latin or East Asian font slots")
        return self


class PptxParagraphFormatting(BaseModel):
    """Direct DrawingML formatting allowlist for existing paragraphs."""

    model_config = ConfigDict(extra="forbid")

    alignment: ParagraphAlignment | None = None
    space_before: float | None = Field(default=None, ge=0, le=1584)
    space_after: float | None = Field(default=None, ge=0, le=1584)
    line_spacing_points: float | None = Field(default=None, ge=0, le=1584)
    line_spacing_percent: float | None = Field(default=None, ge=1, le=1000)

    @field_validator("space_before", "space_after", "line_spacing_points")
    @classmethod
    def validate_hundredth_points(cls, value: float | None) -> float | None:
        return _validate_hundredth_points(value)

    @field_validator("line_spacing_percent")
    @classmethod
    def validate_thousandth_percent(cls, value: float | None) -> float | None:
        return _validate_thousandth_percent(value)

    @model_validator(mode="after")
    def require_property(self) -> "PptxParagraphFormatting":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("PPTX paragraph formatting must define at least one property")
        if self.line_spacing_points is not None and self.line_spacing_percent is not None:
            raise ValueError("line_spacing_points and line_spacing_percent are mutually exclusive")
        return self


class PptxGradientStopFormatting(BaseModel):
    """One RGB stop in a direct gradient."""

    model_config = ConfigDict(extra="forbid")

    position_percent: float = Field(ge=0, le=100)
    color: str = Field(pattern=r"^#?[0-9A-Fa-f]{6}$")
    opacity_percent: float | None = Field(default=None, ge=0, le=100)

    @field_validator("position_percent", "opacity_percent")
    @classmethod
    def validate_percent(cls, value: float | None) -> float | None:
        return _validate_thousandth_percent(value)


class PptxLinearGradientFormatting(BaseModel):
    """Explicit DrawingML linear-gradient geometry."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["linear"] = "linear"
    angle_degrees: float = Field(ge=0, lt=360)
    scaled: bool

    @field_validator("angle_degrees")
    @classmethod
    def validate_angle(cls, value: float) -> float:
        if abs(value * 60_000 - round(value * 60_000)) > 1e-8:
            raise ValueError("PPTX gradient angles must use 1/60000-degree increments")
        return value


class PptxGradientRectangleFormatting(BaseModel):
    """Explicit bounded focus rectangle for a radial path gradient."""

    model_config = ConfigDict(extra="forbid")

    left_percent: float = Field(ge=0, le=100)
    top_percent: float = Field(ge=0, le=100)
    right_percent: float = Field(ge=0, le=100)
    bottom_percent: float = Field(ge=0, le=100)

    @field_validator(
        "left_percent",
        "top_percent",
        "right_percent",
        "bottom_percent",
    )
    @classmethod
    def validate_percent(cls, value: float) -> float:
        _validate_thousandth_percent(value)
        return value

    @model_validator(mode="after")
    def validate_focus(self) -> "PptxGradientRectangleFormatting":
        horizontal = round((self.left_percent + self.right_percent) * 1_000)
        vertical = round((self.top_percent + self.bottom_percent) * 1_000)
        if horizontal != 100_000 or vertical != 100_000:
            raise ValueError("PPTX radial gradient focus edges must sum to 100 percent on each axis")
        return self


class PptxImageCropFormatting(BaseModel):
    """Explicit source-image crop percentages for a stretched shape fill."""

    model_config = ConfigDict(extra="forbid")

    left_percent: float = Field(ge=0, le=100)
    top_percent: float = Field(ge=0, le=100)
    right_percent: float = Field(ge=0, le=100)
    bottom_percent: float = Field(ge=0, le=100)

    @field_validator(
        "left_percent",
        "top_percent",
        "right_percent",
        "bottom_percent",
    )
    @classmethod
    def validate_percent(cls, value: float) -> float:
        _validate_thousandth_percent(value)
        return value

    @model_validator(mode="after")
    def validate_visible_area(self) -> "PptxImageCropFormatting":
        horizontal = round((self.left_percent + self.right_percent) * 1_000)
        vertical = round((self.top_percent + self.bottom_percent) * 1_000)
        if horizontal >= 100_000 or vertical >= 100_000:
            raise ValueError("PPTX image crop must leave a visible area on each axis")
        return self


class PptxImageTileFormatting(BaseModel):
    """Explicit DrawingML tile framing for an embedded shape image."""

    model_config = ConfigDict(extra="forbid")

    offset_x_emu: int = Field(ge=-2_147_483_648, le=2_147_483_647)
    offset_y_emu: int = Field(ge=-2_147_483_648, le=2_147_483_647)
    scale_x_percent: float = Field(ge=1, le=500)
    scale_y_percent: float = Field(ge=1, le=500)
    alignment: PptxImageTileAlignment
    flip: PptxImageTileFlip

    @field_validator("scale_x_percent", "scale_y_percent")
    @classmethod
    def validate_scale(cls, value: float) -> float:
        _validate_thousandth_percent(value)
        return value


class PptxPathGradientFormatting(BaseModel):
    """Explicit corpus-verified radial DrawingML path geometry."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["path"] = "path"
    path: Literal["circle"] = "circle"
    fill_to_rectangle: PptxGradientRectangleFormatting


PptxGradientGeometryFormatting = Annotated[
    PptxLinearGradientFormatting | PptxPathGradientFormatting,
    Field(discriminator="type"),
]


class PptxShapeFillFormatting(BaseModel):
    """Direct solid, no-fill, RGB gradient/pattern, or embedded image formatting."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["solid", "none", "gradient", "pattern", "image"]
    color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    stops: list[PptxGradientStopFormatting] | None = Field(
        default=None,
        min_length=2,
        max_length=32,
    )
    geometry: PptxGradientGeometryFormatting | None = None
    rotate_with_shape: bool | None = None
    preset: PptxPresetPattern | None = None
    foreground_color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    background_color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    image_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=1_024,
        description=("Absolute /mnt/user-data path to an embedded PNG or baseline JPEG source image"),
    )
    mode: PptxImageFillMode | None = Field(
        default=None,
        description="Image framing mode; omitted image mode preserves stretch compatibility",
    )
    crop: PptxImageCropFormatting | None = None
    tile: PptxImageTileFormatting | None = None

    @model_validator(mode="after")
    def validate_fill(self) -> "PptxShapeFillFormatting":
        gradient_fields = (self.stops, self.geometry, self.rotate_with_shape)
        pattern_fields = (self.preset, self.foreground_color, self.background_color)
        image_fields = (self.image_path, self.mode, self.crop, self.tile)
        if self.type == "solid":
            if self.color is None:
                raise ValueError("solid PPTX fill requires color")
            if any(value is not None for value in (*gradient_fields, *pattern_fields, *image_fields)):
                raise ValueError("solid PPTX fill does not accept gradient, pattern, or image properties")
        elif self.type == "none":
            if self.color is not None or any(value is not None for value in (*gradient_fields, *pattern_fields, *image_fields)):
                raise ValueError("none PPTX fill does not accept color, gradient, pattern, or image properties")
        elif self.type == "gradient":
            if self.color is not None or any(value is not None for value in (*pattern_fields, *image_fields)):
                raise ValueError("gradient PPTX fill does not accept solid, pattern, or image properties")
            if self.stops is None or self.geometry is None or self.rotate_with_shape is None:
                raise ValueError("gradient PPTX fill requires stops, geometry, and rotate_with_shape")
            positions = [stop.position_percent for stop in self.stops]
            if any(current <= previous for previous, current in zip(positions, positions[1:])):
                raise ValueError("PPTX gradient stop positions must be strictly increasing")
        elif self.type == "pattern":
            if self.color is not None or any(value is not None for value in (*gradient_fields, *image_fields)):
                raise ValueError("pattern PPTX fill does not accept solid or gradient properties, including image properties")
            if any(value is None for value in pattern_fields):
                raise ValueError("pattern PPTX fill requires preset, foreground_color, and background_color")
        else:
            if self.color is not None or any(value is not None for value in (self.stops, self.geometry, *pattern_fields)):
                raise ValueError("image PPTX fill does not accept solid, gradient, or pattern properties")
            if self.image_path is None or self.rotate_with_shape is None:
                raise ValueError("image PPTX fill requires image_path and rotate_with_shape")
            mode = self.mode or "stretch"
            if mode == "stretch" and self.tile is not None:
                raise ValueError("stretch PPTX image fill does not accept tile properties")
            if mode == "tile":
                if self.tile is None:
                    raise ValueError("tile PPTX image fill requires explicit tile properties")
                if self.crop is not None:
                    raise ValueError("tile PPTX image fill does not support crop")
            if mode == "center":
                if self.tile is not None:
                    raise ValueError("center PPTX image fill uses canonical framing and does not accept tile properties")
                if self.crop is not None:
                    raise ValueError("center PPTX image fill does not support crop")
        return self


class PptxSlideBackgroundFormatting(BaseModel):
    """Direct slide-only background formatting verified by the native corpus."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "solid", "gradient", "image"]
    color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    stops: list[PptxGradientStopFormatting] | None = Field(
        default=None,
        min_length=2,
        max_length=32,
    )
    geometry: PptxLinearGradientFormatting | None = None
    image_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=1_024,
        description="Absolute /mnt/user-data path to an embedded PNG or baseline JPEG source image",
    )
    mode: PptxImageFillMode | None = Field(
        default=None,
        description="Slide image framing mode; omitted mode uses stretch",
    )
    tile: PptxImageTileFormatting | None = None

    @model_validator(mode="after")
    def validate_background(self) -> "PptxSlideBackgroundFormatting":
        gradient_fields = (self.stops, self.geometry)
        image_fields = (self.image_path, self.mode, self.tile)
        if self.type == "none":
            if self.color is not None or any(value is not None for value in (*gradient_fields, *image_fields)):
                raise ValueError("none PPTX slide background does not accept fill properties")
        elif self.type == "solid":
            if self.color is None:
                raise ValueError("solid PPTX slide background requires color")
            if any(value is not None for value in (*gradient_fields, *image_fields)):
                raise ValueError("solid PPTX slide background does not accept gradient or image properties")
        elif self.type == "gradient":
            if self.color is not None or any(value is not None for value in image_fields):
                raise ValueError("gradient PPTX slide background does not accept solid or image properties")
            if self.stops is None or self.geometry is None:
                raise ValueError("gradient PPTX slide background requires stops and linear geometry")
            positions = [stop.position_percent for stop in self.stops]
            if any(current <= previous for previous, current in zip(positions, positions[1:])):
                raise ValueError("PPTX gradient stop positions must be strictly increasing")
        else:
            if self.color is not None or any(value is not None for value in gradient_fields):
                raise ValueError("image PPTX slide background does not accept solid or gradient properties")
            if self.image_path is None:
                raise ValueError("image PPTX slide background requires image_path")
            mode = self.mode or "stretch"
            if mode == "stretch" and self.tile is not None:
                raise ValueError("stretch PPTX slide background does not accept tile properties")
            if mode == "tile" and self.tile is None:
                raise ValueError("tile PPTX slide background requires explicit tile properties")
            if mode == "center" and self.tile is not None:
                raise ValueError("center PPTX slide background uses canonical framing and does not accept tile properties")
        return self


class PptxShapeLineFormatting(BaseModel):
    """Bounded direct fill, width, cap, preset dash, and join formatting."""

    model_config = ConfigDict(extra="forbid")

    fill: PptxShapeFillFormatting | None = None
    width_points: float | None = Field(
        default=None,
        ge=0,
        le=1584,
        description="Direct line width in points",
    )
    cap: PptxLineCap | None = None
    dash: PptxPresetLineDash | None = None
    join: PptxLineJoin | None = None
    miter_limit_percent: float | None = Field(
        default=None,
        ge=0,
        le=2_147_483.647,
        description="Miter limit in percent; requires join=miter",
    )

    @field_validator("width_points")
    @classmethod
    def validate_width(cls, value: float | None) -> float | None:
        return _validate_hundredth_points(value)

    @field_validator("miter_limit_percent")
    @classmethod
    def validate_miter_limit(cls, value: float | None) -> float | None:
        return _validate_thousandth_percent(value)

    @model_validator(mode="after")
    def require_property(self) -> "PptxShapeLineFormatting":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("PPTX line formatting must define at least one property")
        if self.miter_limit_percent is not None and self.join != "miter":
            raise ValueError("miter_limit_percent requires join=miter")
        if self.fill is not None and self.fill.type == "pattern":
            raise ValueError("PPTX line fills do not support pattern fills")
        if self.fill is not None and self.fill.type == "image":
            raise ValueError("PPTX line fills do not support image fills")
        if self.fill is not None and self.fill.type == "gradient" and isinstance(self.fill.geometry, PptxPathGradientFormatting):
            raise ValueError("PPTX line fills support linear gradients only")
        return self


class PptxLineEndFormatting(BaseModel):
    """Typed type and independent size fields for one direct line end."""

    model_config = ConfigDict(extra="forbid")

    type: PptxLineEndType | None = None
    width: PptxLineEndSize | None = None
    length: PptxLineEndSize | None = None

    @model_validator(mode="after")
    def validate_line_end(self) -> "PptxLineEndFormatting":
        if self.type is None and self.width is None and self.length is None:
            raise ValueError("PPTX line-end formatting must define at least one property")
        if self.type == "none" and (self.width is not None or self.length is not None):
            raise ValueError("PPTX line-end type none does not accept width or length")
        return self


class PptxLineFormatting(PptxShapeLineFormatting):
    """Typed direct line formatting shared by authored shapes and connectors."""

    compound: PptxLineCompound | None = None
    alignment: PptxLineAlignment | None = None
    head_end: PptxLineEndFormatting | None = None
    tail_end: PptxLineEndFormatting | None = None


class PptxTextBoxFormatting(BaseModel):
    """Direct text-box inset and vertical-anchor formatting."""

    model_config = ConfigDict(extra="forbid")

    margin_left: float | None = Field(default=None, ge=-4032, le=4032, description="Left text inset in points")
    margin_top: float | None = Field(default=None, ge=-4032, le=4032, description="Top text inset in points")
    margin_right: float | None = Field(default=None, ge=-4032, le=4032, description="Right text inset in points")
    margin_bottom: float | None = Field(default=None, ge=-4032, le=4032, description="Bottom text inset in points")
    vertical_anchor: PptxVerticalAnchor | None = None

    @field_validator(
        "margin_left",
        "margin_top",
        "margin_right",
        "margin_bottom",
    )
    @classmethod
    def validate_margins(cls, value: float | None) -> float | None:
        return _validate_hundredth_points(value)

    @model_validator(mode="after")
    def require_property(self) -> "PptxTextBoxFormatting":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("PPTX text-box formatting must define at least one property")
        return self


class PptxPresetGeometryFormatting(BaseModel):
    """Corpus-bounded preset geometry for an existing authored shape."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["preset"] = "preset"
    preset: PptxPresetGeometry


class PptxShapeFormatting(BaseModel):
    """Direct DrawingML formatting allowlist for existing authored shapes."""

    model_config = ConfigDict(extra="forbid")

    fill: PptxShapeFillFormatting | None = None
    geometry: PptxPresetGeometryFormatting | None = None
    line: PptxShapeLineFormatting | None = None
    text_box: PptxTextBoxFormatting | None = None

    @model_validator(mode="after")
    def require_property(self) -> "PptxShapeFormatting":
        if self.fill is None and self.geometry is None and self.line is None and self.text_box is None:
            raise ValueError("PPTX shape formatting must define at least one property")
        return self


class PptxRunFormatOperation(BaseModel):
    """PPTX run formatting with only ``type``, ``runs``, and ``formatting``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["format_pptx_runs"] = "format_pptx_runs"
    runs: PptxRunSelector = Field(description=("PPTX-only selector containing exactly targets; do not add contains_text, occurrence, or require_match"))
    formatting: PptxRunFormatting

    @field_validator("runs", mode="before")
    @classmethod
    def normalize_inert_selector_fields(cls, value: object) -> object:
        return _normalize_pptx_exact_selector_compat(value)


class PptxParagraphFormatOperation(BaseModel):
    """PPTX paragraph formatting with only ``type``, ``paragraphs``, and ``formatting``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["format_pptx_paragraphs"] = "format_pptx_paragraphs"
    paragraphs: PptxParagraphSelector = Field(description=("PPTX-only selector containing exactly targets; do not add contains_text, occurrence, or require_match"))
    formatting: PptxParagraphFormatting

    @field_validator("paragraphs", mode="before")
    @classmethod
    def normalize_inert_selector_fields(cls, value: object) -> object:
        return _normalize_pptx_exact_selector_compat(value)


class PptxShapeFormatOperation(BaseModel):
    """PPTX shape formatting with only ``type``, ``shapes``, and ``formatting``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["format_pptx_shapes"] = "format_pptx_shapes"
    shapes: PptxShapeSelector = Field(description=("PPTX-only selector containing exactly targets; do not add contains_text, occurrence, or require_match"))
    formatting: PptxShapeFormatting

    @field_validator("shapes", mode="before")
    @classmethod
    def normalize_inert_selector_fields(cls, value: object) -> object:
        return _normalize_pptx_exact_selector_compat(value)


class PptxLineFormatOperation(BaseModel):
    """PPTX line formatting with only ``type``, ``lines``, and ``formatting``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["format_pptx_lines"] = "format_pptx_lines"
    lines: PptxLineSelector = Field(description=("PPTX-only selector containing exactly targets; do not add contains_text, occurrence, or require_match"))
    formatting: PptxLineFormatting

    @field_validator("lines", mode="before")
    @classmethod
    def normalize_inert_selector_fields(cls, value: object) -> object:
        return _normalize_pptx_exact_selector_compat(value)


class PptxSlideBackgroundFormatOperation(BaseModel):
    """PPTX slide background formatting with only ``type``, ``slides``, and ``formatting``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["format_pptx_slide_backgrounds"] = "format_pptx_slide_backgrounds"
    slides: PptxSlideSelector = Field(
        description=("PPTX-only selector containing exactly targets with part-name guards; do not add occurrence or require_match"),
    )
    formatting: PptxSlideBackgroundFormatting

    @field_validator("slides", mode="before")
    @classmethod
    def normalize_inert_selector_fields(cls, value: object) -> object:
        return _normalize_pptx_exact_selector_compat(value)


class PptxPictureSourceReplacementOperation(BaseModel):
    """PPTX picture source replacement with only ``type``, ``pictures``, and ``image_path``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["replace_pptx_picture_sources"] = "replace_pptx_picture_sources"
    pictures: PptxPictureSelector = Field(
        description=("PPTX-only selector containing exactly targets with name and source-digest guards; do not add occurrence or require_match"),
    )
    image_path: str = Field(
        ...,
        min_length=1,
        max_length=1_024,
        description="Absolute /mnt/user-data path to the replacement PNG or baseline JPEG",
    )

    @field_validator("pictures", mode="before")
    @classmethod
    def normalize_inert_selector_fields(cls, value: object) -> object:
        return _normalize_pptx_exact_selector_compat(value)


PptxEditOperation = Annotated[
    PptxTextReplacement | PptxRunFormatOperation | PptxParagraphFormatOperation | PptxShapeFormatOperation | PptxLineFormatOperation | PptxSlideBackgroundFormatOperation | PptxPictureSourceReplacementOperation,
    Field(discriminator="type"),
]


class DocxTextReplacement(BaseModel):
    """Replace literal text inside DOCX paragraph text nodes."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["replace_text"] = "replace_text"
    find: str = Field(..., min_length=1, description="Literal text to find inside a paragraph")
    replace: str = Field(..., description="Replacement text; an empty string deletes the match")
    occurrence: Literal["first", "all"] = Field(
        default="all",
        description="Replace the first match in the document or every non-overlapping match",
    )
    require_match: bool = Field(
        default=True,
        description="Fail the complete edit transaction when this operation matches no text",
    )


class DocxParagraphSelector(BaseModel):
    """Typed, conjunctive selector over inspectable body paragraphs."""

    model_config = ConfigDict(extra="forbid")

    paragraph_indices: list[ParagraphIndex] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="1-based paragraph indices returned by office_inspect",
    )
    contains_text: str | None = Field(
        default=None,
        min_length=1,
        max_length=1_000,
        description="Case-sensitive literal substring required in paragraph text",
    )
    style: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Case-insensitive OOXML paragraph style ID",
    )
    context: Literal["body", "table_cell"] | None = None
    alignment: ParagraphAlignment | None = Field(
        default=None,
        description="Direct paragraph alignment; absent alignment does not match",
    )

    @model_validator(mode="after")
    def require_filter(self) -> "DocxParagraphSelector":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("Paragraph selector must define at least one filter")
        if self.paragraph_indices and len(set(self.paragraph_indices)) != len(self.paragraph_indices):
            raise ValueError("paragraph_indices must not contain duplicates")
        return self


class DocxRunSelector(BaseModel):
    """Typed, conjunctive selector over visible text-bearing runs."""

    model_config = ConfigDict(extra="forbid")

    run_indices: list[RunIndex] | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="1-based run indices within each selected paragraph",
    )
    contains_text: str | None = Field(
        default=None,
        min_length=1,
        max_length=1_000,
        description="Case-sensitive literal substring required in one run",
    )
    bold: bool | None = Field(default=None, description="Match direct bold state; absent formatting counts as false")
    italic: bool | None = Field(default=None, description="Match direct italic state; absent formatting counts as false")
    strike: bool | None = Field(default=None, description="Match direct strike state; absent formatting counts as false")
    double_strike: bool | None = Field(default=None, description="Match direct double-strike state; absent formatting counts as false")
    all_caps: bool | None = Field(default=None, description="Match direct all-caps state; absent formatting counts as false")
    small_caps: bool | None = Field(default=None, description="Match direct small-caps state; absent formatting counts as false")
    underline: UnderlineStyle | None = Field(
        default=None,
        description="Match direct underline style; none also matches an absent underline",
    )
    color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    highlight: HighlightColor | None = Field(
        default=None,
        description="Match direct highlight; none also matches an absent highlight",
    )
    font: str | None = Field(default=None, min_length=1, max_length=100)
    font_ascii: str | None = Field(default=None, min_length=1, max_length=100)
    font_high_ansi: str | None = Field(default=None, min_length=1, max_length=100)
    font_east_asia: str | None = Field(default=None, min_length=1, max_length=100)
    font_complex_script: str | None = Field(default=None, min_length=1, max_length=100)
    font_size: float | None = Field(default=None, ge=1, le=400)
    font_size_complex_script: float | None = Field(default=None, ge=1, le=400)
    vertical_alignment: VerticalAlignment | None = None

    @field_validator(
        "font",
        "font_ascii",
        "font_high_ansi",
        "font_east_asia",
        "font_complex_script",
    )
    @classmethod
    def normalize_font(cls, value: str | None) -> str | None:
        return _normalize_font_name(value)

    @field_validator("font_size", "font_size_complex_script")
    @classmethod
    def validate_half_points(cls, value: float | None) -> float | None:
        return _validate_half_points(value)

    @model_validator(mode="after")
    def require_filter(self) -> "DocxRunSelector":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("Run selector must define at least one filter")
        if self.run_indices and len(set(self.run_indices)) != len(self.run_indices):
            raise ValueError("run_indices must not contain duplicates")
        return self


class DocxRunFormatting(BaseModel):
    """Small direct-formatting allowlist for DOCX text runs."""

    model_config = ConfigDict(extra="forbid")

    bold: bool | None = None
    italic: bool | None = None
    underline: UnderlineStyle | None = None
    underline_color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    strike: bool | None = None
    double_strike: bool | None = None
    all_caps: bool | None = None
    small_caps: bool | None = None
    color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    highlight: HighlightColor | None = None
    font: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="ASCII, High ANSI, and East Asian font; complex-script metadata is preserved",
    )
    font_ascii: str | None = Field(default=None, min_length=1, max_length=100)
    font_high_ansi: str | None = Field(default=None, min_length=1, max_length=100)
    font_east_asia: str | None = Field(default=None, min_length=1, max_length=100)
    font_complex_script: str | None = Field(default=None, min_length=1, max_length=100)
    font_size: float | None = Field(
        default=None,
        ge=1,
        le=400,
        description="Primary font size in 0.5-point increments; complex-script size is preserved",
    )
    font_size_complex_script: float | None = Field(
        default=None,
        ge=1,
        le=400,
        description="Complex-script font size in 0.5-point increments",
    )
    vertical_alignment: VerticalAlignment | None = None

    @field_validator(
        "font",
        "font_ascii",
        "font_high_ansi",
        "font_east_asia",
        "font_complex_script",
    )
    @classmethod
    def normalize_font(cls, value: str | None) -> str | None:
        return _normalize_font_name(value)

    @field_validator("font_size", "font_size_complex_script")
    @classmethod
    def validate_half_points(cls, value: float | None) -> float | None:
        return _validate_half_points(value)

    @model_validator(mode="after")
    def require_property(self) -> "DocxRunFormatting":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("Run formatting must define at least one property")
        if self.font is not None and any(value is not None for value in (self.font_ascii, self.font_high_ansi, self.font_east_asia)):
            raise ValueError("font cannot be combined with explicit ASCII, High ANSI, or East Asian font slots")
        if self.all_caps is True and self.small_caps is True:
            raise ValueError("all_caps and small_caps cannot both be true")
        return self


class DocxParagraphFormatting(BaseModel):
    """Small direct-formatting allowlist for DOCX paragraphs."""

    model_config = ConfigDict(extra="forbid")

    alignment: ParagraphAlignment | None = None
    space_before: float | None = Field(default=None, ge=0, le=1584)
    space_after: float | None = Field(default=None, ge=0, le=1584)
    left_indent: float | None = Field(default=None, ge=-1584, le=1584)
    right_indent: float | None = Field(default=None, ge=-1584, le=1584)
    first_line_indent: float | None = Field(default=None, ge=0, le=1584)
    hanging_indent: float | None = Field(default=None, ge=0, le=1584)
    keep_with_next: bool | None = None
    keep_lines: bool | None = None
    page_break_before: bool | None = None

    @field_validator(
        "space_before",
        "space_after",
        "left_indent",
        "right_indent",
        "first_line_indent",
        "hanging_indent",
    )
    @classmethod
    def validate_twentieth_points(cls, value: float | None) -> float | None:
        return _validate_twentieth_points(value)

    @model_validator(mode="after")
    def require_property(self) -> "DocxParagraphFormatting":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("Paragraph formatting must define at least one property")
        if self.first_line_indent is not None and self.hanging_indent is not None:
            raise ValueError("first_line_indent and hanging_indent are mutually exclusive")
        return self


class DocxRunFormatOperation(BaseModel):
    """Apply direct formatting to runs selected inside matching paragraphs."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["format_runs"] = "format_runs"
    paragraphs: DocxParagraphSelector
    runs: DocxRunSelector | None = Field(
        default=None,
        description="Optional run filter; omitted means every visible text-bearing run in each paragraph",
    )
    formatting: DocxRunFormatting
    occurrence: Literal["first", "all"] = "all"
    require_match: bool = True


class DocxParagraphFormatOperation(BaseModel):
    """Apply direct paragraph formatting to matching paragraphs."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["format_paragraphs"] = "format_paragraphs"
    paragraphs: DocxParagraphSelector
    formatting: DocxParagraphFormatting
    occurrence: Literal["first", "all"] = "all"
    require_match: bool = True


DocxEditOperation = Annotated[
    DocxTextReplacement | DocxRunFormatOperation | DocxParagraphFormatOperation,
    Field(discriminator="type"),
]


class XlsxCellSelector(BaseModel):
    """Typed, conjunctive selector over bounded worksheet ranges."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    sheet_name: str = Field(..., min_length=1, max_length=31)
    ranges: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="A1 cells or rectangular ranges on sheet_name; at most 10,000 cells total",
    )
    contains_text: str | None = Field(default=None, min_length=1, max_length=1_000)
    value_equals: str | int | float | bool | None = None
    has_formula: bool | None = None
    is_blank: bool | None = None
    data_type: XlsxCellDataType | None = None
    bold: bool | None = None
    italic: bool | None = None
    font_name: str | None = Field(default=None, min_length=1, max_length=100)
    font_size: float | None = Field(default=None, ge=1, le=409)
    font_color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    fill_color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    horizontal_alignment: XlsxHorizontalAlignment | None = None
    number_format: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("sheet_name")
    @classmethod
    def normalize_sheet_name(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("sheet_name must be a printable non-empty name")
        return value

    @field_validator("ranges")
    @classmethod
    def normalize_ranges(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        bounds: list[tuple[int, int, int, int]] = []
        for value in values:
            cell_range, cell_bounds = _normalize_xlsx_range(value)
            if cell_range in normalized:
                raise ValueError("ranges must not contain duplicates")
            normalized.append(cell_range)
            bounds.append(cell_bounds)
        selected_cells = _xlsx_range_union_cell_count(bounds)
        if selected_cells > _MAX_XLSX_SELECTED_CELLS:
            raise ValueError(f"ranges may select at most {_MAX_XLSX_SELECTED_CELLS:,} cells")
        return normalized

    @field_validator("font_name")
    @classmethod
    def normalize_font(cls, value: str | None) -> str | None:
        return _normalize_font_name(value)

    @field_validator("font_size")
    @classmethod
    def validate_half_points(cls, value: float | None) -> float | None:
        return _validate_half_points(value)


class XlsxCellFormatting(BaseModel):
    """Direct-formatting allowlist for worksheet cells."""

    model_config = ConfigDict(extra="forbid")

    bold: bool | None = None
    italic: bool | None = None
    strike: bool | None = None
    underline: XlsxUnderlineStyle | None = None
    font_name: str | None = Field(default=None, min_length=1, max_length=100)
    font_size: float | None = Field(default=None, ge=1, le=409)
    font_color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    fill_color: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")
    horizontal_alignment: XlsxHorizontalAlignment | None = None
    vertical_alignment: XlsxVerticalAlignment | None = None
    wrap_text: bool | None = None
    shrink_to_fit: bool | None = None
    text_rotation: int | None = Field(default=None, ge=0, le=180)
    indent: int | None = Field(default=None, ge=0, le=255)
    number_format: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("font_name")
    @classmethod
    def normalize_font(cls, value: str | None) -> str | None:
        return _normalize_font_name(value)

    @field_validator("font_size")
    @classmethod
    def validate_half_points(cls, value: float | None) -> float | None:
        return _validate_half_points(value)

    @field_validator("number_format")
    @classmethod
    def validate_number_format(cls, value: str | None) -> str | None:
        return _validate_xlsx_number_format(value)

    @model_validator(mode="after")
    def require_property(self) -> "XlsxCellFormatting":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("Cell formatting must define at least one property")
        return self


class XlsxCellFormatOperation(BaseModel):
    """Apply direct formatting to cells selected inside bounded ranges."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["format_cells"] = "format_cells"
    cells: XlsxCellSelector
    formatting: XlsxCellFormatting
    occurrence: Literal["first", "all"] = "all"
    require_match: bool = True


XlsxEditOperation = XlsxCellFormatOperation

OfficeEditOperation = Annotated[
    DocxTextReplacement
    | DocxRunFormatOperation
    | DocxParagraphFormatOperation
    | XlsxCellFormatOperation
    | PptxTextReplacement
    | PptxRunFormatOperation
    | PptxParagraphFormatOperation
    | PptxShapeFormatOperation
    | PptxLineFormatOperation
    | PptxSlideBackgroundFormatOperation
    | PptxPictureSourceReplacementOperation,
    Field(discriminator="type"),
]

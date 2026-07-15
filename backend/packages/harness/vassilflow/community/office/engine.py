"""Format dispatch for the VassilFlow Office engine."""

from typing import Any

from .docx import (
    edit_docx,
    inspect_docx,
    validate_docx,
    validate_docx_renderable,
)
from .errors import UnsupportedOfficeFormatError
from .models import OfficeEditOperation, PptxObjectSelector
from .pptx import edit_pptx, inspect_pptx, validate_pptx, validate_pptx_renderable
from .render import OfficeRenderResult, render_docx_pages, render_pptx_pages, render_xlsx_pages
from .xlsx import edit_xlsx, inspect_xlsx, validate_xlsx, validate_xlsx_renderable


class OfficeEngine:
    """Small format-neutral contract owned by VassilFlow."""

    def inspect(
        self,
        document: bytes,
        *,
        suffix: str,
        start_paragraph: int = 1,
        max_paragraphs: int = 100,
        include_runs: bool = False,
        sheet_name: str | None = None,
        cell_range: str | None = None,
        include_cell_styles: bool = False,
        start_slide: int = 1,
        max_slides: int = 20,
        include_pptx_formatting: bool = False,
        include_pptx_annotations: bool = False,
        include_pptx_dynamics: bool = False,
        include_pptx_media_gc_plan: bool = False,
        pptx_selector: PptxObjectSelector | None = None,
    ) -> dict[str, Any]:
        normalized_suffix = suffix.lower()
        if normalized_suffix == ".docx":
            return inspect_docx(
                document,
                start_paragraph=start_paragraph,
                max_paragraphs=max_paragraphs,
                include_runs=include_runs,
            )
        if normalized_suffix == ".xlsx":
            return inspect_xlsx(
                document,
                sheet_name=sheet_name,
                cell_range=cell_range,
                include_cell_styles=include_cell_styles,
            )
        if normalized_suffix == ".pptx":
            return inspect_pptx(
                document,
                start_slide=start_slide,
                max_slides=max_slides,
                include_formatting=include_pptx_formatting,
                include_annotations=include_pptx_annotations,
                include_dynamics=include_pptx_dynamics,
                include_media_gc_plan=include_pptx_media_gc_plan,
                selector=pptx_selector,
            )
        raise UnsupportedOfficeFormatError(f"Unsupported Office format: {suffix}")

    def edit(
        self,
        document: bytes,
        *,
        suffix: str,
        operations: list[OfficeEditOperation],
        image_assets: dict[str, bytes] | None = None,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        normalized_suffix = suffix.lower()
        if normalized_suffix == ".docx":
            if image_assets:
                raise UnsupportedOfficeFormatError("Image assets are supported only for PPTX edits")
            return edit_docx(document, operations)
        if normalized_suffix == ".xlsx":
            if image_assets:
                raise UnsupportedOfficeFormatError("Image assets are supported only for PPTX edits")
            return edit_xlsx(document, operations)
        if normalized_suffix == ".pptx":
            return edit_pptx(document, operations, image_assets=image_assets)
        raise UnsupportedOfficeFormatError(f"Unsupported Office format: {suffix}")

    def validate(self, document: bytes, *, suffix: str) -> dict[str, Any]:
        normalized_suffix = suffix.lower()
        if normalized_suffix == ".docx":
            return validate_docx(document)
        if normalized_suffix == ".xlsx":
            return validate_xlsx(document)
        if normalized_suffix == ".pptx":
            return validate_pptx(document)
        raise UnsupportedOfficeFormatError(f"Unsupported Office format: {suffix}")

    def render(
        self,
        document: bytes,
        *,
        suffix: str,
        start_page: int = 1,
        max_pages: int = 1,
        dpi: int = 120,
    ) -> OfficeRenderResult:
        normalized_suffix = suffix.lower()
        if normalized_suffix == ".docx":
            validate_docx_renderable(document)
            return render_docx_pages(
                document,
                start_page=start_page,
                max_pages=max_pages,
                dpi=dpi,
            )
        if normalized_suffix == ".xlsx":
            validate_xlsx_renderable(document)
            return render_xlsx_pages(
                document,
                start_page=start_page,
                max_pages=max_pages,
                dpi=dpi,
            )
        if normalized_suffix == ".pptx":
            validate_pptx_renderable(document)
            return render_pptx_pages(
                document,
                start_page=start_page,
                max_pages=max_pages,
                dpi=dpi,
            )
        raise UnsupportedOfficeFormatError(f"Unsupported Office format: {suffix}")


office_engine = OfficeEngine()

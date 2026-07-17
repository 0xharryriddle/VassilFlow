"""Typed client envelope for launching an Office selected-object run."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class OfficePptxObjectSelectionInput(BaseModel):
    """Optimistic identity guards for one object selected in Office preview."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pptx_object"] = "pptx_object"
    project_id: str = Field(pattern=r"^ofp_[0-9a-f]{32}$")
    revision_id: str = Field(pattern=r"^ofr_[0-9a-f]{32}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    slide_index: int = Field(ge=1, le=10_000)
    object_path: str = Field(min_length=1, max_length=1_024)
    object_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


def extract_office_selection_input(body: Any) -> OfficePptxObjectSelectionInput | None:
    """Read the direct API field or SDK-compatible runtime-context envelope."""

    direct = getattr(body, "office_selection", None)
    context = getattr(body, "context", None)
    raw_context = context.get("office_selection_request") if isinstance(context, dict) else None
    if raw_context is None:
        return direct
    try:
        contextual = OfficePptxObjectSelectionInput.model_validate(raw_context)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Office selection request",
        ) from exc
    if direct is not None and direct != contextual:
        raise HTTPException(
            status_code=400,
            detail="Conflicting Office selection requests",
        )
    return contextual

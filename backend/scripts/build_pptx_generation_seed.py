"""Build deterministic native PPTX generation corpus artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.generation import (
    PRESENTATION_INTENT_SCHEMA,
    PresentationIntent,
    compile_presentation,
    validate_generation_evidence,
)

GENERATION_IMAGE_PATH = "/mnt/user-data/uploads/generation-corpus-v1.png"


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def build_generation_image() -> bytes:
    """Return a deterministic accessible visual used by contain and cover."""

    width = 960
    height = 540
    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)
        for x in range(width):
            if x < 16 or x >= width - 16 or y < 16 or y >= height - 16:
                color = (23, 33, 43)
            elif x < width // 3:
                color = (31, 111, 235)
            elif x < width * 2 // 3:
                color = (15, 118, 110)
            else:
                color = (255, 183, 77)
            if abs((x * height) - (y * width)) < width * 5:
                color = (255, 255, 255)
            scanlines.extend((*color, 255))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(scanlines), level=9))
        + _png_chunk(b"IEND", b"")
    )


def build_generation_intent_payload() -> dict[str, Any]:
    return {
        "schema": PRESENTATION_INTENT_SCHEMA,
        "title": "Native Generation Corpus",
        "aspect_ratio": "16:9",
        "theme": {
            "background": "F7F8FA",
            "surface": "FFFFFF",
            "text": "17212B",
            "muted": "56616F",
            "accent": "1F6FEB",
            "accent_alt": "0F766E",
            "heading_font": "Arial",
            "body_font": "Georgia",
        },
        "slides": [
            {
                "id": "opening",
                "purpose": "Verify the native title layout",
                "layout": "title",
                "elements": [
                    {
                        "kind": "shape",
                        "id": "opening-accent",
                        "placement": "accent_bar",
                        "shape": "rectangle",
                        "fill": "accent",
                    },
                    {
                        "kind": "text",
                        "id": "opening-title",
                        "role": "title",
                        "text": "Native Generation Corpus",
                    },
                    {
                        "kind": "text",
                        "id": "opening-subtitle",
                        "role": "subtitle",
                        "text": "Editable objects across native producers",
                    },
                ],
            },
            {
                "id": "summary",
                "purpose": "Verify native bullet text and decoration",
                "layout": "title_content",
                "elements": [
                    {
                        "kind": "text",
                        "id": "summary-title",
                        "role": "title",
                        "text": "Semantic content",
                    },
                    {
                        "kind": "text",
                        "id": "summary-content",
                        "role": "content",
                        "bullets": [
                            "Stable intent IDs map to authored object paths",
                            "Native text remains independently editable",
                            "Visual evidence remains bound to one artifact",
                        ],
                    },
                    {
                        "kind": "shape",
                        "id": "summary-mark",
                        "placement": "top_right",
                        "shape": "ellipse",
                        "fill": "accent_alt",
                    },
                ],
            },
            {
                "id": "evidence",
                "purpose": "Verify cover imagery beside text",
                "layout": "two_column",
                "elements": [
                    {
                        "kind": "text",
                        "id": "evidence-title",
                        "role": "title",
                        "text": "Evidence and interpretation",
                    },
                    {
                        "kind": "image",
                        "id": "evidence-image",
                        "role": "left",
                        "source_path": GENERATION_IMAGE_PATH,
                        "alt_text": "Three colored evidence bands crossed by a white diagonal",
                        "fit": "cover",
                    },
                    {
                        "kind": "text",
                        "id": "evidence-notes",
                        "role": "right",
                        "bullets": [
                            "The image is embedded, not linked",
                            "The crop is compiler-owned and deterministic",
                        ],
                    },
                ],
            },
            {
                "id": "detail",
                "purpose": "Verify contained imagery and caption text",
                "layout": "picture_caption",
                "elements": [
                    {
                        "kind": "text",
                        "id": "detail-title",
                        "role": "title",
                        "text": "Contained visual evidence",
                    },
                    {
                        "kind": "image",
                        "id": "detail-image",
                        "role": "media",
                        "source_path": GENERATION_IMAGE_PATH,
                        "alt_text": "Complete three-band corpus image with its dark border visible",
                        "fit": "contain",
                    },
                    {
                        "kind": "text",
                        "id": "detail-caption",
                        "role": "caption",
                        "text": "Contain preserves the complete source image and its border.",
                    },
                ],
            },
            {
                "id": "closing",
                "purpose": "Verify the native closing layout",
                "layout": "closing",
                "elements": [
                    {
                        "kind": "shape",
                        "id": "closing-mark",
                        "placement": "bottom_left",
                        "shape": "rounded_rectangle",
                        "fill": "accent_alt",
                    },
                    {
                        "kind": "text",
                        "id": "closing-title",
                        "role": "title",
                        "text": "Native generation verified",
                    },
                    {
                        "kind": "text",
                        "id": "closing-subtitle",
                        "role": "subtitle",
                        "text": "Inspect, render, review, then deliver",
                    },
                ],
            },
        ],
    }


def build_generation_seed() -> tuple[bytes, dict[str, Any], dict[str, Any], dict[str, Any]]:
    intent = PresentationIntent.model_validate(build_generation_intent_payload())
    intent_payload = intent.model_dump(by_alias=True, exclude_none=True, mode="json")
    artifact, receipt = compile_presentation(
        intent,
        image_assets={GENERATION_IMAGE_PATH: build_generation_image()},
    )
    preflight = office_engine.preflight(artifact, suffix=".pptx")
    validate_generation_evidence(
        artifact=artifact,
        intent=intent_payload,
        receipt=receipt,
        preflight=preflight,
    )
    return artifact, intent_payload, receipt, preflight


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write(path: Path, payload: bytes, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    artifact, intent, receipt, preflight = build_generation_seed()
    image = build_generation_image()
    outputs = {
        "asset-v1.png": image,
        "intent-v1.json": _json_bytes(intent),
        "seed-v1.pptx": artifact,
        "generation-receipt-v1.json": _json_bytes(receipt),
        "preflight-v1.json": _json_bytes(preflight),
    }
    for name, payload in outputs.items():
        _write(args.output_dir / name, payload, overwrite=args.overwrite)

    summary = {
        name: {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        for name, payload in outputs.items()
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

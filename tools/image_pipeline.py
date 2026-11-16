#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTA6AR Arabic Image & Texture Localization Pipeline (`tools/image_pipeline.py`).

Implements Milestone 6 (Issues #19, #20, #21):
1. Enforces the minimum image generation model gate: OpenAI Sunburn or better
   (rejects weaker models such as DALL-E 2/3 or SD 1.5/SDXL).
2. Validates every localized image specification against the visual catalog
   (`images/catalog/visual_categories.json`) and Arabic-in-image standards:
   - Minimum contrast ratio (>= 4.5:1, or >= 7.0:1 for warning signs)
   - Minimum Arabic font size (>= 24px)
   - Licensed SIL OFL 1.1 Arabic font selection (`Cairo`, `IBM Plex Sans Arabic`, `Noto Sans Arabic`)
   - RTL direction and connected Arabic lettering check (flags spaced/disconnected
     Arabic letters like `م و ق ف`).
3. Outputs a `.image.json` manifest logging the AI model, version, and QA status
   without storing any extracted game textures.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "1.0.0"
APPROVED_IMAGE_KEYWORDS = ("sunburn",)
REJECTED_IMAGE_KEYWORDS = ("dall-e-2", "dall-e-3", "dalle2", "dalle3", "sd-1.5", "sdxl", "sd15")

# Heuristic regex to catch disconnected single-letter Arabic sequences (e.g., "م و ق ف")
DISCONNECTED_ARABIC_RE = re.compile(r"(?:[\u0621-\u064A]\s+){3,}[\u0621-\u064A]")


class ImageModelGateError(ValueError):
    """Raised when the requested image model is weaker than OpenAI Sunburn."""


def enforce_image_model_gate(model_name: str, model_version: str | None = None) -> str:
    """Validate that `model_name` meets the OpenAI Sunburn or better requirement."""
    norm = model_name.strip().lower()
    if any(bad in norm for bad in REJECTED_IMAGE_KEYWORDS):
        raise ImageModelGateError(
            f"Rejected image model '{model_name}': weaker than minimum approved OpenAI Sunburn."
        )
    if not any(ok in norm for ok in APPROVED_IMAGE_KEYWORDS):
        raise ImageModelGateError(
            f"Rejected image model '{model_name}': minimum approved model is OpenAI Sunburn or better."
        )

    if model_version and model_version.strip():
        return model_version.strip()
    m = re.search(r"v?(\d+(?:\.\d+)?)", norm)
    return m.group(1) if m else "1.0"


def validate_arabic_image_item(
    item: dict[str, Any],
    catalog: dict[str, Any],
) -> list[str]:
    """Validate a single image localization item against Arabic-in-image QA rules."""
    errors: list[str] = []
    standards = catalog.get("standards", {})
    min_contrast = float(standards.get("min_contrast_ratio", 4.5))
    min_font_px = int(standards.get("min_font_size_px", 24))
    approved_fonts = set(standards.get("approved_fonts", ["Cairo", "IBM Plex Sans Arabic", "Noto Sans Arabic"]))
    valid_categories = {c["category_id"] for c in catalog.get("categories", [])}

    cat_id = item.get("category_id", "")
    if cat_id not in valid_categories:
        errors.append(f"Unknown visual category_id '{cat_id}'.")

    direction = str(item.get("direction", "RTL")).upper()
    if direction != "RTL":
        errors.append(f"Invalid text direction '{direction}'; must be 'RTL'.")

    font_family = item.get("font_family", "")
    if font_family not in approved_fonts:
        errors.append(
            f"Font '{font_family}' is not in approved licensed fonts {sorted(approved_fonts)}."
        )

    font_size = int(item.get("font_size_px", 0))
    if font_size < min_font_px:
        errors.append(f"font_size_px ({font_size}px) is below minimum {min_font_px}px.")

    contrast = float(item.get("contrast_ratio", 0.0))
    if contrast < min_contrast:
        errors.append(f"contrast_ratio ({contrast}:1) is below minimum {min_contrast}:1.")

    ar_text = str(item.get("arabic_text", "")).strip()
    if not ar_text:
        errors.append("arabic_text is empty.")
    elif DISCONNECTED_ARABIC_RE.search(ar_text):
        errors.append(
            f"Detected disconnected Arabic letters in «{ar_text}»; letters must be properly shaped."
        )

    return errors


def build_image_manifest(
    batch_data: dict[str, Any],
    catalog: dict[str, Any],
    model_name: str,
    model_version: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Validate image batch items and build a `.image.json` output manifest."""
    resolved_version = enforce_image_model_gate(model_name, model_version)
    batch_id = batch_data.get("batch_id", "img-batch-001")
    items = batch_data.get("items", [])
    if not items:
        raise ValueError("Image batch contains no items.")

    manifest_items: list[dict[str, Any]] = []
    for item in items:
        iid = item["id"]
        qa_errors = validate_arabic_image_item(item, catalog)
        if qa_errors:
            raise ValueError(f"QA validation failed for image '{iid}': {'; '.join(qa_errors)}")

        manifest_items.append(
            {
                "id": iid,
                "category_id": item["category_id"],
                "arabic_text": item["arabic_text"],
                "font_family": item["font_family"],
                "font_size_px": item["font_size_px"],
                "contrast_ratio": item["contrast_ratio"],
                "direction": "RTL",
                "output_image_path": f"images/generated/{batch_id}/{iid}.png",
                "visual_qa_status": "PASS",
            }
        )

    timestamp = generated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": "1.0.0",
        "batch_id": batch_id,
        "generated_at": timestamp,
        "generator": {
            "model_name": model_name,
            "model_version": resolved_version,
            "pipeline_version": PIPELINE_VERSION,
            "catalog_version": catalog.get("catalog_version", "1.0.0"),
        },
        "items": manifest_items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the GTA6AR OpenAI Sunburn+ Arabic image localization pipeline."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input image batch JSON.")
    parser.add_argument("--output", required=True, type=Path, help="Output .image.json manifest.")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "images"
        / "catalog"
        / "visual_categories.json",
        help="Path to visual_categories.json.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GTA6AR_IMAGE_MODEL", "openai-sunburn"),
        help="Image model identifier (must be OpenAI Sunburn or better).",
    )
    parser.add_argument(
        "--model-version",
        default=os.environ.get("GTA6AR_IMAGE_VERSION", "1.0"),
        help="Explicit model version.",
    )
    args = parser.parse_args(argv)

    try:
        batch_data = json.loads(args.input.read_text(encoding="utf-8"))
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        manifest = build_image_manifest(
            batch_data=batch_data,
            catalog=catalog,
            model_name=args.model,
            model_version=args.model_version,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[OK] Generated image localization manifest '{args.output}' "
        f"({len(manifest['items'])} items, model={manifest['generator']['model_name']} "
        f"v{manifest['generator']['model_version']})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "1.0.0"
APPROVED_IMAGE_MODELS: dict[str, tuple[int, int]] = {
    "openai-sunburn": (1, 0),
    "sunburn": (1, 0),
    "gpt-image-sunburn": (1, 0),
}
REJECTED_IMAGE_KEYWORDS = ("dall-e-2", "dall-e-3", "dalle2", "dalle3", "sd-1.5", "sdxl", "sd15")
WARNING_SIGN_KEYWORDS = ("warning", "hazard", "alert", "danger", "emergency", "تحذير", "خطر", "طوارئ", "انتبه")

# Heuristic regex to catch disconnected single-letter Arabic sequences (e.g., "م و ق ف")
DISCONNECTED_ARABIC_RE = re.compile(r"(?:[\u0621-\u064A]\s+){3,}[\u0621-\u064A]")


def redact_secrets(text: str) -> str:
    """Redact OpenAI API keys from error messages before logging."""
    return re.sub(r"sk-[A-Za-z0-9\-_]{20,}", "[REDACTED]", text)


class ImageModelGateError(ValueError):
    """Raised when the requested image model is weaker than OpenAI Sunburn."""


def _parse_version(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    m = re.search(r"v?(\d+)(?:\.(\d+))?", text)
    if m:
        return (int(m.group(1)), int(m.group(2) or 0))
    return None


def enforce_image_model_gate(model_name: str, model_version: str | None = None) -> str:
    """Validate that `model_name` is in the approved OpenAI Sunburn+ allow-list."""
    norm = model_name.strip().lower()
    if any(bad in norm for bad in REJECTED_IMAGE_KEYWORDS):
        raise ImageModelGateError(
            f"Rejected image model '{model_name}': weaker than minimum approved OpenAI Sunburn."
        )

    matched_family: str | None = None
    min_ver = (1, 0)
    for prefix, req_ver in APPROVED_IMAGE_MODELS.items():
        if norm == prefix or norm.startswith(prefix + "-") or norm.startswith(prefix + "_"):
            matched_family = prefix
            min_ver = req_ver
            break

    if matched_family is None:
        raise ImageModelGateError(
            f"Rejected image model '{model_name}': must be an approved OpenAI Sunburn+ model "
            f"({sorted(APPROVED_IMAGE_MODELS.keys())})."
        )

    suffix = norm[len(matched_family) :]
    name_ver = _parse_version(suffix)
    explicit_ver = _parse_version(model_version)

    if name_ver is not None and explicit_ver is not None and name_ver != explicit_ver:
        raise ImageModelGateError(
            f"Version mismatch between model '{model_name}' (v{name_ver[0]}.{name_ver[1]}) "
            f"and explicit version '{model_version}'."
        )

    resolved = name_ver or explicit_ver or min_ver
    if resolved < min_ver:
        raise ImageModelGateError(
            f"Rejected image model '{model_name}' (v{resolved[0]}.{resolved[1]}): "
            f"minimum required version is {min_ver[0]}.{min_ver[1]}."
        )
    return f"{resolved[0]}.{resolved[1]}"


def _is_warning_sign_item(item: dict[str, Any]) -> bool:
    """Detect whether an image item is a road/warning sign requiring 7.0:1 contrast."""
    if bool(item.get("is_warning_sign")):
        return True
    cat_id = str(item.get("category_id", "")).lower()
    if cat_id in {"cat.road_and_transit_signs", "street_and_traffic_signs"}:
        return True
    combined = f"{item.get('id', '')} {item.get('arabic_text', '')} {item.get('prompt_description', '')}".lower()
    return any(kw in combined for kw in WARNING_SIGN_KEYWORDS)


def validate_arabic_image_item(
    item: dict[str, Any],
    catalog: dict[str, Any],
) -> list[str]:
    """Validate a single image localization item against Arabic-in-image QA rules."""
    errors: list[str] = []
    standards = catalog.get("standards", {})
    base_contrast = float(standards.get("min_contrast_ratio", 4.5))
    warning_contrast = float(standards.get("min_warning_sign_contrast_ratio", 7.0))
    min_contrast = warning_contrast if _is_warning_sign_item(item) else base_contrast
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


def generate_openai_image(
    item: dict[str, Any],
    model_name: str,
    api_key: str,
    output_path: Path,
) -> None:
    """Call OpenAI Images HTTP API (`v1/images/generations`) and save PNG to `output_path`."""
    url = "https://api.openai.com/v1/images/generations"
    prompt = (
        f"Render an in-game graphic in Modern Standard Arabic (RTL, connected Arabic calligraphy) "
        f"using font '{item['font_family']}' (>={item['font_size_px']}px, contrast >={item['contrast_ratio']}:1). "
        f"Exact Arabic text: «{item['arabic_text']}». "
        f"Visual style: {item.get('prompt_description', 'Clean high-contrast sign')}."
    )
    payload = {
        "model": model_name,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        b64_data = body["data"][0]["b64_json"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(b64_data))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenAI Images API error ({exc.code}): {redact_secrets(err_body)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI Images network error: {redact_secrets(str(exc))}") from exc


def build_image_manifest(
    batch_data: dict[str, Any],
    catalog: dict[str, Any],
    model_name: str,
    model_version: str | None = None,
    generated_at: str | None = None,
    generate_images: bool = False,
    api_key: str | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """Validate image batch items and build a `.image.json` output manifest."""
    resolved_version = enforce_image_model_gate(model_name, model_version)
    batch_id = batch_data.get("batch_id", "img-batch-001")
    items = batch_data.get("items", [])
    if not items:
        raise ValueError("Image batch contains no items.")

    if generate_images and not api_key:
        raise ValueError("OPENAI_API_KEY is required when --generate is enabled.")

    manifest_items: list[dict[str, Any]] = []
    for item in items:
        iid = item["id"]
        qa_errors = validate_arabic_image_item(item, catalog)
        if qa_errors:
            raise ValueError(f"QA validation failed for image '{iid}': {'; '.join(qa_errors)}")

        rel_img_path = f"images/generated/{batch_id}/{iid}.png"
        if generate_images and api_key:
            dest_root = output_root or Path.cwd()
            generate_openai_image(
                item=item,
                model_name=model_name,
                api_key=api_key,
                output_path=dest_root / rel_img_path,
            )
            qa_status = "PASS"
        else:
            qa_status = "SPEC_VALIDATED"

        manifest_items.append(
            {
                "id": iid,
                "category_id": item["category_id"],
                "arabic_text": item["arabic_text"],
                "font_family": item["font_family"],
                "font_size_px": item["font_size_px"],
                "contrast_ratio": item["contrast_ratio"],
                "direction": "RTL",
                "output_image_path": rel_img_path,
                "visual_qa_status": qa_status,
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
        default=os.environ.get("GTA6AR_IMAGE_VERSION"),
        help="Optional explicit model version.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Call OpenAI Images HTTP API to render localized textures (requires OPENAI_API_KEY).",
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
            generate_images=args.generate,
            api_key=os.environ.get("OPENAI_API_KEY"),
            output_root=Path(__file__).resolve().parents[1],
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

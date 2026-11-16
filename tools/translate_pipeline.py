#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTA6AR Arabic translation pipeline (Gemini 3.8 Flash or stronger).

Features:
- Enforces the project's minimum AI model gate (Gemini >= 3.8), deriving the
  version directly from the model name and rejecting any mismatch with an
  explicit version argument.
- Injects the Fusha style guide and glossary terms into the system prompt.
- Batches translation requests with a configurable batch size limit.
- Computes SHA-256 hashes of source strings so original game text is never
  stored in the output `.patch.json` files (including in `--dry-run` mode).
- Never prints or logs API keys.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
MIN_GEMINI_VERSION = (3, 8)
DEFAULT_BATCH_SIZE = 50
MAX_ALLOWED_BATCH_SIZE = 250


class ModelGateError(ValueError):
    """Raised when the requested AI model is below the approved project minimum."""


def _parse_version_tuple(version_str: str) -> tuple[int, int] | None:
    """Parse 'major' or 'major.minor' into an integer tuple."""
    m = re.fullmatch(r"v?(\d+)(?:\.(\d+))?", version_str.strip().lower())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2) or 0))


def parse_gemini_version(model_name: str, explicit_version: str | None = None) -> tuple[int, int]:
    """Extract (major, minor) version from a Gemini model name and cross-check `explicit_version`."""
    normalized = model_name.strip().lower()
    if "gemini" not in normalized:
        raise ModelGateError(
            f"Rejected model '{model_name}': translation requires Gemini 3.8 Flash or stronger."
        )

    m = re.search(r"gemini[-_/\s]*v?(\d+)(?:\.(\d+))?", normalized)
    if not m:
        raise ModelGateError(
            f"Could not determine Gemini version from model name '{model_name}'. "
            "Model identifier must include version >= 3.8 (e.g. 'gemini-3.8-flash')."
        )

    name_ver = (int(m.group(1)), int(m.group(2) or 0))

    if explicit_version is not None and explicit_version.strip():
        exp_ver = _parse_version_tuple(explicit_version)
        if exp_ver is None:
            raise ModelGateError(
                f"Invalid explicit model version '{explicit_version}'. Expected format like '3.8'."
            )
        if exp_ver != name_ver:
            raise ModelGateError(
                f"Model version mismatch: model '{model_name}' is v{name_ver[0]}.{name_ver[1]}, "
                f"but explicit version '{explicit_version}' was supplied."
            )

    return name_ver


def enforce_model_gate(model_name: str, model_version: str | None = None) -> str:
    """Validate that model_name meets the Gemini >= 3.8 requirement.

    Returns the resolved version string (e.g. '3.8').
    """
    major, minor = parse_gemini_version(model_name, model_version)
    if (major, minor) < MIN_GEMINI_VERSION:
        raise ModelGateError(
            f"Rejected model '{model_name}' (v{major}.{minor}): "
            "minimum approved model for GTA6AR translation is Gemini 3.8 Flash (>= 3.8)."
        )
    return f"{major}.{minor}"


def sha256_hex(text: str) -> str:
    """Return lowercase SHA-256 hex digest of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_glossary(glossary_path: Path) -> dict[str, Any]:
    """Load and return the JSON glossary."""
    if not glossary_path.is_file():
        raise FileNotFoundError(f"Glossary file not found: {glossary_path}")
    return json.loads(glossary_path.read_text(encoding="utf-8"))


def build_system_prompt(glossary: dict[str, Any], domain: str) -> str:
    """Construct the system prompt enforcing Fusha style and glossary terms."""
    terms_lines = []
    for term in glossary.get("terms", []):
        src = term.get("source_en", "")
        tgt = term.get("target_ar", "")
        alts = ", ".join(term.get("alternatives_ar", []))
        forbid = ", ".join(term.get("forbidden_ar", []))
        line = f"- {src} -> «{tgt}»"
        if alts:
            line += f" (بدائل مسموحة: {alts})"
        if forbid:
            line += f" [يُمنع: {forbid}]"
        terms_lines.append(line)

    glossary_block = "\n".join(terms_lines)
    return (
        "أنت نظام التعريب الآلي المعتمد لمشروع GTA6AR.\n"
        "المهمة: ترجمة سلاسل النصوص المرفقة إلى العربية الفصحى المعاصرة السلسة (MSA / Fusha) بدقة وإتقان.\n\n"
        "القواعد الإلزامية:\n"
        "1. الالتزام التام بالعربية الفصحى السلسة، وتجنّب العاميات أو اللهجات المحلية.\n"
        "2. صيغة المخاطبة الافتراضية في الواجهة والتعليمات هي المفرد المذكر.\n"
        "3. استخدام الأرقام القياسية (0-9) وعدم تحويلها إلى أرقام هندية.\n"
        "4. الحفاظ التام على جميع المتغيرات والرموز البرمجية (Placeholders) مثل {0} و %s و ~INPUT_ACCEPT~ دون أي تغيير.\n"
        "5. مراعاة الحد الأقصى للأحرف (max_chars) والأسطر (max_lines) المحدد لكل سلسلة.\n"
        f"6. مجال الدفعة الحالي: {domain}.\n\n"
        "المسرد الإلزامي للمصطلحات:\n"
        f"{glossary_block}\n\n"
        "أخرج النتيجة بصيغة JSON فقط: مصفوفة كائنات يحتوي كل منها على الحقلين \"id\" و \"ar\"."
    )


def chunk_entries(entries: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    """Split entries into bounded batches."""
    if batch_size < 1 or batch_size > MAX_ALLOWED_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_ALLOWED_BATCH_SIZE}")
    return [entries[i : i + batch_size] for i in range(0, len(entries), batch_size)]


def call_gemini_api(
    model_name: str,
    system_prompt: str,
    batch: list[dict[str, Any]],
    api_key: str,
) -> dict[str, str]:
    """Call the Google Generative Language API for a single batch.

    Never logs or prints the API key.
    """
    payload_items = [
        {
            "id": item["id"],
            "source_en": item.get("source_en", ""),
            "context_category": item.get("context_category", "other"),
            "max_chars": item.get("max_chars"),
            "max_lines": item.get("max_lines"),
            "placeholders": item.get("placeholders", []),
        }
        for item in batch
    ]
    user_text = json.dumps(payload_items, ensure_ascii=False, indent=2)

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Gemini API HTTP {exc.code}: request failed (API key redacted)."
        ) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Gemini API connection error: {exc.reason} (API key redacted)."
        ) from None

    try:
        text_out = raw["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text_out)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected Gemini response structure: {exc}") from None

    return {row["id"]: row["ar"] for row in parsed if "id" in row and "ar" in row}


def dry_run_translate(batch: list[dict[str, Any]], glossary: dict[str, Any]) -> dict[str, str]:
    """Deterministic offline translation for testing without copying any English `source_en` text."""
    terms_by_id = {t["id"]: t for t in glossary.get("terms", [])}
    results: dict[str, str] = {}
    for item in batch:
        if "ar" in item and item["ar"]:
            results[item["id"]] = item["ar"]
            continue

        ar_parts: list[str] = ["[معاينة تجريبية]"]
        for tid in item.get("glossary_terms", []):
            term = terms_by_id.get(tid)
            if term and term.get("target_ar"):
                ar_parts.append(term["target_ar"])
        for ph in item.get("placeholders", []):
            ar_parts.append(str(ph))

        results[item["id"]] = " ".join(ar_parts)
    return results


def build_patch_document(
    input_data: dict[str, Any],
    glossary: dict[str, Any],
    model_name: str,
    model_version: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run the translation pipeline on input_data and return a patch dict."""
    resolved_version = enforce_model_gate(model_name, model_version)
    domain = input_data.get("domain", "ui")
    batch_id = input_data.get("batch_id", "batch-001")
    raw_entries = input_data.get("entries", [])
    if not raw_entries:
        raise ValueError("Input batch contains no entries.")

    system_prompt = build_system_prompt(glossary, domain)
    batches = chunk_entries(raw_entries, batch_size=batch_size)

    api_key = ""
    if not dry_run:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is not set. "
                "Set it in your local environment or pass --dry-run for offline testing."
            )

    translated_map: dict[str, str] = {}
    for batch in batches:
        if dry_run:
            translated_map.update(dry_run_translate(batch, glossary))
        else:
            translated_map.update(call_gemini_api(model_name, system_prompt, batch, api_key))

    output_entries: list[dict[str, Any]] = []
    for item in raw_entries:
        entry_id = item["id"]
        ar_val = translated_map.get(entry_id, "")
        if not ar_val:
            raise RuntimeError(f"Missing Arabic output for entry '{entry_id}'.")

        out_entry: dict[str, Any] = {"id": entry_id}
        if "source_hash" in item and item["source_hash"]:
            out_entry["source_hash"] = item["source_hash"]
        elif "source_en" in item and item["source_en"]:
            out_entry["source_hash"] = sha256_hex(item["source_en"])

        out_entry["ar"] = ar_val
        for optional_key in (
            "context_category",
            "max_chars",
            "max_lines",
            "timing_ms",
            "placeholders",
            "glossary_terms",
        ):
            if optional_key in item:
                out_entry[optional_key] = item[optional_key]

        output_entries.append(out_entry)

    timestamp = generated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recorded_model = f"dry-run ({model_name})" if dry_run else model_name
    recorded_version = "dry-run" if dry_run else resolved_version
    return {
        "schema_version": SCHEMA_VERSION,
        "domain": domain,
        "batch_id": batch_id,
        "generated_at": timestamp,
        "generator": {
            "model_name": recorded_model,
            "model_version": recorded_version,
            "pipeline_version": PIPELINE_VERSION,
            "glossary_version": glossary.get("glossary_version", "1.0.0"),
        },
        "entries": output_entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the GTA6AR Gemini 3.8+ Arabic translation pipeline."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the input batch JSON file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the output .patch.json file.",
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "text" / "glossary.json",
        help="Path to text/glossary.json.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GTA6AR_GEMINI_MODEL", "gemini-3.8-flash"),
        help="Gemini model identifier (must be Gemini 3.8 Flash or stronger).",
    )
    parser.add_argument(
        "--model-version",
        default=os.environ.get("GTA6AR_GEMINI_VERSION"),
        help="Optional explicit model version cross-check (e.g. '3.8').",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Entries per API call (1..{MAX_ALLOWED_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run offline without calling the API (marks output as dry-run and omits source_en).",
    )
    args = parser.parse_args(argv)

    try:
        glossary = load_glossary(args.glossary)
        input_data = json.loads(args.input.read_text(encoding="utf-8"))
        patch_doc = build_patch_document(
            input_data=input_data,
            glossary=glossary,
            model_name=args.model,
            model_version=args.model_version,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(patch_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[OK] Generated patch '{args.output}' "
        f"({len(patch_doc['entries'])} entries, model={patch_doc['generator']['model_name']} "
        f"v{patch_doc['generator']['model_version']})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTA6AR Glossary Consistency & Patch Validator (`tools/check_glossary.py`).

Checks Arabic text patch files against `text/glossary.json` and patch rules:
1. Validates generator model gate (Gemini 3.8 Flash or stronger).
2. Flags any occurrence of `forbidden_ar` terms from the glossary.
3. Verifies that entries referencing `glossary_terms` include the approved
   `target_ar` (or one of `alternatives_ar`).
4. Verifies that all declared `placeholders` appear intact in `ar`.
5. Verifies `max_chars` and `max_lines` constraints when specified.
6. Generates a clear Markdown or console report suitable for Pull Request reviews.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from translate_pipeline import ModelGateError, enforce_model_gate

ARABIC_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")
ARABIC_WORD_RE = re.compile(r"[\u0621-\u064A]+")
BATCH_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "text" / "schema" / "text_patch.schema.json"


def normalize_arabic(text: str) -> str:
    """Strip tashkeel/tatweel for resilient matching while keeping hamzas."""
    return ARABIC_DIACRITICS_RE.sub("", text)


def tokenize_arabic_words(text: str) -> list[str]:
    """Return normalized Arabic word tokens from `text`."""
    return ARABIC_WORD_RE.findall(normalize_arabic(text))


def build_forbidden_word_forms(forbidden_word: str) -> set[str]:
    """Build exact whole-word forms for a single forbidden Arabic token."""
    forms = {forbidden_word, f"و{forbidden_word}", f"ف{forbidden_word}"}
    if forbidden_word != "الضبط":
        forms.update({f"ب{forbidden_word}", f"ك{forbidden_word}"})
        if forbidden_word.startswith("ال") and len(forbidden_word) > 2:
            forms.add(f"لل{forbidden_word[2:]}")
    return forms


def contains_arabic_phrase(text_with_diacritics: str, text_tokens: list[str], phrase: str) -> bool:
    """Check whether `phrase` appears as a whole word (or multi-word sequence) in `norm_text`."""
    phrase_tokens = tokenize_arabic_words(phrase)
    if not phrase_tokens:
        return False

    if len(phrase_tokens) == 1:
        target = phrase_tokens[0]
        candidate_forms = build_forbidden_word_forms(target)
        for tok in text_tokens:
            if tok in candidate_forms:
                # If the original text explicitly has a shadda (ـّ) such as «اطّلع»,
                # it is the Fusha verb Form VIII (اطَّلَعَ), not colloquial «اطلع».
                if target == "اطلع" and "اطّلع" in text_with_diacritics:
                    continue
                return True
        return False

    n = len(phrase_tokens)
    first_forms = build_forbidden_word_forms(phrase_tokens[0])
    for i in range(len(text_tokens) - n + 1):
        if text_tokens[i] in first_forms and text_tokens[i + 1 : i + n] == phrase_tokens[1:]:
            return True
    return False


@dataclass
class Violation:
    file_path: str
    entry_id: str
    rule: str
    message: str


def validate_against_schema(
    patch_data: dict[str, Any],
    schema: dict[str, Any],
    file_label: str,
) -> list[Violation]:
    """Enforce `text/schema/text_patch.schema.json` structural constraints using stdlib."""
    violations: list[Violation] = []
    if not isinstance(patch_data, dict):
        return [Violation(file_label, "<root>", "schema-invalid", "Root document must be a JSON object.")]

    required_root = set(schema.get("required", []))
    allowed_root = set(schema.get("properties", {}).keys())
    for req in sorted(required_root):
        if req not in patch_data:
            violations.append(
                Violation(file_label, "<root>", "schema-missing-field", f"Missing required root field '{req}'.")
            )
    for key in patch_data:
        if allowed_root and key not in allowed_root:
            violations.append(
                Violation(file_label, "<root>", "schema-additional-property", f"Unexpected root field '{key}'.")
            )

    if patch_data.get("schema_version") != "1.0.0":
        violations.append(
            Violation(file_label, "<root>", "schema-version", "schema_version must be '1.0.0'.")
        )

    allowed_domains = set(
        schema.get("properties", {}).get("domain", {}).get("enum", ["ui", "subtitles", "missions"])
    )
    if patch_data.get("domain") not in allowed_domains:
        violations.append(
            Violation(
                file_label,
                "<root>",
                "schema-domain",
                f"Invalid domain '{patch_data.get('domain')}'; must be one of {sorted(allowed_domains)}.",
            )
        )

    batch_id = str(patch_data.get("batch_id", ""))
    if not BATCH_ID_RE.match(batch_id):
        violations.append(
            Violation(
                file_label,
                "<root>",
                "schema-batch-id",
                f"Invalid batch_id '{batch_id}'; must match {BATCH_ID_RE.pattern}.",
            )
        )

    gen = patch_data.get("generator")
    gen_schema = schema.get("properties", {}).get("generator", {})
    if not isinstance(gen, dict):
        violations.append(Violation(file_label, "<generator>", "schema-generator", "'generator' must be an object."))
    else:
        req_gen = set(gen_schema.get("required", []))
        allow_gen = set(gen_schema.get("properties", {}).keys())
        for req in sorted(req_gen):
            if req not in gen or not isinstance(gen[req], str) or not gen[req].strip():
                violations.append(
                    Violation(
                        file_label,
                        "<generator>",
                        "schema-generator-field",
                        f"Missing or empty generator field '{req}'.",
                    )
                )
        for k in gen:
            if allow_gen and k not in allow_gen:
                violations.append(
                    Violation(
                        file_label,
                        "<generator>",
                        "schema-additional-property",
                        f"Unexpected generator field '{k}'.",
                    )
                )

    entry_schema = schema.get("properties", {}).get("entries", {}).get("items", {})
    allow_entry_keys = set(entry_schema.get("properties", {}).keys())
    allow_categories = set(
        entry_schema.get("properties", {})
        .get("context_category", {})
        .get("enum", ["menu", "settings", "hud", "prompt", "dialogue", "objective", "notification", "other"])
    )

    entries = patch_data.get("entries")
    if isinstance(entries, list):
        for idx, item in enumerate(entries):
            if not isinstance(item, dict):
                violations.append(
                    Violation(file_label, f"<entry[{idx}]>", "schema-entry", "Entry must be an object.")
                )
                continue
            eid = str(item.get("id", f"<entry[{idx}]>"))
            for k in item:
                if allow_entry_keys and k not in allow_entry_keys:
                    violations.append(
                        Violation(
                            file_label,
                            eid,
                            "schema-additional-property",
                            f"Unexpected entry field '{k}' (remember: never store source_en).",
                        )
                    )
            if "source_hash" in item and not SHA256_RE.match(str(item["source_hash"])):
                violations.append(
                    Violation(file_label, eid, "schema-source-hash", "source_hash must be a 64-char hex SHA-256.")
                )
            if "context_category" in item and item["context_category"] not in allow_categories:
                violations.append(
                    Violation(
                        file_label,
                        eid,
                        "schema-context-category",
                        f"Invalid context_category '{item['context_category']}'.",
                    )
                )
            if "timing_ms" in item:
                tm = item["timing_ms"]
                if (
                    not isinstance(tm, dict)
                    or not isinstance(tm.get("start"), int)
                    or not isinstance(tm.get("end"), int)
                    or tm["start"] < 0
                    or tm["end"] < 1
                ):
                    violations.append(
                        Violation(file_label, eid, "schema-timing-ms", "Invalid timing_ms object.")
                    )

    return violations


def check_patch_data(
    patch_data: dict[str, Any],
    glossary: dict[str, Any],
    file_label: str = "<memory>",
    schema: dict[str, Any] | None = None,
) -> list[Violation]:
    """Validate a parsed patch dictionary against the glossary and schema rules."""
    violations: list[Violation] = []

    if schema is None and DEFAULT_SCHEMA_PATH.is_file():
        schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    if schema is not None:
        violations.extend(validate_against_schema(patch_data, schema, file_label))

    generator = patch_data.get("generator", {}) if isinstance(patch_data.get("generator"), dict) else {}
    model_name = str(generator.get("model_name", ""))
    model_version = generator.get("model_version")

    if "dry-run" in model_name.lower() or str(model_version).lower() == "dry-run":
        violations.append(
            Violation(
                file_path=file_label,
                entry_id="<generator>",
                rule="dry-run-not-allowed",
                message="Dry-run output is for local testing only and cannot pass release/PR validation.",
            )
        )
    else:
        try:
            enforce_model_gate(model_name, str(model_version) if model_version else None)
        except ModelGateError as exc:
            violations.append(
                Violation(
                    file_path=file_label,
                    entry_id="<generator>",
                    rule="model-gate",
                    message=str(exc),
                )
            )

    terms_by_id: dict[str, dict[str, Any]] = {}
    all_terms: list[dict[str, Any]] = glossary.get("terms", [])
    for term in all_terms:
        tid = term.get("id")
        if tid:
            terms_by_id[tid] = term

    entries = patch_data.get("entries", [])
    if not isinstance(entries, list) or not entries:
        violations.append(
            Violation(
                file_path=file_label,
                entry_id="<root>",
                rule="empty-entries",
                message="Patch contains no entries.",
            )
        )
        return violations

    seen_ids: set[str] = set()
    for item in entries:
        entry_id = str(item.get("id", "<missing-id>"))
        if entry_id in seen_ids:
            violations.append(
                Violation(
                    file_path=file_label,
                    entry_id=entry_id,
                    rule="duplicate-id",
                    message=f"Duplicate entry id '{entry_id}' in patch.",
                )
            )
        seen_ids.add(entry_id)

        ar_text = str(item.get("ar", "")).strip()
        if not ar_text:
            violations.append(
                Violation(
                    file_path=file_label,
                    entry_id=entry_id,
                    rule="empty-translation",
                    message="Arabic text 'ar' is empty.",
                )
            )
            continue

        norm_ar = normalize_arabic(ar_text)
        ar_tokens = tokenize_arabic_words(ar_text)

        # 1. Check all forbidden terms across the glossary using whole-word matching
        for term in all_terms:
            for forbidden in term.get("forbidden_ar", []):
                if contains_arabic_phrase(ar_text, ar_tokens, forbidden):
                    violations.append(
                        Violation(
                            file_path=file_label,
                            entry_id=entry_id,
                            rule="forbidden-term",
                            message=(
                                f"Found forbidden term «{forbidden}» "
                                f"(use «{term['target_ar']}» for '{term['source_en']}')."
                            ),
                        )
                    )

        # 2. Check explicitly linked glossary_terms for this entry
        for tid in item.get("glossary_terms", []):
            if tid not in terms_by_id:
                violations.append(
                    Violation(
                        file_path=file_label,
                        entry_id=entry_id,
                        rule="unknown-glossary-id",
                        message=f"Referenced glossary term '{tid}' does not exist in glossary.",
                    )
                )
                continue

            term = terms_by_id[tid]
            allowed_forms = [term["target_ar"], *term.get("alternatives_ar", [])]
            norm_allowed = [normalize_arabic(f) for f in allowed_forms if f]
            # Also allow stripped leading definite article "ال" when prefixed by prepositions (بـ، لـ، كـ، فـ)
            expanded_allowed = list(norm_allowed)
            for form in norm_allowed:
                if form.startswith("ال") and len(form) > 2:
                    bare = form[2:]
                    expanded_allowed.extend([f"بال{bare}", f"لل{bare}", f"كال{bare}", f"وال{bare}", bare])

            if not any(cand in norm_ar for cand in expanded_allowed):
                violations.append(
                    Violation(
                        file_path=file_label,
                        entry_id=entry_id,
                        rule="missing-glossary-term",
                        message=(
                            f"Entry requires term '{tid}' ({term['source_en']} -> "
                            f"«{term['target_ar']}»), but none of the approved forms "
                            f"{allowed_forms} were found in «{ar_text}»."
                        ),
                    )
                )

        # 3. Check placeholders preservation
        for ph in item.get("placeholders", []):
            if ph not in ar_text:
                violations.append(
                    Violation(
                        file_path=file_label,
                        entry_id=entry_id,
                        rule="missing-placeholder",
                        message=f"Missing required placeholder '{ph}' in Arabic translation.",
                    )
                )

        # 4. Check length and line constraints
        lines = ar_text.splitlines() or [ar_text]
        max_lines = item.get("max_lines")
        if isinstance(max_lines, int) and len(lines) > max_lines:
            violations.append(
                Violation(
                    file_path=file_label,
                    entry_id=entry_id,
                    rule="max-lines-exceeded",
                    message=f"Translation has {len(lines)} lines, exceeding max_lines={max_lines}.",
                )
            )

        max_chars = item.get("max_chars")
        if isinstance(max_chars, int):
            longest_line = max(len(line) for line in lines)
            if longest_line > max_chars:
                violations.append(
                    Violation(
                        file_path=file_label,
                        entry_id=entry_id,
                        rule="max-chars-exceeded",
                        message=(
                            f"Line length ({longest_line} chars) exceeds max_chars={max_chars} "
                            f"in «{ar_text}»."
                        ),
                    )
                )

    return violations


def format_markdown_report(
    checked_files: list[str],
    violations: list[Violation],
) -> str:
    """Build a bilingual Markdown QA report for PR reviews."""
    status = "ناجح (PASS)" if not violations else f"فشل ({len(violations)} مخالفة / FAIL)"
    lines = [
        "## تقرير فحص اتساق المسرد والترقيع — Glossary & Patch QA Report",
        "",
        f"- **الحالة / Status:** {status}",
        f"- **الملفات المفحوصة / Checked files:** `{len(checked_files)}`",
        f"- **إجمالي المخالفات / Total violations:** `{len(violations)}`",
        "",
    ]
    if not violations:
        lines.append("جميع ملفات الترقيع مطابقة للمسرد وقواعد النموذج المعتمد.")
        return "\n".join(lines)

    lines.extend(
        [
            "| الملف / File | المعرّف / Entry ID | القاعدة / Rule | التفاصيل / Details |",
            "|---|---|---|---|",
        ]
    )
    for v in violations:
        lines.append(f"| `{v.file_path}` | `{v.entry_id}` | `{v.rule}` | {v.message} |")
    return "\n".join(lines)


def collect_patch_paths(targets: list[Path]) -> list[Path]:
    """Expand files and directories into a sorted list of JSON patch files."""
    found: list[Path] = []
    for target in targets:
        if target.is_file():
            found.append(target)
        elif target.is_dir():
            found.extend(sorted(target.rglob("*.json")))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check GTA6AR Arabic patch files for glossary consistency and QA rules."
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "text" / "glossary.json",
        help="Path to text/glossary.json.",
    )
    parser.add_argument(
        "--patches",
        type=Path,
        nargs="+",
        required=True,
        help="One or more patch JSON files or directories to validate.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        help="Optional path to write the Markdown QA report.",
    )
    args = parser.parse_args(argv)

    if not args.glossary.is_file():
        print(f"[ERROR] Glossary not found: {args.glossary}", file=sys.stderr)
        return 1

    glossary = json.loads(args.glossary.read_text(encoding="utf-8"))
    patch_files = collect_patch_paths(args.patches)
    if not patch_files:
        print("[ERROR] No patch JSON files found in specified paths.", file=sys.stderr)
        return 1

    all_violations: list[Violation] = []
    checked_labels: list[str] = []
    for pfile in patch_files:
        label = pfile.as_posix()
        checked_labels.append(label)
        data = json.loads(pfile.read_text(encoding="utf-8"))
        all_violations.extend(check_patch_data(data, glossary, file_label=pfile.name))

    report = format_markdown_report(checked_labels, all_violations)
    print(report)

    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(report + "\n", encoding="utf-8")

    return 0 if not all_violations else 1


if __name__ == "__main__":
    sys.exit(main())

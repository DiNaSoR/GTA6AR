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


def normalize_arabic(text: str) -> str:
    """Strip tashkeel/tatweel for resilient substring matching while keeping hamzas."""
    return ARABIC_DIACRITICS_RE.sub("", text)


@dataclass
class Violation:
    file_path: str
    entry_id: str
    rule: str
    message: str


def check_patch_data(
    patch_data: dict[str, Any],
    glossary: dict[str, Any],
    file_label: str = "<memory>",
) -> list[Violation]:
    """Validate a parsed patch dictionary against the glossary and schema rules."""
    violations: list[Violation] = []

    generator = patch_data.get("generator", {})
    model_name = generator.get("model_name", "")
    model_version = generator.get("model_version")
    try:
        enforce_model_gate(str(model_name), str(model_version) if model_version else None)
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

        # 1. Check all forbidden terms across the glossary
        for term in all_terms:
            for forbidden in term.get("forbidden_ar", []):
                norm_forbid = normalize_arabic(forbidden)
                if norm_forbid and norm_forbid in norm_ar:
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

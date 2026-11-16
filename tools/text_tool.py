#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTA6AR Generic Text Extractor, Injector & RTL Preview CLI (`tools/text_tool.py`).

Implements Issue #5 and Issue #13:
- Pluggable adapter architecture (`StringTableAdapter`, `JsonKeyValueAdapter`,
  `CsvTableAdapter`, `IniKeyValueAdapter`) to extract strings from local files
  into translation input batches and inject `.patch.json` translations back.
- Optional SHA-256 `source_hash` verification during injection.
- Optional Arabic contextual shaping (`--shape`) and Unicode BiDi isolation
  (`--bidi-isolate`) for game UI engines that lack native RTL shaping.
- Standalone RTL HTML preview generator (`preview` command) using the project's
  licensed SIL OFL 1.1 Arabic fonts (`IBM Plex Sans Arabic`, `Cairo`,
  `Noto Sans Arabic`).

Legal rule: Tested exclusively on dummy strings. Never commit original game
files or extracted assets to the repository.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rtl_shaper import (
    has_eastern_arabic_numerals,
    has_kashida,
    isolate_bidi_tokens,
    normalize_numerals,
    shape_arabic_text,
)

PLACEHOLDER_SCAN_RE = re.compile(
    r"(~\w+~|\{[a-zA-Z0-9_]+\}|%[sdif]|<[A-Za-z0-9_/]+>)"
)


def sha256_hex(text: str) -> str:
    """Compute SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def detect_placeholders(text: str) -> list[str]:
    """Extract ordered unique engine placeholders from a string."""
    seen: list[str] = []
    for match in PLACEHOLDER_SCAN_RE.finditer(text):
        tok = match.group(0)
        if tok not in seen:
            seen.append(tok)
    return seen


@dataclass
class StringRecord:
    id: str
    text: str
    context_category: str = "other"
    max_chars: int | None = None
    max_lines: int | None = None


class StringTableAdapter(ABC):
    """Base interface for replaceable string table adapters."""

    @abstractmethod
    def read_records(self, content: str) -> list[StringRecord]:
        """Parse source content into a list of StringRecord items."""

    @abstractmethod
    def write_records(self, original_content: str, translated_by_id: dict[str, str]) -> str:
        """Return updated content with translated strings injected by ID."""


class JsonKeyValueAdapter(StringTableAdapter):
    """Adapter for JSON string tables (either flat `{id: text}` or `{"strings": [...]}`)."""

    def read_records(self, content: str) -> list[StringRecord]:
        data = json.loads(content)
        records: list[StringRecord] = []
        if isinstance(data, dict) and "strings" in data and isinstance(data["strings"], list):
            for row in data["strings"]:
                records.append(
                    StringRecord(
                        id=str(row["id"]),
                        text=str(row["text"]),
                        context_category=str(row.get("context_category", "other")),
                        max_chars=row.get("max_chars"),
                        max_lines=row.get("max_lines"),
                    )
                )
        elif isinstance(data, dict):
            for k, v in data.items():
                records.append(StringRecord(id=str(k), text=str(v)))
        else:
            raise ValueError("Unsupported JSON string table layout.")
        return records

    def write_records(self, original_content: str, translated_by_id: dict[str, str]) -> str:
        data = json.loads(original_content)
        if isinstance(data, dict) and "strings" in data and isinstance(data["strings"], list):
            for row in data["strings"]:
                rid = str(row["id"])
                if rid in translated_by_id:
                    row["text"] = translated_by_id[rid]
        elif isinstance(data, dict):
            for k in list(data.keys()):
                if str(k) in translated_by_id:
                    data[k] = translated_by_id[str(k)]
        else:
            raise ValueError("Unsupported JSON string table layout.")
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


class CsvTableAdapter(StringTableAdapter):
    """Adapter for CSV string tables with columns `id,text[,context_category,max_chars,max_lines]`."""

    def read_records(self, content: str) -> list[StringRecord]:
        reader = csv.DictReader(io.StringIO(content))
        records: list[StringRecord] = []
        for row in reader:
            max_c = int(row["max_chars"]) if row.get("max_chars") else None
            max_l = int(row["max_lines"]) if row.get("max_lines") else None
            records.append(
                StringRecord(
                    id=str(row["id"]),
                    text=str(row["text"]),
                    context_category=str(row.get("context_category") or "other"),
                    max_chars=max_c,
                    max_lines=max_l,
                )
            )
        return records

    def write_records(self, original_content: str, translated_by_id: dict[str, str]) -> str:
        reader = csv.DictReader(io.StringIO(original_content))
        fieldnames = list(reader.fieldnames or ["id", "text"])
        out_buf = io.StringIO()
        writer = csv.DictWriter(out_buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            rid = str(row["id"])
            if rid in translated_by_id:
                row["text"] = translated_by_id[rid]
            writer.writerow(row)
        return out_buf.getvalue()


class IniKeyValueAdapter(StringTableAdapter):
    """Adapter for simple `KEY = VALUE` localization tables (preserving comments and sections)."""

    LINE_RE = re.compile(r"^(\s*([A-Za-z0-9_.-]+)\s*=\s*)(.*)$")

    def read_records(self, content: str) -> list[StringRecord]:
        records: list[StringRecord] = []
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(("#", ";", "[")):
                continue
            m = self.LINE_RE.match(raw_line)
            if m:
                key = m.group(2)
                val = m.group(3).strip()
                records.append(StringRecord(id=key, text=val))
        return records

    def write_records(self, original_content: str, translated_by_id: dict[str, str]) -> str:
        out_lines: list[str] = []
        for raw_line in original_content.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(("#", ";", "[")):
                out_lines.append(raw_line)
                continue
            m = self.LINE_RE.match(raw_line)
            if m and m.group(2) in translated_by_id:
                prefix = m.group(1)
                key = m.group(2)
                out_lines.append(f"{prefix}{translated_by_id[key]}")
            else:
                out_lines.append(raw_line)
        return "\n".join(out_lines) + "\n"


ADAPTERS: dict[str, type[StringTableAdapter]] = {
    "json": JsonKeyValueAdapter,
    "csv": CsvTableAdapter,
    "ini": IniKeyValueAdapter,
}


def resolve_adapter(adapter_name: str, file_path: Path) -> StringTableAdapter:
    """Resolve adapter by explicit name or file extension."""
    if adapter_name != "auto":
        cls = ADAPTERS.get(adapter_name.lower())
        if not cls:
            raise ValueError(f"Unknown adapter '{adapter_name}'. Choose from: {list(ADAPTERS)}")
        return cls()

    ext = file_path.suffix.lower().lstrip(".")
    if ext in ADAPTERS:
        return ADAPTERS[ext]()
    return JsonKeyValueAdapter()


def extract_to_batch(
    source_content: str,
    adapter: StringTableAdapter,
    domain: str = "ui",
    batch_id: str = "extracted-batch-001",
    include_source_text: bool = False,
) -> dict[str, Any]:
    """Extract strings via adapter into a GTA6AR input batch dictionary.

    By default (`include_source_text=False`), only `source_hash` is emitted so
    the output file is safe to inspect without storing copyrighted source strings.
    When running locally right before `translate_pipeline.py`, `--with-source-text`
    can be used in a temporary untracked file.
    """
    records = adapter.read_records(source_content)
    entries: list[dict[str, Any]] = []
    for rec in records:
        item: dict[str, Any] = {
            "id": rec.id,
            "source_hash": sha256_hex(rec.text),
            "context_category": rec.context_category,
            "placeholders": detect_placeholders(rec.text),
        }
        if include_source_text:
            item["source_en"] = rec.text
        if rec.max_chars is not None:
            item["max_chars"] = rec.max_chars
        if rec.max_lines is not None:
            item["max_lines"] = rec.max_lines
        entries.append(item)

    return {
        "domain": domain,
        "batch_id": batch_id,
        "entries": entries,
    }


def inject_patch(
    original_content: str,
    patch_data: dict[str, Any],
    adapter: StringTableAdapter,
    verify_hashes: bool = True,
    apply_shaping: bool = False,
    apply_bidi_isolate: bool = False,
) -> tuple[str, int]:
    """Inject Arabic translations from patch_data into original_content.

    Returns (updated_content, applied_count).
    """
    records_by_id = {r.id: r for r in adapter.read_records(original_content)}
    translated_by_id: dict[str, str] = {}

    for entry in patch_data.get("entries", []):
        eid = str(entry["id"])
        if eid not in records_by_id:
            continue

        expected_hash = entry.get("source_hash")
        if verify_hashes and expected_hash:
            actual_hash = sha256_hex(records_by_id[eid].text)
            if actual_hash.lower() != str(expected_hash).lower():
                raise ValueError(
                    f"Source hash mismatch for '{eid}': expected {expected_hash}, "
                    f"got {actual_hash}."
                )

        ar_text = normalize_numerals(str(entry["ar"]))
        if apply_shaping:
            ar_text = shape_arabic_text(ar_text)
        if apply_bidi_isolate:
            ar_text = isolate_bidi_tokens(ar_text)

        translated_by_id[eid] = ar_text

    updated = adapter.write_records(original_content, translated_by_id)
    return updated, len(translated_by_id)


def render_rtl_preview_html(patch_data: dict[str, Any]) -> str:
    """Generate a standalone RTL HTML preview page using licensed SIL OFL 1.1 Arabic fonts."""
    batch_id = html.escape(str(patch_data.get("batch_id", "batch")))
    domain = html.escape(str(patch_data.get("domain", "ui")))
    gen = patch_data.get("generator", {})
    model_info = html.escape(
        f"{gen.get('model_name', 'unknown')} (v{gen.get('model_version', '?')})"
    )

    rows_html: list[str] = []
    for item in patch_data.get("entries", []):
        eid = html.escape(str(item.get("id", "")))
        raw_ar = str(item.get("ar", ""))
        bidi_ar = html.escape(isolate_bidi_tokens(raw_ar))
        cat = html.escape(str(item.get("context_category", "other")))
        char_len = len(raw_ar)
        max_c = item.get("max_chars")
        len_badge = f"{char_len}/{max_c}" if max_c else str(char_len)

        warnings: list[str] = []
        if has_eastern_arabic_numerals(raw_ar):
            warnings.append("أرقام هندية شرقية (استخدم 0-9)")
        if has_kashida(raw_ar):
            warnings.append("يحتوي على كشيدة (ـ)")
        warn_html = (
            f'<div class="warn">⚠️ {" · ".join(warnings)}</div>' if warnings else ""
        )

        rows_html.append(
            f"""
            <tr>
              <td dir="ltr" class="id-cell"><code>{eid}</code><br><small>{cat} · {len_badge} chars</small></td>
              <td dir="rtl" class="preview-plex">
                <div class="sz-14">{bidi_ar}</div>
                <div class="sz-20">{bidi_ar}</div>
                <div class="sz-28">{bidi_ar}</div>
                {warn_html}
              </td>
              <td dir="rtl" class="preview-cairo">
                <div class="sz-20">{bidi_ar}</div>
              </td>
            </tr>
            """
        )

    body_rows = "\n".join(rows_html)
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>معاينة التعريب واتجاه RTL — GTA6AR ({batch_id})</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@600;700&family=IBM+Plex+Sans+Arabic:wght@400;500;700&family=Noto+Sans+Arabic:wght@400;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0d1117;
      --card: #161b22;
      --border: #30363d;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #2ec4b6;
      --warn: #f85149;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--text);
      font-family: 'IBM Plex Sans Arabic', 'Noto Sans Arabic', sans-serif;
    }}
    header {{
      margin-bottom: 20px;
      padding: 16px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    h1 {{ margin: 0 0 8px 0; font-family: 'Cairo', sans-serif; font-size: 22px; }}
    .meta {{ color: var(--muted); font-size: 14px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border: 1px solid var(--border);
    }}
    th, td {{
      padding: 12px 14px;
      border: 1px solid var(--border);
      vertical-align: top;
    }}
    th {{ background: #21262d; text-align: right; }}
    .id-cell {{ font-family: monospace; color: var(--accent); text-align: left; width: 22%; }}
    .preview-plex {{ font-family: 'IBM Plex Sans Arabic', sans-serif; width: 50%; }}
    .preview-cairo {{ font-family: 'Cairo', sans-serif; font-weight: 700; width: 28%; }}
    .sz-14 {{ font-size: 14px; color: var(--muted); margin-bottom: 4px; }}
    .sz-20 {{ font-size: 20px; margin-bottom: 4px; }}
    .sz-28 {{ font-size: 28px; font-weight: 700; }}
    .warn {{ margin-top: 6px; color: var(--warn); font-size: 13px; }}
  </style>
</head>
<body>
  <header>
    <h1>معاينة الترقيع النصي ودعم RTL — GTA6AR</h1>
    <div class="meta">
      الدفعة: <code>{batch_id}</code> · المجال: <code>{domain}</code> · النموذج: <code>{model_info}</code> ·
      الخطوط المرخّصة (SIL OFL 1.1): <b>IBM Plex Sans Arabic</b> و <b>Cairo</b> و <b>Noto Sans Arabic</b>
    </div>
  </header>
  <table>
    <thead>
      <tr>
        <th>المعرّف / String ID</th>
        <th>IBM Plex Sans Arabic (14px / 20px / 28px)</th>
        <th>Cairo Bold (عناوين ولافتات)</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GTA6AR Generic Text Extractor, Injector & RTL Preview Tool."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # extract subcommand
    p_ext = sub.add_parser("extract", help="Extract strings via adapter into a batch JSON.")
    p_ext.add_argument("--input", required=True, type=Path, help="Input string table path.")
    p_ext.add_argument("--output", required=True, type=Path, help="Output batch JSON path.")
    p_ext.add_argument("--adapter", default="auto", choices=["auto", "json", "csv", "ini"])
    p_ext.add_argument("--domain", default="ui", choices=["ui", "subtitles", "missions"])
    p_ext.add_argument("--batch-id", default="extracted-batch-001")
    p_ext.add_argument(
        "--with-source-text",
        action="store_true",
        help="Include 'source_en' in output for local translation (never commit source game text).",
    )

    # inject subcommand
    p_inj = sub.add_parser("inject", help="Inject a .patch.json into a local target file.")
    p_inj.add_argument("--source", required=True, type=Path, help="Original target file.")
    p_inj.add_argument("--patch", required=True, type=Path, help="Arabic .patch.json file.")
    p_inj.add_argument("--output", required=True, type=Path, help="Output patched file.")
    p_inj.add_argument("--adapter", default="auto", choices=["auto", "json", "csv", "ini"])
    p_inj.add_argument("--no-verify-hash", action="store_true", help="Skip SHA-256 hash check.")
    p_inj.add_argument("--shape", action="store_true", help="Apply Arabic presentation shaping.")
    p_inj.add_argument(
        "--bidi-isolate",
        action="store_true",
        help="Wrap Arabic strings and placeholders in Unicode BiDi isolates.",
    )

    # preview subcommand
    p_prv = sub.add_parser("preview", help="Generate an RTL HTML preview of a .patch.json file.")
    p_prv.add_argument("--patch", required=True, type=Path, help="Arabic .patch.json file.")
    p_prv.add_argument("--output", required=True, type=Path, help="Output HTML file path.")

    args = parser.parse_args(argv)

    try:
        if args.command == "extract":
            adapter = resolve_adapter(args.adapter, args.input)
            content = args.input.read_text(encoding="utf-8")
            batch_doc = extract_to_batch(
                source_content=content,
                adapter=adapter,
                domain=args.domain,
                batch_id=args.batch_id,
                include_source_text=args.with_source_text,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(batch_doc, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[OK] Extracted {len(batch_doc['entries'])} entries to '{args.output}'.")
            return 0

        if args.command == "inject":
            adapter = resolve_adapter(args.adapter, args.source)
            src_content = args.source.read_text(encoding="utf-8")
            patch_doc = json.loads(args.patch.read_text(encoding="utf-8"))
            updated, count = inject_patch(
                original_content=src_content,
                patch_data=patch_doc,
                adapter=adapter,
                verify_hashes=not args.no_verify_hash,
                apply_shaping=args.shape,
                apply_bidi_isolate=args.bidi_isolate,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(updated, encoding="utf-8")
            print(f"[OK] Injected {count} Arabic strings into '{args.output}'.")
            return 0

        if args.command == "preview":
            patch_doc = json.loads(args.patch.read_text(encoding="utf-8"))
            html_out = render_rtl_preview_html(patch_doc)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(html_out, encoding="utf-8")
            print(f"[OK] Generated RTL preview HTML at '{args.output}'.")
            return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

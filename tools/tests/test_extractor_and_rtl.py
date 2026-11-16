#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for GTA6AR generic extractor/injector and Arabic RTL/shaping/numerals.

Tested exclusively on dummy strings — zero original game files or assets.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from rtl_shaper import (  # noqa: E402
    LRI,
    PDI,
    RLI,
    has_eastern_arabic_numerals,
    has_kashida,
    isolate_bidi_tokens,
    normalize_numerals,
    shape_arabic_text,
    visual_reorder_line,
)
from text_tool import (  # noqa: E402
    CsvTableAdapter,
    IniKeyValueAdapter,
    JsonKeyValueAdapter,
    detect_placeholders,
    extract_to_batch,
    inject_patch,
    render_rtl_preview_html,
    sha256_hex,
)


class RtlShapingAndExtractorTests(unittest.TestCase):
    def test_contextual_arabic_shaping_and_lam_alef_ligature(self) -> None:
        # "كتب": ك (initial \uFEDB) + ت (medial \uFE98) + ب (final \uFE90)
        shaped_ktb = shape_arabic_text("كتب")
        self.assertEqual(shaped_ktb, "\uFEDB\uFE98\uFE90")

        # "لا": mandatory Lam-Alef isolated ligature (\uFEFB)
        self.assertEqual(shape_arabic_text("لا"), "\uFEFB")

        # "الآن": ا (\uFE8D) + لآ (\uFEF5) + ن (\uFEE5)
        self.assertEqual(shape_arabic_text("الآن"), "\uFE8D\uFEF5\uFEE5")

    def test_diacritics_do_not_break_contextual_joining(self) -> None:
        # "كُتِبَ" should have the exact same base letter joining forms as "كتب"
        shaped_with_tashkeel = shape_arabic_text("كُتِبَ")
        base_glyphs = [ch for ch in shaped_with_tashkeel if ord(ch) >= 0xFE70]
        self.assertEqual("".join(base_glyphs), "\uFEDB\uFE98\uFE90")

    def test_numerals_and_kashida_policy(self) -> None:
        sample = "السرعة ١٢٠ كم/س"
        self.assertTrue(has_eastern_arabic_numerals(sample))
        normalized = normalize_numerals(sample)
        self.assertEqual(normalized, "السرعة 120 كم/س")
        self.assertFalse(has_eastern_arabic_numerals(normalized))
        self.assertTrue(has_kashida("حفـظ"))
        self.assertFalse(has_kashida("حفظ"))

    def test_bidi_isolation_wraps_placeholders_and_rtl_line(self) -> None:
        raw = "اضغط على ~INPUT_ACCEPT~ لحفظ الخانة {0}."
        isolated = isolate_bidi_tokens(raw)
        self.assertTrue(isolated.startswith(RLI))
        self.assertTrue(isolated.endswith(PDI))
        self.assertIn(f"{LRI}~INPUT_ACCEPT~{PDI}", isolated)
        self.assertIn(f"{LRI}{{0}}{PDI}", isolated)

    def test_json_csv_ini_extract_and_inject_roundtrip(self) -> None:
        # 1. JSON adapter
        json_adapter = JsonKeyValueAdapter()
        src_path = ROOT / "text" / "samples" / "dummy_source_table.json"
        src_content = src_path.read_text(encoding="utf-8")

        batch = extract_to_batch(src_content, json_adapter, domain="ui", batch_id="b1")
        self.assertEqual(len(batch["entries"]), 3)
        self.assertIn("~INPUT_ACCEPT~", batch["entries"][1]["placeholders"])
        self.assertIn("{0}", batch["entries"][1]["placeholders"])

        patch_path = ROOT / "text" / "samples" / "dummy_patch_rtl.json"
        patch_data = json.loads(patch_path.read_text(encoding="utf-8"))
        # Sync hashes with dummy source table
        for entry in patch_data["entries"]:
            for rec in json_adapter.read_records(src_content):
                if rec.id == entry["id"]:
                    entry["source_hash"] = sha256_hex(rec.text)

        injected_json, count = inject_patch(
            original_content=src_content,
            patch_data=patch_data,
            adapter=json_adapter,
            verify_hashes=True,
        )
        self.assertEqual(count, 3)
        parsed_out = json.loads(injected_json)
        self.assertEqual(parsed_out["strings"][0]["text"], "القائمة الرئيسة")

        # 2. CSV adapter
        csv_adapter = CsvTableAdapter()
        csv_src = "id,text\nDUMMY_MENU_TITLE,Main Menu\n"
        injected_csv, csv_count = inject_patch(
            original_content=csv_src,
            patch_data=patch_data,
            adapter=csv_adapter,
            verify_hashes=False,
        )
        self.assertEqual(csv_count, 1)
        self.assertIn("القائمة الرئيسة", injected_csv)

        # 3. INI adapter (with section-qualified IDs, multiline escaping, BOM, and CRLF preservation)
        ini_adapter = IniKeyValueAdapter()
        crlf = chr(13) + chr(10)
        ini_src = (
            "\ufeff# Dummy config"
            + crlf
            + "[Menu]"
            + crlf
            + "TITLE = Main Menu"
            + crlf
            + "[Shop]"
            + crlf
            + "TITLE = Weapon Shop"
            + crlf
        )
        ini_records = ini_adapter.read_records(ini_src)
        self.assertEqual([r.id for r in ini_records], ["Menu.TITLE", "Shop.TITLE"])

        ini_patch = {
            "entries": [
                {"id": "Menu.TITLE", "ar": "القائمة الرئيسة"},
                {"id": "Shop.TITLE", "ar": "متجر المعدات\nالفرع الأول"},
            ]
        }
        injected_ini, ini_count = inject_patch(
            original_content=ini_src,
            patch_data=ini_patch,
            adapter=ini_adapter,
            verify_hashes=False,
        )
        self.assertEqual(ini_count, 2)
        self.assertIn("TITLE = القائمة الرئيسة" + crlf, injected_ini)
        self.assertIn("TITLE = متجر المعدات" + chr(92) + "nالفرع الأول" + crlf, injected_ini)

    def test_extended_placeholders_and_visual_order(self) -> None:
        sample = "Speed: %.2f km/h | Pos: %1$s | Cash: {0:N2} | <font color='red'>Alert</font>"
        phs = detect_placeholders(sample)
        self.assertEqual(phs, ["%.2f", "%1$s", "{0:N2}", "<font color='red'>", "</font>"])

        shaped = shape_arabic_text("كتب 10")
        reordered = visual_reorder_line(shaped)
        self.assertTrue(reordered.startswith("10"))
        self.assertTrue(reordered.endswith("\uFEDB"))

    def test_rtl_preview_html_generation(self) -> None:
        patch_path = ROOT / "text" / "samples" / "dummy_patch_rtl.json"
        patch_data = json.loads(patch_path.read_text(encoding="utf-8"))
        html_doc = render_rtl_preview_html(patch_data)
        self.assertIn('dir="rtl"', html_doc)
        self.assertIn("IBM Plex Sans Arabic", html_doc)
        self.assertIn("Cairo", html_doc)
        self.assertIn("القائمة الرئيسة", html_doc)


if __name__ == "__main__":
    unittest.main()

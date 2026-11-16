#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the GTA6AR translation pipeline and glossary consistency checker.

Tested exclusively on dummy strings — no original game files or assets.
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

from check_glossary import check_patch_data, format_markdown_report  # noqa: E402
from translate_pipeline import (  # noqa: E402
    ModelGateError,
    build_patch_document,
    enforce_model_gate,
    load_glossary,
)


class TranslationPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.glossary_path = ROOT / "text" / "glossary.json"
        self.glossary = load_glossary(self.glossary_path)
        self.valid_patch_path = ROOT / "text" / "samples" / "dummy_patch_valid.json"
        self.invalid_patch_path = ROOT / "text" / "samples" / "dummy_patch_invalid.json"
        self.input_batch_path = ROOT / "text" / "samples" / "dummy_input_batch.json"

    def test_model_gate_accepts_approved_models(self) -> None:
        self.assertEqual(enforce_model_gate("gemini-3.8-flash"), "3.8")
        self.assertEqual(enforce_model_gate("gemini-3.8-pro"), "3.8")
        self.assertEqual(enforce_model_gate("gemini-4-argon", "4.0"), "4.0")

    def test_model_gate_rejects_weaker_or_non_gemini_models(self) -> None:
        with self.assertRaises(ModelGateError):
            enforce_model_gate("gemini-2.5-flash")
        with self.assertRaises(ModelGateError):
            enforce_model_gate("gemini-1.5-flash", "3.8")
        with self.assertRaises(ModelGateError):
            enforce_model_gate("gemini-3.8-flash", "4.0")
        with self.assertRaises(ModelGateError):
            enforce_model_gate("gemini-3.5-flash")
        with self.assertRaises(ModelGateError):
            enforce_model_gate("gpt-4o-mini")

    def test_dry_run_pipeline_generates_valid_patch_without_source_text(self) -> None:
        input_data = json.loads(self.input_batch_path.read_text(encoding="utf-8"))
        patch = build_patch_document(
            input_data=input_data,
            glossary=self.glossary,
            model_name="gemini-3.8-flash",
            model_version="3.8",
            batch_size=2,
            dry_run=True,
            generated_at="2026-11-16T18:00:00Z",
        )
        self.assertEqual(patch["schema_version"], "1.0.0")
        self.assertIn("dry-run", patch["generator"]["model_name"])
        self.assertEqual(patch["generator"]["model_version"], "dry-run")
        self.assertEqual(len(patch["entries"]), 4)
        for entry in patch["entries"]:
            self.assertNotIn("source_en", entry)
            self.assertNotIn("Press ", entry["ar"])
            self.assertNotIn("Follow ", entry["ar"])
            self.assertEqual(len(entry["source_hash"]), 64)

        violations = check_patch_data(patch, self.glossary, file_label="dry_run.patch.json")
        self.assertIn("dry-run-not-allowed", {v.rule for v in violations})

    def test_glossary_checker_passes_valid_sample(self) -> None:
        valid_data = json.loads(self.valid_patch_path.read_text(encoding="utf-8"))
        valid_data["entries"].append(
            {
                "id": "DUMMY_FUSHA_CHECK",
                "ar": "هذا بالضبط ما يتطلبه إتمام المهمة بعد أن اطّلع القائد على ملف مولود جديد باهتمام.",
                "context_category": "dialogue",
            }
        )
        violations = check_patch_data(valid_data, self.glossary, file_label="dummy_patch_valid.json")
        self.assertEqual(violations, [])

    def test_glossary_checker_flags_forbidden_and_missing_terms(self) -> None:
        invalid_data = json.loads(self.invalid_patch_path.read_text(encoding="utf-8"))
        violations = check_patch_data(
            invalid_data,
            self.glossary,
            file_label="dummy_patch_invalid.json",
        )
        rules_triggered = {v.rule for v in violations}
        self.assertIn("forbidden-term", rules_triggered)
        self.assertIn("missing-glossary-term", rules_triggered)
        self.assertIn("missing-placeholder", rules_triggered)
        self.assertIn("max-chars-exceeded", rules_triggered)

        bad_schema_data = json.loads(self.valid_patch_path.read_text(encoding="utf-8"))
        bad_schema_data["entries"][0]["source_en"] = "Start Game"
        schema_violations = check_patch_data(bad_schema_data, self.glossary, file_label="bad.json")
        self.assertIn("schema-additional-property", {v.rule for v in schema_violations})

        report = format_markdown_report(["dummy_patch_invalid.json"], violations)
        self.assertIn("FAIL", report)


if __name__ == "__main__":
    unittest.main()

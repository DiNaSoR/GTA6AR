#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the GTA6AR Voice Dubbing (ElevenLabs v4+) and Image (Sunburn+) pipelines.

Tested exclusively on dummy metadata — zero game audio or textures.
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

from image_pipeline import (  # noqa: E402
    ImageModelGateError,
    build_image_manifest,
    enforce_image_model_gate,
    validate_arabic_image_item,
)
from voice_pipeline import (  # noqa: E402
    VoiceModelGateError,
    align_line_timing,
    build_voice_manifest,
    enforce_voice_model_gate,
)


class VoiceAndImagePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = json.loads(
            (ROOT / "audio" / "profiles" / "voice_profiles.json").read_text(encoding="utf-8")
        )
        self.voice_batch = json.loads(
            (ROOT / "audio" / "samples" / "dummy_voice_batch.json").read_text(encoding="utf-8")
        )
        self.visual_catalog = json.loads(
            (ROOT / "images" / "catalog" / "visual_categories.json").read_text(encoding="utf-8")
        )
        self.image_batch = json.loads(
            (ROOT / "images" / "samples" / "dummy_image_batch.json").read_text(encoding="utf-8")
        )

    def test_voice_model_gate_accepts_elevenlabs_v4_and_rejects_weaker(self) -> None:
        self.assertEqual(enforce_voice_model_gate("eleven_v4"), "4.0")
        self.assertEqual(enforce_voice_model_gate("eleven_multilingual_v4.2"), "4.2")
        with self.assertRaises(VoiceModelGateError):
            enforce_voice_model_gate("eleven_multilingual_v2")
        with self.assertRaises(VoiceModelGateError):
            enforce_voice_model_gate("eleven_turbo_v2.5")
        with self.assertRaises(VoiceModelGateError):
            enforce_voice_model_gate("generic-tts-v1")

    def test_voice_timing_alignment_and_manifest_generation(self) -> None:
        manifest = build_voice_manifest(
            batch_data=self.voice_batch,
            profiles_data=self.profiles,
            model_name="eleven_v4",
            model_version="4.0",
            generated_at="2026-11-16T19:00:00Z",
        )
        self.assertEqual(manifest["generator"]["model_name"], "eleven_v4")
        self.assertEqual(len(manifest["items"]), 3)
        statuses = [item["timing_alignment"]["alignment_status"] for item in manifest["items"]]
        self.assertIn("OK", statuses)
        self.assertIn("REGENERATE_SHORTEN_TEXT", statuses)

        ok_align = align_line_timing("تأكيد الوصول الآن.", target_duration_ms=1300, chars_per_sec=14.0)
        self.assertEqual(ok_align["alignment_status"], "OK")

    def test_image_model_gate_accepts_sunburn_and_rejects_weaker(self) -> None:
        self.assertEqual(enforce_image_model_gate("openai-sunburn", "1.0"), "1.0")
        self.assertEqual(enforce_image_model_gate("sunburn-v2"), "2")
        with self.assertRaises(ImageModelGateError):
            enforce_image_model_gate("dall-e-3")
        with self.assertRaises(ImageModelGateError):
            enforce_image_model_gate("sdxl")

    def test_image_manifest_and_arabic_in_image_qa_standards(self) -> None:
        manifest = build_image_manifest(
            batch_data=self.image_batch,
            catalog=self.visual_catalog,
            model_name="openai-sunburn",
            model_version="1.0",
            generated_at="2026-11-16T19:00:00Z",
        )
        self.assertEqual(len(manifest["items"]), 2)
        self.assertEqual(manifest["items"][0]["visual_qa_status"], "PASS")

        bad_item = {
            "id": "BAD_SIGN",
            "category_id": "cat.road_and_transit_signs",
            "arabic_text": "م و ق ف خ ا ص",
            "font_family": "Arial",
            "font_size_px": 14,
            "contrast_ratio": 2.1,
            "direction": "LTR",
        }
        errors = validate_arabic_image_item(bad_item, self.visual_catalog)
        self.assertEqual(len(errors), 5)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTA6AR Arabic Voice Dubbing Pipeline (`tools/voice_pipeline.py`).

Implements Milestone 5 (Issues #15, #16, #17, #18):
1. Enforces the minimum voice synthesis model gate: ElevenLabs v4 or stronger
   (rejects v1/v2/v2.5/v3 or non-approved models).
2. Loads reusable character voice profiles from `audio/profiles/voice_profiles.json`.
3. Computes scene timing alignment against `timing_ms` (`end - start`),
   recommending speaking-rate adjustments or flagging lines that need regeneration.
4. Outputs a structured `.voice.json` manifest with model/version logging and
   Fusha pronunciation QA checklist fields, without storing any original game audio.
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
MIN_ELEVENLABS_VERSION = (4, 0)
MAX_SAFE_SPEAKING_RATE = 1.18
MIN_SAFE_SPEAKING_RATE = 0.85
TIMING_TOLERANCE_RATIO = 0.12  # +/- 12%


class VoiceModelGateError(ValueError):
    """Raised when the voice model is weaker than ElevenLabs v4."""


def enforce_voice_model_gate(model_name: str, explicit_version: str | None = None) -> str:
    """Validate that `model_name` is ElevenLabs v4 or stronger."""
    norm = model_name.strip().lower()
    if not ("eleven" in norm or "11labs" in norm):
        raise VoiceModelGateError(
            f"Rejected voice model '{model_name}': minimum approved model is ElevenLabs v4."
        )

    candidates = []
    if explicit_version:
        candidates.append(explicit_version.strip())
    candidates.append(norm)

    for text in candidates:
        m = re.search(r"v?(\d+)(?:\.(\d+))?", text)
        if m:
            major = int(m.group(1))
            minor = int(m.group(2) or 0)
            if (major, minor) < MIN_ELEVENLABS_VERSION:
                raise VoiceModelGateError(
                    f"Rejected voice model '{model_name}' (v{major}.{minor}): "
                    "minimum approved model is ElevenLabs v4 (>= 4.0)."
                )
            return f"{major}.{minor}"

    raise VoiceModelGateError(
        f"Could not determine version for voice model '{model_name}'. Specify >= 4.0."
    )


def estimate_speech_duration_ms(ar_text: str, chars_per_sec: float, speaking_rate: float = 1.0) -> int:
    """Estimate spoken duration in milliseconds for an Arabic Fusha line."""
    clean = re.sub(r"\s+", " ", ar_text).strip()
    effective_cps = max(1.0, chars_per_sec * max(0.5, speaking_rate))
    seconds = len(clean) / effective_cps
    return int(round(seconds * 1000))


def align_line_timing(
    ar_text: str,
    target_duration_ms: int,
    chars_per_sec: float = 14.0,
    base_rate: float = 1.0,
) -> dict[str, Any]:
    """Compare estimated speech duration against scene window `target_duration_ms`."""
    if target_duration_ms <= 0:
        raise ValueError("target_duration_ms must be positive.")

    est_ms = estimate_speech_duration_ms(ar_text, chars_per_sec, base_rate)
    delta_ms = est_ms - target_duration_ms
    ratio = est_ms / float(target_duration_ms)

    if abs(1.0 - ratio) <= TIMING_TOLERANCE_RATIO:
        status = "OK"
        rec_rate = round(base_rate, 2)
    elif ratio > 1.0:
        needed_rate = round(base_rate * ratio, 2)
        if needed_rate <= MAX_SAFE_SPEAKING_RATE:
            status = "ADJUST_SPEAKING_RATE"
            rec_rate = needed_rate
        else:
            status = "REGENERATE_SHORTEN_TEXT"
            rec_rate = MAX_SAFE_SPEAKING_RATE
    else:
        needed_rate = round(base_rate * ratio, 2)
        if needed_rate >= MIN_SAFE_SPEAKING_RATE:
            status = "ADJUST_SPEAKING_RATE"
            rec_rate = needed_rate
        else:
            status = "PAD_PAUSE_OR_EXPAND"
            rec_rate = MIN_SAFE_SPEAKING_RATE

    return {
        "target_duration_ms": target_duration_ms,
        "estimated_duration_ms": est_ms,
        "delta_ms": delta_ms,
        "ratio": round(ratio, 3),
        "recommended_speaking_rate": rec_rate,
        "alignment_status": status,
    }


def build_voice_manifest(
    batch_data: dict[str, Any],
    profiles_data: dict[str, Any],
    model_name: str,
    model_version: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Generate a complete `.voice.json` dubbing manifest with timing alignment and QA metadata."""
    resolved_version = enforce_voice_model_gate(model_name, model_version)
    profiles_by_id = {
        p["role_id"]: p for p in profiles_data.get("profiles", []) if "role_id" in p
    }

    scene_id = batch_data.get("scene_id", "scene-001")
    lines = batch_data.get("lines", [])
    if not lines:
        raise ValueError("Voice batch contains no lines.")

    manifest_items: list[dict[str, Any]] = []
    for line in lines:
        lid = line["id"]
        role_id = line["role_id"]
        if role_id not in profiles_by_id:
            raise KeyError(f"Unknown voice profile role_id '{role_id}' for line '{lid}'.")

        profile = profiles_by_id[role_id]
        timing = line["timing_ms"]
        target_ms = int(timing["end"]) - int(timing["start"])
        cps = float(profile.get("chars_per_sec_baseline", 14.0))
        base_rate = float(profile.get("settings", {}).get("speaking_rate", 1.0))

        alignment = align_line_timing(
            ar_text=line["ar"],
            target_duration_ms=target_ms,
            chars_per_sec=cps,
            base_rate=base_rate,
        )

        manifest_items.append(
            {
                "id": lid,
                "role_id": role_id,
                "ar": line["ar"],
                "output_audio_path": f"audio/generated/{scene_id}/{lid}.ogg",
                "voice_settings": {
                    **profile.get("settings", {}),
                    "speaking_rate": alignment["recommended_speaking_rate"],
                },
                "timing_alignment": alignment,
                "fusha_pronunciation_qa": {
                    "status": "PENDING_LISTENING_QA",
                    "checks": [
                        "articulation_and_grammar_endings",
                        "hamzat_wasl_and_solar_lam",
                        "character_tone_consistency",
                        "zero_audio_artifacts",
                    ],
                },
            }
        )

    timestamp = generated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": "1.0.0",
        "scene_id": scene_id,
        "generated_at": timestamp,
        "generator": {
            "model_name": model_name,
            "model_version": resolved_version,
            "pipeline_version": PIPELINE_VERSION,
            "profiles_version": profiles_data.get("profiles_version", "1.0.0"),
        },
        "items": manifest_items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the GTA6AR ElevenLabs v4+ Arabic voice dubbing pipeline."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input voice batch JSON.")
    parser.add_argument("--output", required=True, type=Path, help="Output .voice.json manifest.")
    parser.add_argument(
        "--profiles",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "audio"
        / "profiles"
        / "voice_profiles.json",
        help="Path to voice_profiles.json.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GTA6AR_VOICE_MODEL", "eleven_v4"),
        help="ElevenLabs model identifier (must be v4 or stronger).",
    )
    parser.add_argument(
        "--model-version",
        default=os.environ.get("GTA6AR_VOICE_VERSION", "4.0"),
        help="Explicit model version (>= 4.0).",
    )
    args = parser.parse_args(argv)

    try:
        batch_data = json.loads(args.input.read_text(encoding="utf-8"))
        profiles_data = json.loads(args.profiles.read_text(encoding="utf-8"))
        manifest = build_voice_manifest(
            batch_data=batch_data,
            profiles_data=profiles_data,
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
        f"[OK] Generated voice dubbing manifest '{args.output}' "
        f"({len(manifest['items'])} lines, model={manifest['generator']['model_name']} "
        f"v{manifest['generator']['model_version']})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

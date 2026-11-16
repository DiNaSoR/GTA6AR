#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTA6AR Unified Command-Line Interface (`tools/gta6ar.py`).

Provides a single unified entry point for contributors and CI to run:
- `status`    : Inspect installed pipeline modules, schemas, and sample assets.
- `clean`     : Run the repository cleanliness & zero-game-assets gate.
- `check`     : Run glossary, placeholder, length, and MSA register checks.
- `translate` : Run the Gemini 3.8 Flash+ translation pipeline.
- `text`      : Run the general text extractor/injector/RTL preview tool.
- `voice`     : Run the ElevenLabs v4+ voice dubbing & timing alignment pipeline.
- `image`     : Run the OpenAI Sunburn+ Arabic image localization pipeline.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent

MODULES = [
    ("verify_repo_cleanliness.py", "Legal & Security Cleanliness Gate (#1, #23)"),
    ("translate_pipeline.py", "Gemini 3.8 Flash+ Translation Pipeline (#8)"),
    ("check_glossary.py", "Glossary, Placeholder & Fusha QA Checker (#9)"),
    ("text_tool.py", "String Extractor, Patch Injector & RTL Preview (#5, #13)"),
    ("rtl_shaper.py", "Arabic Contextual Shaper & BiDi Isolator (#13, #14)"),
    ("voice_pipeline.py", "ElevenLabs v4+ Voice Dubbing & Timing Engine (#15-#18)"),
    ("image_pipeline.py", "OpenAI Sunburn+ Image Localization Pipeline (#19-#21)"),
]


def cmd_status() -> int:
    print("============================================================")
    print(" GTA6AR — Unified AI Localization Pipeline Status")
    print("============================================================")
    available = 0
    for filename, description in MODULES:
        path = TOOLS_DIR / filename
        exists = path.is_file()
        if exists:
            available += 1
        badge = "[READY]" if exists else "[MISSING]"
        print(f" {badge:9s} tools/{filename:28s} — {description}")
    print("------------------------------------------------------------")
    print(f" Modules available in current branch: {available}/{len(MODULES)}")
    return 0


def delegate_script(script_name: str, extra_args: list[str]) -> int:
    script_path = TOOLS_DIR / script_name
    if not script_path.is_file():
        print(
            f"[ERROR] Module 'tools/{script_name}' is not present in this branch yet.",
            file=sys.stderr,
        )
        return 1
    cmd = [sys.executable, str(script_path), *extra_args]
    completed = subprocess.run(cmd, check=False)
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gta6ar",
        description="GTA6AR Unified CLI for AI Translation, Voice Dubbing, Images, and QA.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    sub.add_parser("status", help="Show pipeline modules status.")
    sub.add_parser("clean", help="Verify zero game files and zero secrets in repo.")
    sub.add_parser("check", help="Run glossary & Fusha consistency checker.")
    sub.add_parser("translate", help="Run Gemini 3.8 Flash+ translation pipeline.")
    sub.add_parser("text", help="Run extract / inject / preview text tool.")
    sub.add_parser("voice", help="Run ElevenLabs v4+ voice dubbing pipeline.")
    sub.add_parser("image", help="Run OpenAI Sunburn+ image localization pipeline.")

    args, remaining = parser.parse_known_args(argv)

    dispatch_map = {
        "clean": "verify_repo_cleanliness.py",
        "check": "check_glossary.py",
        "translate": "translate_pipeline.py",
        "text": "text_tool.py",
        "voice": "voice_pipeline.py",
        "image": "image_pipeline.py",
    }

    if args.subcommand == "status":
        if remaining:
            parser.error(f"unrecognized arguments: {' '.join(remaining)}")
        return cmd_status()

    return delegate_script(dispatch_map[args.subcommand], remaining)


if __name__ == "__main__":
    sys.exit(main())

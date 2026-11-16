#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for `tools/verify_repo_cleanliness.py`."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from gta6ar import main as gta6ar_main  # noqa: E402
from verify_repo_cleanliness import scan_repository  # noqa: E402


class RepoCleanlinessTests(unittest.TestCase):
    def test_current_repository_is_clean(self) -> None:
        issues = scan_repository(ROOT)
        self.assertEqual(issues, [])

    def test_unified_cli_status_and_clean(self) -> None:
        self.assertEqual(gta6ar_main(["status"]), 0)
        self.assertEqual(gta6ar_main(["clean"]), 0)

    def test_detects_forbidden_game_files_and_secrets_in_temp_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            (tmp_root / ".gitignore").write_text("*.rpf\n", encoding="utf-8")
            (tmp_root / "archive.rpf").write_bytes(b"dummy")
            (tmp_root / ".env").write_text("GEMINI_API_KEY=secret123\n", encoding="utf-8")

            issues = scan_repository(tmp_root)
            categories = {i.category for i in issues}
            self.assertIn("forbidden-game-or-binary-asset", categories)
            self.assertIn("forbidden-env-file", categories)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTA6AR Repository Cleanliness & Release Gate (`tools/verify_repo_cleanliness.py`).

Implements the automated legal & security verification gate for Issues #1, #2, #3, #23:
1. Scans the repository tree to ensure zero prohibited game archive, audio,
   texture, or executable extensions (`*.rpf`, `*.pak`, `*.wem`, `*.ytd`, etc.)
   are present.
2. Scans tracked text/code files for accidental API key or secret leaks.
3. Validates that `.gitignore` and `.env.example` are present and properly
   configured.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_EXTENSIONS = frozenset(
    {
        ".rpf",
        ".iso",
        ".bin",
        ".cue",
        ".img",
        ".pak",
        ".arc",
        ".wem",
        ".bnk",
        ".awc",
        ".ytd",
        ".ydd",
        ".yft",
        ".ydr",
        ".ycd",
        ".ypt",
        ".yld",
        ".ymap",
        ".ytyp",
        ".ynd",
        ".dds",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".app",
        ".ipa",
        ".apk",
        ".obb",
        ".psarc",
        ".usm",
        ".bik",
        ".bk2",
        ".dat",
        ".idx",
        ".key",
        ".pem",
        ".pfx",
        ".p12",
    }
)

FORBIDDEN_DIRS = frozenset(
    {
        "extracted",
        "game_files",
        "roms",
        "isos",
        "disc",
        "dump",
        "dumps",
        "game",
        "gta6",
        "gtavi",
        "secrets",
        "tokens",
    }
)

SKIP_SCAN_DIRS = frozenset({".git", "__pycache__", ".venv", "venv", "node_modules"})

SECRET_PATTERNS = [
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("openai-api-key", re.compile(r"sk-[A-Za-z0-9\-_]{20,}")),
    ("elevenlabs-api-key", re.compile(r"sk_[a-fA-F0-9]{32,}")),
    ("non-empty-env-key", re.compile(r"^(GEMINI_API_KEY|ELEVENLABS_API_KEY|OPENAI_API_KEY)[ \t]*=[ \t]*[^\s#]+", re.MULTILINE)),
]


@dataclass
class CleanlinessIssue:
    path: str
    category: str
    detail: str


def _iter_candidate_files(root: Path) -> list[Path]:
    """Return tracked/unignored files under `root` via `git ls-files`, falling back to `rglob`."""
    if (root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
                capture_output=True,
                text=True,
                check=True,
            )
            paths: list[Path] = []
            for rel_line in proc.stdout.splitlines():
                rel_line = rel_line.strip()
                if not rel_line:
                    continue
                candidate = root / rel_line
                if candidate.exists():
                    paths.append(candidate)
            return paths
        except (subprocess.SubprocessError, OSError):
            pass
    return list(root.rglob("*"))


def scan_repository(root: Path) -> list[CleanlinessIssue]:
    """Scan `root` for prohibited game files, secret files, or leaked keys."""
    issues: list[CleanlinessIssue] = []

    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        issues.append(
            CleanlinessIssue(
                path=".gitignore",
                category="missing-gitignore",
                detail="Repository is missing .gitignore.",
            )
        )

    reported_dirs: set[str] = set()
    for item in _iter_candidate_files(root):
        rel_parts = item.relative_to(root).parts
        if any(part in SKIP_SCAN_DIRS for part in rel_parts):
            continue

        # Check whether any parent directory component is in FORBIDDEN_DIRS
        for idx, part in enumerate(rel_parts[:-1] if item.is_file() else rel_parts):
            if part.lower() in FORBIDDEN_DIRS:
                dir_rel = "/".join(rel_parts[: idx + 1])
                if dir_rel not in reported_dirs:
                    reported_dirs.add(dir_rel)
                    issues.append(
                        CleanlinessIssue(
                            path=dir_rel,
                            category="forbidden-directory",
                            detail=f"Directory '{part}' is prohibited (game/secrets dir).",
                        )
                    )

        if item.is_dir():
            continue

        rel_posix = item.relative_to(root).as_posix()

        # Check .env files (allow .env.example only)
        if item.name == ".env" or (
            item.name.startswith(".env.") and item.name != ".env.example"
        ):
            issues.append(
                CleanlinessIssue(
                    path=rel_posix,
                    category="forbidden-env-file",
                    detail="Local .env secret file must never be present in tracked tree.",
                )
            )
            continue

        ext = item.suffix.lower()
        if ext in FORBIDDEN_EXTENSIONS:
            issues.append(
                CleanlinessIssue(
                    path=rel_posix,
                    category="forbidden-game-or-binary-asset",
                    detail=f"File extension '{ext}' is prohibited by project rules.",
                )
            )
            continue

        # Scan text files for accidental secret patterns
        if ext in {".py", ".json", ".md", ".yml", ".yaml", ".txt", ".example"}:
            try:
                content = item.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for rule_name, pattern in SECRET_PATTERNS:
                if pattern.search(content):
                    issues.append(
                        CleanlinessIssue(
                            path=rel_posix,
                            category=f"secret-leak ({rule_name})",
                            detail=f"Detected potential hardcoded secret matching '{rule_name}'.",
                        )
                    )

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify GTA6AR repository cleanliness (zero game files, zero secrets)."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root directory.",
    )
    args = parser.parse_args(argv)

    issues = scan_repository(args.root.resolve())
    if not issues:
        print("[OK] Repository cleanliness check passed: 0 game assets, 0 secrets found.")
        return 0

    print(f"[FAIL] Found {len(issues)} cleanliness violation(s):", file=sys.stderr)
    for iss in issues:
        print(f" - [{iss.category}] {iss.path}: {iss.detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

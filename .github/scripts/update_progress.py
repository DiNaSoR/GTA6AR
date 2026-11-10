#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recompute the README progress table from open vs closed issues per area label.

Only the block between <!-- progress-table:start --> and <!-- progress-table:end -->
is rewritten. No other file is modified. Exits 0 even if nothing changed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "DiNaSoR/GTA6AR")
README = Path(__file__).resolve().parents[2] / "README.md"
START = "<!-- progress-table:start -->"
END = "<!-- progress-table:end -->"

AREAS = [
    {
        "key": "area:translation",
        "ar": "الترجمة",
        "en": "Translation",
        "color": "2EC4B6",
        "badge": "translation",
        "milestones": [3],
    },
    {
        "key": "area:voice",
        "ar": "الدبلجة",
        "en": "Voice",
        "color": "7B61FF",
        "badge": "voice",
        "milestones": [5],
    },
    {
        "key": "area:images",
        "ar": "الصور",
        "en": "Images",
        "color": "FF7A45",
        "badge": "images",
        "milestones": [6],
    },
    {
        "key": "area:fonts",
        "ar": "الخطوط وRTL",
        "en": "Fonts & RTL",
        "color": "E8B923",
        "badge": "fonts",
        "milestones": [4],
    },
    {
        "key": "area:tools",
        "ar": "الأدوات",
        "en": "Tools",
        "color": "3D8BFF",
        "badge": "tools",
        "milestones": [1, 2],
    },
    {
        "key": "area:qa",
        "ar": "الجودة والإصدار",
        "en": "QA & Release",
        "color": "E85D8C",
        "badge": "qa",
        "milestones": [7],
    },
]

MILESTONE_TITLES = {
    1: "الإعداد",
    2: "الأدوات",
    3: "الترجمة",
    4: "الخطوط",
    5: "الدبلجة",
    6: "الصور",
    7: "الإصدار 1.0",
}


def repo_url() -> str:
    return f"https://github.com/{REPO}"


def gh_api(path: str):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        # Fall back to the gh CLI so a local run does not need a printed token.
        r = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            raise RuntimeError(f"gh api {path} failed: {r.stderr.strip()}")
        return json.loads(r.stdout)
    url = "https://api.github.com/" + path.lstrip("/")
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GTA6AR-progress-updater",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_issues():
    items = []
    page = 1
    while True:
        path = (
            f"repos/{REPO}/issues?state=all&per_page=100&page={page}"
            "&filter=all"
        )
        batch = gh_api(path)
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 20:
            break
    # Exclude pull requests (the issues API also returns PRs).
    return [i for i in items if "pull_request" not in i]


def bar(pct: int) -> str:
    filled = min(10, max(0, int(round(pct / 10.0))))
    return "█" * filled + "░" * (10 - filled)


def badge_color(pct: int, default: str) -> str:
    if pct <= 0:
        return "8B949E"
    if pct >= 100:
        return "2DA44E"
    return default


def status_ar(pct: int, total: int) -> str:
    if total == 0:
        return "—"
    if pct >= 100:
        return "مكتمل"
    if pct <= 0:
        return "لم يبدأ"
    return "جارٍ"


def status_en(pct: int, total: int) -> str:
    if total == 0:
        return "—"
    if pct >= 100:
        return "Done"
    if pct <= 0:
        return "Not started"
    return "In progress"


def shield(label: str, value: str, color: str, link: str) -> str:
    # shields.io static badge; safe on a private repo (no API lookup).
    enc_label = urllib.parse.quote(label, safe="")
    enc_value = urllib.parse.quote(value, safe="")
    img = f"https://img.shields.io/badge/{enc_label}-{enc_value}-{color}"
    return f"[![{label}: {value}]({img})]({link})"


def milestone_links(numbers):
    parts = []
    for n in numbers:
        title = MILESTONE_TITLES.get(n, f"#{n}")
        parts.append(f"[{title}]({repo_url()}/milestone/{n})")
    return " · ".join(parts)


def issue_query(label: str) -> str:
    q = urllib.parse.quote(f"is:issue label:{label}")
    return f"{repo_url()}/issues?q={q}"


def pct(closed: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round(100.0 * closed / total))


def build_block(issues) -> str:
    by_area = {a["key"]: {"open": 0, "closed": 0} for a in AREAS}
    open_all = 0
    closed_all = 0
    for issue in issues:
        labels = {lab["name"] for lab in issue.get("labels", [])}
        is_closed = issue.get("state") == "closed"
        if is_closed:
            closed_all += 1
        else:
            open_all += 1
        for key in by_area:
            if key in labels:
                if is_closed:
                    by_area[key]["closed"] += 1
                else:
                    by_area[key]["open"] += 1

    total_all = open_all + closed_all
    overall = pct(closed_all, total_all)
    overall_color = badge_color(overall, "3D8BFF")

    badges = " ".join(
        [
            shield("overall", f"{overall}%", overall_color, f"{repo_url()}/milestones"),
            shield("open issues", str(open_all), "3D8BFF", f"{repo_url()}/issues"),
            shield("milestones", "7", "2EC4B6", f"{repo_url()}/milestones"),
        ]
    )

    rows = []
    for area in AREAS:
        stats = by_area[area["key"]]
        total = stats["open"] + stats["closed"]
        p = pct(stats["closed"], total)
        color = badge_color(p, area["color"])
        area_badge = shield(area["badge"], f"{p}%", color, issue_query(area["key"]))
        rows.append(
            "| {ar} / {en} | {badge} `{bar}` | {p}% ({closed}/{total}) | {st_ar} / {st_en} | {ms} |".format(
                ar=area["ar"],
                en=area["en"],
                badge=area_badge,
                bar=bar(p),
                p=p,
                closed=stats["closed"],
                total=total,
                st_ar=status_ar(p, total),
                st_en=status_en(p, total),
                ms=milestone_links(area["milestones"]),
            )
        )

    overall_badge = shield("overall", f"{overall}%", overall_color, f"{repo_url()}/milestones")
    rows.append(
        "| **الكلي / Overall** | {badge} `{bar}` | **{p}%** ({closed}/{total}) | {st_ar} / {st_en} | [المعالم]({url}/milestones) |".format(
            badge=overall_badge,
            bar=bar(overall),
            p=overall,
            closed=closed_all,
            total=total_all,
            st_ar=status_ar(overall, total_all),
            st_en=status_en(overall, total_all),
            url=repo_url(),
        )
    )

    table = "\n".join(
        [
            "| المجال | التقدّم | النسبة | الحالة | المَعلم |",
            "|---|---|---|---|---|",
            *rows,
        ]
    )

    return "\n".join(
        [
            START,
            badges,
            "",
            table,
            "",
            f"تُحتسب النسبة من القضايا المغلقة مقابل المفتوحة في كل تصنيف مجال. يُحدَّث الجدول بتشغيل `.github/scripts/update_progress.py`. "
            f"[كل القضايا]({repo_url()}/issues) · [المعالم]({repo_url()}/milestones)",
            END,
        ]
    )


def main() -> int:
    if not README.is_file():
        print(f"README not found: {README}", file=sys.stderr)
        return 1
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print("Progress markers missing in README.md", file=sys.stderr)
        return 1
    issues = list_issues()
    block = build_block(issues)
    new = re.sub(
        re.escape(START) + r".*?" + re.escape(END),
        lambda _m: block,
        text,
        count=1,
        flags=re.DOTALL,
    )
    if new == text:
        print("README progress table already up to date.")
        return 0
    README.write_text(new, encoding="utf-8")
    print("Updated README progress table.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

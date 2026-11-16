#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTA6AR Arabic Shaping, RTL BiDi, Diacritics & Numerals Toolkit (`tools/rtl_shaper.py`).

Zero-dependency utilities for:
1. Contextual Arabic letter shaping (Isolated, Final, Initial, Medial forms in
   Unicode Presentation Forms-B, plus mandatory Lam-Alef ligatures).
2. Transparent handling of Arabic diacritics (tashkeel) so vowel marks never
   break cursive joining between neighboring letters.
3. Unicode BiDi isolation (`RLI` / `LRI` / `PDI`) so mixed Arabic sentences
   containing Latin placeholders (`{0}`, `%s`, `~INPUT_ACCEPT~`), numbers, and
   punctuation render in the true right-to-left order.
4. Numerals & kashida validation/normalization (enforcing standard `0-9`
   numerals in UI and subtitles).
"""
from __future__ import annotations

import re

# Unicode BiDi Isolate Controls
RLI = "\u2067"  # Right-to-Left Isolate
LRI = "\u2066"  # Left-to-Right Isolate
PDI = "\u2069"  # Pop Directional Isolate
ALM = "\u061C"  # Arabic Letter Mark

TATWEEL = "\u0640"
DIACRITICS_SET = frozenset(chr(c) for c in range(0x064B, 0x0660)) | {"\u0670"}
EASTERN_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
WESTERN_DIGITS = "0123456789"
EASTERN_TO_WESTERN_TABLE = str.maketrans(EASTERN_ARABIC_DIGITS, WESTERN_DIGITS)

PLACEHOLDER_TOKEN_RE = re.compile(
    r"(~\w+~|\{[a-zA-Z0-9_]+(?::[^}]+)?\}|%(?:\d+\$)?[-+0# ]*\d*(?:\.\d+)?[sdifuxX%]|<[A-Za-z0-9_/][^>]*>)"
)

# Arabic letters mapping: base_char -> (isolated, final, initial, medial)
# Letters with 2 forms (right-joining only: ا أ إ آ د ذ ر ز و ؤ ء ة ى) have initial=isolated, medial=final.
ARABIC_FORMS: dict[str, tuple[str, str, str, str]] = {
    "\u0621": ("\uFE80", "\uFE80", "\uFE80", "\uFE80"),  # ء
    "\u0622": ("\uFE81", "\uFE82", "\uFE81", "\uFE82"),  # آ
    "\u0623": ("\uFE83", "\uFE84", "\uFE83", "\uFE84"),  # أ
    "\u0624": ("\uFE85", "\uFE86", "\uFE85", "\uFE86"),  # ؤ
    "\u0625": ("\uFE87", "\uFE88", "\uFE87", "\uFE88"),  # إ
    "\u0626": ("\uFE89", "\uFE8A", "\uFE8B", "\uFE8C"),  # ئ
    "\u0627": ("\uFE8D", "\uFE8E", "\uFE8D", "\uFE8E"),  # ا
    "\u0628": ("\uFE8F", "\uFE90", "\uFE91", "\uFE92"),  # ب
    "\u0629": ("\uFE93", "\uFE94", "\uFE93", "\uFE94"),  # ة
    "\u062A": ("\uFE95", "\uFE96", "\uFE97", "\uFE98"),  # ت
    "\u062B": ("\uFE99", "\uFE9A", "\uFE9B", "\uFE9C"),  # ث
    "\u062C": ("\uFE9D", "\uFE9E", "\uFE9F", "\uFEA0"),  # ج
    "\u062D": ("\uFEA1", "\uFEA2", "\uFEA3", "\uFEA4"),  # ح
    "\u062E": ("\uFEA5", "\uFEA6", "\uFEA7", "\uFEA8"),  # خ
    "\u062F": ("\uFEA9", "\uFEAA", "\uFEA9", "\uFEAA"),  # د
    "\u0630": ("\uFEAB", "\uFEAC", "\uFEAB", "\uFEAC"),  # ذ
    "\u0631": ("\uFEAD", "\uFEAE", "\uFEAD", "\uFEAE"),  # ر
    "\u0632": ("\uFEAF", "\uFEB0", "\uFEAF", "\uFEB0"),  # ز
    "\u0633": ("\uFEB1", "\uFEB2", "\uFEB3", "\uFEB4"),  # س
    "\u0634": ("\uFEB5", "\uFEB6", "\uFEB7", "\uFEB8"),  # ش
    "\u0635": ("\uFEB9", "\uFEBA", "\uFEBB", "\uFEBC"),  # ص
    "\u0636": ("\uFEBD", "\uFEBE", "\uFEBF", "\uFEC0"),  # ض
    "\u0637": ("\uFEC1", "\uFEC2", "\uFEC3", "\uFEC4"),  # ط
    "\u0638": ("\uFEC5", "\uFEC6", "\uFEC7", "\uFEC8"),  # ظ
    "\u0639": ("\uFEC9", "\uFECA", "\uFECB", "\uFECC"),  # ع
    "\u063A": ("\uFECD", "\uFECE", "\uFECF", "\uFED0"),  # غ
    "\u0641": ("\uFED1", "\uFED2", "\uFED3", "\uFED4"),  # ف
    "\u0642": ("\uFED5", "\uFED6", "\uFED7", "\uFED8"),  # ق
    "\u0643": ("\uFED9", "\uFEDA", "\uFEDB", "\uFEDC"),  # ك
    "\u0644": ("\uFEDD", "\uFEDE", "\uFEDF", "\uFEE0"),  # ل
    "\u0645": ("\uFEE1", "\uFEE2", "\uFEE3", "\uFEE4"),  # م
    "\u0646": ("\uFEE5", "\uFEE6", "\uFEE7", "\uFEE8"),  # ن
    "\u0647": ("\uFEE9", "\uFEEA", "\uFEEB", "\uFEEC"),  # ه
    "\u0648": ("\uFEED", "\uFEEE", "\uFEED", "\uFEEE"),  # و
    "\u0649": ("\uFEEF", "\uFEF0", "\uFEEF", "\uFEF0"),  # ى
    "\u064A": ("\uFEF1", "\uFEF2", "\uFEF3", "\uFEF4"),  # ي
}

RIGHT_JOIN_ONLY = frozenset(
    {
        "\u0621",  # ء (non-joining)
        "\u0622",  # آ
        "\u0623",  # أ
        "\u0624",  # ؤ
        "\u0625",  # إ
        "\u0627",  # ا
        "\u0629",  # ة
        "\u062F",  # د
        "\u0630",  # ذ
        "\u0631",  # ر
        "\u0632",  # ز
        "\u0648",  # و
        "\u0649",  # ى
    }
)

NON_JOINING = frozenset({"\u0621"})

# Lam + Alef ligatures: alef_char -> (isolated_ligature, final_ligature)
LAM_ALEF_LIGATURES: dict[str, tuple[str, str]] = {
    "\u0622": ("\uFEF5", "\uFEF6"),  # لآ
    "\u0623": ("\uFEF7", "\uFEF8"),  # لأ
    "\u0625": ("\uFEF9", "\uFEFA"),  # لإ
    "\u0627": ("\uFEFB", "\uFEFC"),  # لا
}


def is_diacritic(ch: str) -> bool:
    """Return True if ch is an Arabic combining vowel/tashkeel mark."""
    return ch in DIACRITICS_SET


def can_join_left(ch: str) -> bool:
    """Return True if letter ch can connect to a following Arabic letter."""
    return (ch in ARABIC_FORMS or ch == TATWEEL) and ch not in RIGHT_JOIN_ONLY


def can_join_right(ch: str) -> bool:
    """Return True if letter ch can connect to a preceding Arabic letter."""
    return (ch in ARABIC_FORMS or ch == TATWEEL) and ch not in NON_JOINING


def _prev_base_char(chars: list[str], index: int) -> str | None:
    """Find the nearest preceding non-diacritic character."""
    j = index - 1
    while j >= 0:
        if not is_diacritic(chars[j]):
            return chars[j]
        j -= 1
    return None


def _next_base_index_and_char(chars: list[str], index: int) -> tuple[int | None, str | None]:
    """Find the index and value of the nearest following non-diacritic character."""
    j = index + 1
    while j < len(chars):
        if not is_diacritic(chars[j]):
            return j, chars[j]
        j += 1
    return None, None


def shape_arabic_text(text: str) -> str:
    """Convert logical Arabic text into contextual Presentation Forms-B glyphs.

    Preserves diacritics attached to their base letters and forms mandatory
    Lam-Alef ligatures (`لا`, `لأ`, `لإ`, `لآ`).
    """
    chars = list(text)
    out: list[str] = []
    skip_indices: set[int] = set()

    for i, ch in enumerate(chars):
        if i in skip_indices:
            continue

        if is_diacritic(ch):
            out.append(ch)
            continue

        if ch not in ARABIC_FORMS:
            out.append(ch)
            continue

        prev_ch = _prev_base_char(chars, i)
        next_idx, next_ch = _next_base_index_and_char(chars, i)
        joins_prev = prev_ch is not None and can_join_left(prev_ch) and can_join_right(ch)

        # Check for Lam-Alef ligature (ل followed by ا/أ/إ/آ, even with diacritics on Lam)
        if ch == "\u0644" and next_ch in LAM_ALEF_LIGATURES and next_idx is not None:
            iso_lig, fin_lig = LAM_ALEF_LIGATURES[next_ch]
            out.append(fin_lig if joins_prev else iso_lig)
            # Keep any diacritics that sat between Lam and Alef
            for mid in range(i + 1, next_idx):
                if is_diacritic(chars[mid]):
                    out.append(chars[mid])
            skip_indices.add(next_idx)
            continue

        joins_next = next_ch is not None and can_join_left(ch) and can_join_right(next_ch)
        isolated, final, initial, medial = ARABIC_FORMS[ch]

        if joins_prev and joins_next:
            out.append(medial)
        elif joins_prev and not joins_next:
            out.append(final)
        elif not joins_prev and joins_next:
            out.append(initial)
        else:
            out.append(isolated)

    return "".join(out)


def visual_reorder_line(text: str) -> str:
    """Reorder a shaped Arabic line into visual LTR order while keeping LTR runs intact.

    Intended only for legacy game UI renderers that lack any Unicode BiDi algorithm
    (`--visual-order` flag in `text_tool.py`).
    """
    ltr_run_re = re.compile(
        r"(~\w+~|\{[a-zA-Z0-9_]+(?::[^}]+)?\}|%(?:\d+\$)?[-+0# ]*\d*(?:\.\d+)?[sdifuxX%]|<[A-Za-z0-9_/][^>]*>|[A-Za-z0-9$.,:/+-]+)"
    )
    tokens: list[tuple[bool, str]] = []
    pos = 0
    for m in ltr_run_re.finditer(text):
        if m.start() > pos:
            tokens.append((False, text[pos : m.start()]))
        tokens.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        tokens.append((False, text[pos:]))

    mirror_pairs = str.maketrans("()[]{}<>«»", ")(][}{><»»"[:8] + "»«")
    visual_parts: list[str] = []
    for is_ltr, segment in reversed(tokens):
        if is_ltr:
            visual_parts.append(segment)
        else:
            # Keep combining diacritics attached after their base glyph when reversing
            clusters: list[str] = []
            for ch in segment:
                if is_diacritic(ch) and clusters:
                    clusters[-1] += ch
                else:
                    clusters.append(ch.translate(mirror_pairs))
            visual_parts.append("".join(reversed(clusters)))
    return "".join(visual_parts)


def isolate_bidi_tokens(text: str) -> str:
    """Wrap an Arabic string in RLI..PDI and isolate embedded Latin placeholders in LRI..PDI."""
    def _wrap_token(match: re.Match[str]) -> str:
        return f"{LRI}{match.group(0)}{PDI}"

    inner = PLACEHOLDER_TOKEN_RE.sub(_wrap_token, text)
    return f"{RLI}{inner}{PDI}"


def normalize_numerals(text: str) -> str:
    """Convert Eastern Arabic-Indic digits (٠-٩) to standard Western digits (0-9)."""
    return text.translate(EASTERN_TO_WESTERN_TABLE)


def has_eastern_arabic_numerals(text: str) -> bool:
    """Return True if text contains any Eastern Arabic-Indic digit (٠-٩)."""
    return any(ch in EASTERN_ARABIC_DIGITS for ch in text)


def has_kashida(text: str) -> bool:
    """Return True if text contains Arabic tatweel/kashida (ـ)."""
    return TATWEEL in text

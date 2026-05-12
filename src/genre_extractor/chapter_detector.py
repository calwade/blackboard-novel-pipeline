"""Multi-format chapter detection for genre extraction.

The old detector (pipeline._count_chapters_in_text) only recognised the
"第N章" Chinese standard pattern, so every novel using a different convention
got batched as a single chapter — extraction quality collapsed.

This module detects chapter boundaries across several common formats and
returns both a count and a list of character offsets for real splitting.

Supported formats (see module-level FORMATS for names):
    zh-standard  : 第N章 / 第N回 / 第N节 (N = digit or cn-numeral)
    en-standard  : Chapter N / CHAPTER N / Ch. N / Chapter One
    zh-ordinal   : 一、 / 二、 / 三、 ... as paragraph-leading markers
    roman        : I. / II. / III. ... as paragraph-leading markers
    numeric      : 1. / 2. / 3. ... (only when 3+ markers exist in the
                   first 1000 chars, to avoid in-body list enumerations)
    separator    : three or more consecutive "===" or "---" lines
    none         : nothing recognised — fall back to single chapter

Detection strategy (single pass, deterministic):
  1. Scan the full text for matches of each format.
  2. For "numeric", apply the first-1k-chars guard.
  3. Pick the format with the highest match count (ties broken by the
     priority order above).
  4. Use that format's regex to produce a sorted list of offsets.

The design goal is robustness on real-world scraped novels, not perfection;
the fallback is always "treat as one chapter", never crash.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Format regexes
# ---------------------------------------------------------------------------

# zh-standard: 第<num>[章|回|节]  — num is Arabic digits OR Chinese numerals
#   Must be at the start of a line (ignoring leading whitespace) to avoid
#   catching mid-paragraph references like "上一章" or "第一章讲的是...".
#   Examples matched: 第1章, 第 12 回, 第一百二十章, 第二节
_ZH_STANDARD_RE = re.compile(
    r"(?m)^[\s\u3000]*第[\s]*[0-9零〇一二两三四五六七八九十百千万]+[\s]*[章回节]"
)

# en-standard: Chapter N / CHAPTER N / Ch. N / Chapter One|Two|...
#   Must begin at start-of-line (after optional whitespace) to avoid catching
#   the word "chapter" inside a sentence.
_EN_WORD_NUMS = (
    "One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|"
    "Eleven|Twelve|Thirteen|Fourteen|Fifteen|Sixteen|Seventeen|"
    "Eighteen|Nineteen|Twenty"
)
_EN_STANDARD_RE = re.compile(
    r"(?m)^[ \t]*(?:"
    r"(?:Chapter|CHAPTER|chapter)\s+(?:\d+|" + _EN_WORD_NUMS + r")"
    r"|Ch\.\s*\d+"
    r")\b"
)

# zh-ordinal: 一、 / 二、 ... at paragraph start (start-of-line, not mid-text)
_ZH_ORDINAL_RE = re.compile(
    r"(?m)^[ \t]*[一二两三四五六七八九十百]+、"
)

# roman: I. / II. / III. / IV. / V. ... at line start, uppercase only to
# avoid false hits. At least one roman-numeral character is required.
_ROMAN_RE = re.compile(
    r"(?m)^[ \t]*"
    r"(?=[MDCLXVI])"  # must start with at least one roman char
    r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}|V)"
    r"\.\s"
)

# numeric: 1. / 2. / 3. at line start (guarded: only if 3+ within first 1k chars)
_NUMERIC_RE = re.compile(
    r"(?m)^[ \t]*\d{1,3}\.\s"
)

# separator: a line made entirely of === or --- (3+ chars), with content on both sides
_SEPARATOR_RE = re.compile(
    r"(?m)^[ \t]*(?:={3,}|-{3,})[ \t]*$"
)

FORMATS: Tuple[str, ...] = (
    "zh-standard",
    "en-standard",
    "zh-ordinal",
    "roman",
    "numeric",
    "separator",
)


# ---------------------------------------------------------------------------
# Internal: find raw match offsets for each format
# ---------------------------------------------------------------------------

def _numeric_qualifies(text: str) -> bool:
    """numeric format requires 3+ '1. / 2. / ...' markers in the first 1k chars.

    This guard stops in-body list enumerations ("1. apple 2. banana") from
    being misread as chapter starts.
    """
    head = text[:1000]
    head_matches = _NUMERIC_RE.findall(head)
    return len(head_matches) >= 3


def _raw_offsets(text: str, fmt: str) -> List[int]:
    if fmt == "zh-standard":
        return [m.start() for m in _ZH_STANDARD_RE.finditer(text)]
    if fmt == "en-standard":
        return [m.start() for m in _EN_STANDARD_RE.finditer(text)]
    if fmt == "zh-ordinal":
        return [m.start() for m in _ZH_ORDINAL_RE.finditer(text)]
    if fmt == "roman":
        return [m.start() for m in _ROMAN_RE.finditer(text)]
    if fmt == "numeric":
        if not _numeric_qualifies(text):
            return []
        return [m.start() for m in _NUMERIC_RE.finditer(text)]
    if fmt == "separator":
        # Each separator line marks a boundary; the resulting "chapters"
        # are what lies *between* separators, so count = matches + 1.
        # But for consistency with the other formats (count == number of
        # starting offsets), we treat offset 0 as chapter 1 start and each
        # position AFTER a separator as the next chapter start.
        offsets = [0]
        for m in _SEPARATOR_RE.finditer(text):
            # Next chapter starts right after this separator line.
            # Skip the trailing newline if present.
            end = m.end()
            if end < len(text) and text[end] == "\n":
                end += 1
            if end < len(text):
                offsets.append(end)
        return offsets
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_format(text: str) -> str:
    """Return the format name with the most matches.

    Ties are broken by the priority order in FORMATS. Returns "none" when
    no format has any match.
    """
    if not text:
        return "none"

    best_fmt = "none"
    best_count = 0
    for fmt in FORMATS:
        offsets = _raw_offsets(text, fmt)
        # For separator, the first offset (0) is synthetic; count only real
        # separator lines when comparing against other formats, so a doc
        # with no separators doesn't "win" with count=1.
        effective = len(offsets)
        if fmt == "separator":
            effective = max(effective - 1, 0)
        if effective > best_count:
            best_count = effective
            best_fmt = fmt
    return best_fmt


def find_chapter_splits(text: str) -> List[int]:
    """Return sorted character offsets where each chapter starts.

    The first offset is always 0 (start of document) so callers can slice
    ``text[splits[i]:splits[i+1]]`` for each chapter.

    On unrecognised format, returns ``[0]``.
    """
    if not text:
        return [0]

    fmt = detect_format(text)
    if fmt == "none":
        return [0]

    offsets = _raw_offsets(text, fmt)
    if not offsets:
        return [0]

    # Normalise: make sure 0 is the first offset (if the first marker is
    # not at position 0, the preamble still belongs to "chapter 1").
    if offsets[0] != 0:
        offsets = [0] + offsets

    # Deduplicate while preserving order, then sort (should already be sorted).
    seen = set()
    unique: List[int] = []
    for o in offsets:
        if o not in seen:
            seen.add(o)
            unique.append(o)
    unique.sort()
    return unique


def count_chapters(text: str) -> int:
    """Return the detected chapter count. Always >= 1."""
    splits = find_chapter_splits(text)
    return max(len(splits), 1)

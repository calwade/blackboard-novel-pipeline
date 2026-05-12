"""Tests for src.genre_extractor.chapter_detector.

Covers multi-format chapter detection used by the genre extraction pipeline
when it tears a novel into batches.
"""
from __future__ import annotations

import pytest

from src.genre_extractor import chapter_detector as cd


# ---------------------------------------------------------------------------
# Format: Chinese standard (第N章 / 第N回 / 第N节)
# ---------------------------------------------------------------------------
def _ch(marker: str, body: str, repeat: int = 10) -> str:
    """Helper: one chapter = 1 marker line + repeated body text."""
    return f"{marker}\n" + (body * repeat)


def test_detect_chinese_standard_num():
    text = "\n\n".join([
        _ch("第1章 开篇", "这是第一章的内容。"),
        _ch("第2章 风起", "这是第二章的内容。"),
        _ch("第3章 云涌", "这是第三章的内容。"),
    ])
    assert cd.detect_format(text) == "zh-standard"
    assert cd.count_chapters(text) == 3


def test_detect_chinese_standard_cn_num():
    text = "\n\n".join([
        _ch("第一章 起", "正文内容。"),
        _ch("第二章 承", "正文内容。"),
        _ch("第三章 转", "正文内容。"),
        _ch("第四章 合", "正文内容。"),
    ])
    assert cd.detect_format(text) == "zh-standard"
    assert cd.count_chapters(text) == 4


def test_detect_chinese_standard_hui():
    text = "\n\n".join([
        _ch("第一回 桃园结义", "话说天下大势。"),
        _ch("第二回 张飞怒鞭", "又说张飞之事。"),
        _ch("第三回 议温明", "再说温明议事。"),
    ])
    assert cd.detect_format(text) == "zh-standard"
    assert cd.count_chapters(text) == 3


def test_detect_chinese_standard_jie():
    text = "\n\n".join([
        _ch("第一节 绪论", "本节介绍基础内容。"),
        _ch("第二节 方法", "本节讨论方法论。"),
    ])
    assert cd.detect_format(text) == "zh-standard"
    assert cd.count_chapters(text) == 2


# ---------------------------------------------------------------------------
# Format: English standard (Chapter N / CHAPTER N / Ch. N / Chapter One)
# ---------------------------------------------------------------------------
def test_detect_english_chapter():
    text = "\n\n".join([
        _ch("Chapter 1", "Once upon a time there was a hobbit. "),
        _ch("Chapter 2", "The hobbit went on an adventure. "),
        _ch("Chapter 3", "He found a ring. "),
    ])
    assert cd.detect_format(text) == "en-standard"
    assert cd.count_chapters(text) == 3


def test_detect_english_chapter_uppercase():
    text = "\n\n".join([
        _ch("CHAPTER 1", "Opening lines of the tale. "),
        _ch("CHAPTER 2", "The plot thickens. "),
    ])
    assert cd.detect_format(text) == "en-standard"
    assert cd.count_chapters(text) == 2


def test_detect_english_ch_dot():
    text = "\n\n".join([
        _ch("Ch. 1", "First chapter body. "),
        _ch("Ch. 2", "Second chapter body. "),
        _ch("Ch. 3", "Third chapter body. "),
    ])
    assert cd.detect_format(text) == "en-standard"
    assert cd.count_chapters(text) == 3


def test_detect_english_word_num():
    text = "\n\n".join([
        _ch("Chapter One", "The beginning of the tale. "),
        _ch("Chapter Two", "Rising action. "),
        _ch("Chapter Three", "The climax is near. "),
    ])
    assert cd.detect_format(text) == "en-standard"
    assert cd.count_chapters(text) == 3


# ---------------------------------------------------------------------------
# Format: Chinese ordinal (一、/二、/三、) at paragraph start
# ---------------------------------------------------------------------------
def test_detect_zh_ordinal():
    text = "\n\n".join([
        _ch("一、", "这是第一部分的内容，讲述了故事的开端。"),
        _ch("二、", "这是第二部分的内容，讲述了故事的发展。"),
        _ch("三、", "这是第三部分的内容，讲述了故事的高潮。"),
        _ch("四、", "这是第四部分的内容，讲述了故事的结局。"),
    ])
    assert cd.detect_format(text) == "zh-ordinal"
    assert cd.count_chapters(text) == 4


def test_detect_zh_ordinal_not_in_body():
    # 一、in the middle of a paragraph should NOT count
    text = "这是一个长段落，其中提到一、某件事，二、另一件事。" * 20
    # Falls back to 1 chapter (none detected)
    assert cd.count_chapters(text) == 1


# ---------------------------------------------------------------------------
# Format: Roman numerals (I. / II. / III.)
# ---------------------------------------------------------------------------
def test_detect_roman():
    text = "\n\n".join([
        _ch("I.", "The first section of the novel begins here. ", 5),
        _ch("II.", "The second section continues the narrative arc. ", 5),
        _ch("III.", "The third section brings resolution. ", 5),
        _ch("IV.", "The fourth section is an epilogue. ", 5),
    ])
    assert cd.detect_format(text) == "roman"
    assert cd.count_chapters(text) == 4


def test_detect_roman_many():
    parts = [_ch(f"{r}.", "Section text. ", 20)
             for r in ["I", "II", "III", "IV", "V", "VI", "VII"]]
    text = "\n\n".join(parts)
    assert cd.detect_format(text) == "roman"
    assert cd.count_chapters(text) == 7


# ---------------------------------------------------------------------------
# Format: Numeric at start (1. / 2. / 3. — only when in first 1k chars & 3+)
# ---------------------------------------------------------------------------
def test_detect_numeric_at_start():
    # File opens with 1. 2. 3. markers, each introducing substantial content
    text = "\n\n".join([
        "1.\nThis is the first numbered section introducing the theme.",
        "2.\nThis is the second numbered section building on the first.",
        "3.\nThis is the third numbered section with more narrative detail.",
        "4.\nThis is the fourth numbered section.",
    ])
    # And pad out with more body that has no markers
    text = text + "\n\nA long trailing paragraph without new markers. " * 30
    assert cd.detect_format(text) == "numeric"
    assert cd.count_chapters(text) == 4


def test_detect_numeric_inline_not_chapter():
    # A long novel-like body with an in-paragraph enumeration like "1. foo 2. bar"
    # should NOT be detected as numeric chapters.
    body = "这是正文第一段。" * 40
    text = body + "\n\n这里有一个列表：1. 苹果 2. 香蕉 3. 橙子。然后继续正文。" * 5
    # No marker should match; falls back to 1
    assert cd.count_chapters(text) == 1


def test_detect_numeric_requires_three_plus():
    # Only "1." and "2." at start — not enough to trigger numeric format
    text = "1.\nOpening.\n\n2.\nSecond.\n\n" + ("Plain body paragraph. " * 100)
    # Only 2 markers at top — should not activate numeric detection
    assert cd.detect_format(text) != "numeric"


# ---------------------------------------------------------------------------
# Format: custom separator (=== or --- lines)
# ---------------------------------------------------------------------------
def test_detect_separator_equals():
    text = "\n".join([
        "Opening narrative paragraph." * 5,
        "===",
        "Second part narrative paragraph." * 5,
        "===",
        "Third part narrative paragraph." * 5,
        "===",
        "Fourth part narrative paragraph." * 5,
    ])
    assert cd.detect_format(text) == "separator"
    # 3 separators → 4 parts
    assert cd.count_chapters(text) == 4


def test_detect_separator_dashes():
    text = "\n".join([
        "First segment." * 10,
        "---",
        "Second segment." * 10,
        "---",
        "Third segment." * 10,
        "---",
        "Fourth segment." * 10,
    ])
    assert cd.detect_format(text) == "separator"
    assert cd.count_chapters(text) == 4


# ---------------------------------------------------------------------------
# Priority: when multiple formats present, pick the winner by count
# ---------------------------------------------------------------------------
def test_detect_format_priority():
    # 5 第N章 markers + 1 stray "Chapter 1" — should pick zh-standard
    text = "\n\n".join([
        _ch("第1章 开始", "正文内容，其中提到 Chapter 1 只是一句对白。"),
        _ch("第2章 发展", "正文内容。"),
        _ch("第3章 高潮", "正文内容。"),
        _ch("第4章 转折", "正文内容。"),
        _ch("第5章 结局", "正文内容。"),
    ])
    assert cd.detect_format(text) == "zh-standard"
    assert cd.count_chapters(text) == 5


def test_count_fallback_to_one():
    # Plain prose with no chapter markers anywhere
    text = "这是一段非常普通的小说正文，没有任何章节标记。" * 100
    assert cd.detect_format(text) == "none"
    assert cd.count_chapters(text) == 1


# ---------------------------------------------------------------------------
# find_chapter_splits
# ---------------------------------------------------------------------------
def test_find_splits_returns_sorted_offsets():
    text = "\n\n".join([
        _ch("第1章 甲", "内容一。"),
        _ch("第2章 乙", "内容二。"),
        _ch("第3章 丙", "内容三。"),
    ])
    splits = cd.find_chapter_splits(text)
    assert splits == sorted(splits)
    assert len(splits) == 3


def test_find_splits_first_is_zero():
    text = "\n\n".join([
        _ch("第1章 甲", "内容一。"),
        _ch("第2章 乙", "内容二。"),
    ])
    splits = cd.find_chapter_splits(text)
    assert splits[0] == 0


def test_find_splits_fallback_single_chapter():
    text = "没有章节标记的纯文本。" * 30
    splits = cd.find_chapter_splits(text)
    assert splits == [0]


def test_find_splits_cover_full_range():
    # Offsets must be strictly within text length
    text = "\n\n".join([
        _ch("第1章 甲", "内容一。"),
        _ch("第2章 乙", "内容二。"),
        _ch("第3章 丙", "内容三。"),
        _ch("第4章 丁", "内容四。"),
    ])
    splits = cd.find_chapter_splits(text)
    assert all(0 <= s < len(text) for s in splits)
    assert len(splits) == 4

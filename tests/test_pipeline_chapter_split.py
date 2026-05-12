"""Integration: pipeline batch split driven by chapter_detector.

Verifies that the pipeline helper functions (``_count_chapters_in_text`` and
``_split_text_into_batches``) delegate to the new chapter detector so that
batches align with real chapter boundaries, not arbitrary char-count cuts.
"""
from __future__ import annotations


def test_pipeline_split_real_chapters_by_batch():
    """30-chapter text, batch_size=10 → 3 batches, each holding exactly
    the right chapters."""
    from src.genre_extractor import pipeline

    chapters = []
    for i in range(1, 31):
        # Body text deliberately avoids "第N章" substrings so the marker
        # regex in the assertions only catches real headers.
        body = f"第{i}章 章节标题{i}\n" + (f"这里是本章内容，编号为 {i}。" * 20)
        chapters.append(body)
    text = "\n\n".join(chapters)

    total_ch = pipeline._count_chapters_in_text(text)
    assert total_ch == 30

    batches = pipeline._split_text_into_batches(text, total_ch, batch_size=10)
    assert len(batches) == 3

    def _markers_in(s):
        import re
        return [int(m.group(1)) for m in re.finditer(r"第(\d+)章", s)]

    assert _markers_in(batches[0]) == list(range(1, 11))
    assert _markers_in(batches[1]) == list(range(11, 21))
    assert _markers_in(batches[2]) == list(range(21, 31))

    # Concatenation should reproduce the full text exactly (no data loss).
    assert "".join(batches) == text


def test_pipeline_split_falls_back_when_no_markers():
    """If detector finds nothing, splitter still returns the whole text
    as a single batch (no crash, no data loss)."""
    from src.genre_extractor import pipeline

    text = "一整段没有章节标记的散文。" * 200
    total_ch = pipeline._count_chapters_in_text(text)
    assert total_ch == 1
    batches = pipeline._split_text_into_batches(text, total_ch, batch_size=10)
    assert len(batches) == 1
    assert batches[0] == text


def test_pipeline_split_english_chapters():
    """English 'Chapter N' format should also split correctly."""
    from src.genre_extractor import pipeline

    chapters = []
    for i in range(1, 13):
        body = f"Chapter {i}\n" + (f"This is body paragraph for part {i}. " * 25)
        chapters.append(body)
    text = "\n\n".join(chapters)

    total_ch = pipeline._count_chapters_in_text(text)
    assert total_ch == 12

    batches = pipeline._split_text_into_batches(text, total_ch, batch_size=5)
    # 12 / 5 = ceil(12/5) = 3 batches of sizes 5, 5, 2
    assert len(batches) == 3
    # No data loss
    assert "".join(batches) == text


def test_pipeline_split_reproduces_text_exactly():
    """Joining all batches must reproduce the original text byte-for-byte."""
    from src.genre_extractor import pipeline

    text = "\n\n".join([
        f"第{i}章 t{i}\n" + ("正文段落内容。" * 15)
        for i in range(1, 8)
    ])
    batches = pipeline._split_text_into_batches(text, 7, batch_size=3)
    assert "".join(batches) == text

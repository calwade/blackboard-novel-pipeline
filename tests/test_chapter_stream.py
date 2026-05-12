"""Tests for ChapterStream streaming chapter reader.

Small files (< 5MB) take the fast path and load fully into memory.
Large files are indexed by byte offset and chapters are read on-demand via seek.
"""
from __future__ import annotations

import tracemalloc
from pathlib import Path

import pytest

from src.genre_pipeline.chapter_stream import (
    ChapterRef,
    ChapterStream,
    STREAMING_THRESHOLD_BYTES,
)


def _make_novel_text(n_chapters: int, chapter_body: str = "正文内容。" * 20) -> str:
    """Build a synthetic novel with `n_chapters` '第N章' markers."""
    parts = []
    for i in range(1, n_chapters + 1):
        parts.append(f"第{i}章 测试章节 {i}\n{chapter_body}\n")
    return "\n".join(parts)


def test_small_file_loaded_fully(tmp_path: Path) -> None:
    """Small files (< 5MB) use the in-memory fast path."""
    p = tmp_path / "small.txt"
    p.write_text(_make_novel_text(5), encoding="utf-8")

    stream = ChapterStream(p)
    assert stream.total_chapters == 5
    assert stream.is_streaming is False

    text = stream.read_batch(1, 3)
    # Should contain chapters 1..3 markers
    assert "第1章" in text
    assert "第2章" in text
    assert "第3章" in text
    # And NOT chapter 4
    assert "第4章" not in text


def test_large_file_uses_streaming(tmp_path: Path) -> None:
    """Files larger than threshold use streaming (index + seek)."""
    p = tmp_path / "big.txt"
    # Construct a >5MB file with many chapters.
    body = "正文" * 2000  # ~12KB per chapter
    text = _make_novel_text(500, chapter_body=body)
    p.write_text(text, encoding="utf-8")
    assert p.stat().st_size > STREAMING_THRESHOLD_BYTES

    stream = ChapterStream(p)
    assert stream.is_streaming is True
    assert stream.total_chapters == 500

    # Check a middle batch
    chunk = stream.read_batch(100, 110)
    assert "第100章" in chunk
    assert "第110章" in chunk
    assert "第99章" not in chunk
    # Chapter 111 start marker must NOT appear
    assert "第111章" not in chunk


def test_read_batch_returns_correct_range(tmp_path: Path) -> None:
    p = tmp_path / "novel.txt"
    p.write_text(_make_novel_text(20), encoding="utf-8")

    stream = ChapterStream(p)
    assert stream.total_chapters == 20

    first = stream.read_batch(1, 5)
    for i in range(1, 6):
        assert f"第{i}章" in first
    assert "第6章" not in first

    mid = stream.read_batch(6, 10)
    assert "第6章" in mid
    assert "第10章" in mid
    assert "第5章" not in mid
    assert "第11章" not in mid

    tail = stream.read_batch(16, 20)
    assert "第16章" in tail
    assert "第20章" in tail
    assert "第15章" not in tail


def test_read_batch_out_of_range_raises(tmp_path: Path) -> None:
    p = tmp_path / "novel.txt"
    p.write_text(_make_novel_text(10), encoding="utf-8")
    stream = ChapterStream(p)

    with pytest.raises(ValueError):
        stream.read_batch(0, 3)  # 1-indexed
    with pytest.raises(ValueError):
        stream.read_batch(5, 3)  # end < start
    with pytest.raises(ValueError):
        stream.read_batch(1, 999)  # past end


def test_utf8_boundary_safe(tmp_path: Path) -> None:
    """Multi-byte UTF-8 characters straddling chapter boundaries must decode
    cleanly in both index build AND read_batch."""
    # Force streaming by padding so file > threshold; chapter boundaries in
    # UTF-8 bytes will land mid-character for some chapters due to varying
    # Chinese content lengths.
    p = tmp_path / "utf8.txt"
    # Use uneven CJK widths to maximize boundary risk
    parts = []
    for i in range(1, 301):
        # every chapter has different length in bytes
        filler = "字" * (i % 97 + 50)  # CJK = 3 bytes each, varies per chapter
        parts.append(f"第{i}章 标题{i}\n{filler}\n")
    # Pad file to exceed streaming threshold
    text = "\n".join(parts)
    while len(text.encode("utf-8")) < STREAMING_THRESHOLD_BYTES + 1024:
        text += "\n" + "填充" * 1000
    p.write_text(text, encoding="utf-8")

    stream = ChapterStream(p)
    assert stream.is_streaming is True

    # Read several batches and confirm they decode without error and
    # contain the expected chapter markers.
    for (a, b) in [(1, 20), (100, 130), (250, 280), (290, 300)]:
        chunk = stream.read_batch(a, b)
        assert isinstance(chunk, str)
        assert f"第{a}章" in chunk
        # Should decode without replacement characters for in-content CJK
        # (we tolerate at most a couple at the very boundaries)
        assert chunk.count("\ufffd") <= 2


def test_invalid_source_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ChapterStream(tmp_path / "nope.txt")


def test_no_chapter_markers_fallback(tmp_path: Path) -> None:
    """A file with no '第N章' markers should report total_chapters >= 1 so
    pipelines that rely on it don't divide by zero."""
    p = tmp_path / "flat.txt"
    p.write_text("just some prose without any chapter marker at all", encoding="utf-8")
    stream = ChapterStream(p)
    assert stream.total_chapters >= 1
    # read_batch(1,1) should return the whole text
    out = stream.read_batch(1, stream.total_chapters)
    assert "prose" in out


def test_chapter_refs_have_byte_offsets(tmp_path: Path) -> None:
    """Public chapter_refs list should expose ChapterRef with byte offsets."""
    p = tmp_path / "novel.txt"
    p.write_text(_make_novel_text(5), encoding="utf-8")
    stream = ChapterStream(p)

    refs = stream.chapter_refs
    assert len(refs) == 5
    for idx, r in enumerate(refs, start=1):
        assert isinstance(r, ChapterRef)
        assert r.chapter_index == idx
        assert r.byte_offset >= 0
        assert r.byte_length > 0
    # refs must be in ascending order
    for a, b in zip(refs, refs[1:]):
        assert a.byte_offset < b.byte_offset


def test_streaming_peak_memory_bounded(tmp_path: Path) -> None:
    """A 6MB file read via read_batch should NOT peak at 6MB of Python str.

    We measure tracemalloc peak while doing an index + single batch read.
    The index holds only offsets (small); a single batch should only load
    that batch's bytes.
    """
    p = tmp_path / "big.txt"
    body = "正文" * 2000  # ~12KB
    text = _make_novel_text(600, chapter_body=body)
    p.write_text(text, encoding="utf-8")
    file_size = p.stat().st_size
    assert file_size > STREAMING_THRESHOLD_BYTES

    tracemalloc.start()
    try:
        stream = ChapterStream(p)
        assert stream.is_streaming is True
        _ = stream.read_batch(1, 25)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # Peak should be well under the whole-file size. Streaming uses a 1MB
    # block buffer during indexing + holds one decoded batch at read time.
    # With ~12KB * 25 = 300KB batch + 1MB block + overhead, expect < 4MB.
    assert peak < file_size, (
        f"streaming peak {peak} should be less than whole-file size {file_size}"
    )
    assert peak < 4 * 1024 * 1024, f"streaming peak {peak} too high"

"""Integration tests: extract_from_novel with large novels uses streaming.

Verifies that the pipeline integrates ChapterStream correctly — large files
are indexed, per-batch text is loaded lazily, and the novel_sources stored
in build_status still carry total_chapters / batch_size / path.
"""
from __future__ import annotations

import tracemalloc
from pathlib import Path

import pytest

from src.genre_pipeline.chapter_stream import STREAMING_THRESHOLD_BYTES


def _make_large_novel(path: Path, n_chapters: int = 500) -> int:
    """Write a novel file of at least STREAMING_THRESHOLD_BYTES bytes.

    Returns the file size in bytes.
    """
    body = "正文内容。" * 500  # ~3KB per chapter in UTF-8
    lines = []
    for i in range(1, n_chapters + 1):
        lines.append(f"第{i}章 测试章节 {i}\n{body}\n")
    text = "\n".join(lines)
    # Pad if needed to exceed streaming threshold
    while len(text.encode("utf-8")) < STREAMING_THRESHOLD_BYTES + 1024 * 256:
        text += "\n第额外章 填充\n" + ("填充" * 2000) + "\n"
    path.write_text(text, encoding="utf-8")
    return path.stat().st_size


def test_extract_from_novel_streaming_integration(tmp_path, monkeypatch):
    """Dry-run extract_from_novel over a > 5MB novel: should plumb without
    loading the whole file fully into Python memory beyond peak."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    novel = tmp_path / "big_novel.txt"
    file_size = _make_large_novel(novel, n_chapters=400)
    assert file_size > STREAMING_THRESHOLD_BYTES

    from src.genre_pipeline import pipeline

    tracemalloc.start()
    try:
        out = pipeline.extract_from_novel(
            "demo-big",
            sources=[str(novel)],
            with_trial=False,
            dry_run=True,
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert out["ok"]
    assert out["mode"] == "dry_run"
    # One source was registered
    assert len(out["sources"]) == 1
    src_info = out["sources"][0]
    assert src_info["path"] == str(novel)
    assert src_info["total_chapters"] >= 400
    assert src_info["batch_size"] in (10, 25, 40)  # adaptive_batch_size values

    # The dry-run path only indexes; it shouldn't touch the full text.
    # Expect peak well below file size.
    assert peak < file_size, (
        f"dry-run peak {peak} should be < file size {file_size}"
    )


def test_extract_small_file_uses_fast_path(tmp_path, monkeypatch):
    """Files under threshold should keep using the in-memory read path."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    novel = tmp_path / "tiny.txt"
    text = "\n".join(
        [f"第{i}章 小章\n这是正文。" for i in range(1, 11)]
    )
    novel.write_text(text, encoding="utf-8")
    assert novel.stat().st_size < STREAMING_THRESHOLD_BYTES

    from src.genre_pipeline import pipeline
    out = pipeline.extract_from_novel(
        "demo-small",
        sources=[str(novel)],
        with_trial=False,
        dry_run=True,
    )
    assert out["ok"]
    assert out["sources"][0]["total_chapters"] == 10


def test_run_phase_extract_rebuilds_streams(tmp_path, monkeypatch):
    """run_phase('extract') must be able to reconstruct streams from the
    paths stored in build_status.yaml (via dry-run path to avoid LLM)."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    novel = tmp_path / "novel.txt"
    text = "\n".join([f"第{i}章 标题\n正文{i}" for i in range(1, 21)])
    novel.write_text(text, encoding="utf-8")

    from src.genre_pipeline import pipeline
    # First establish a build_status via dry_run
    pipeline.extract_from_novel(
        "demo-rephase", sources=[str(novel)], dry_run=True,
    )
    # Now verify run_phase('extract') can read the status and rebuild
    # streams without crashing. We can't actually call _run_extract without
    # an LLM, so just verify the build_status survives and the path exists.
    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "demo-rephase" / ".build")
    status = bb.read_yaml("build_status.yaml")
    assert status["novel_sources"][0]["path"] == str(novel)
    # Confirm a stream can be rebuilt from that path.
    from src.genre_pipeline.chapter_stream import ChapterStream
    stream = ChapterStream(status["novel_sources"][0]["path"])
    assert stream.total_chapters == 20

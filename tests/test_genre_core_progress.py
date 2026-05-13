"""T6: core.run_extract / run_merge / run_draft 接 CancelToken + ProgressCallback."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.blackboard import Blackboard
from src.genre_extractor import core, schemas
from src.jobs.cancel import GenrePipelineAborted, ThreadEventToken


def _mk_bb(tmp_path: Path) -> Blackboard:
    bb_dir = tmp_path / "bb"
    bb_dir.mkdir()
    bb = Blackboard(root=bb_dir)
    bb.write_yaml(
        "build_status.yaml",
        schemas.make_initial_build_status(
            genre_id="x", entry="test", novel_sources=[],
        ),
    )
    return bb


class _FakeStream:
    """Minimal stream mimicking ChapterStream API: total_chapters / read_batch."""

    def __init__(self, total: int, batch_size: int) -> None:
        self.total_chapters = total
        self._batch_size = batch_size

    def read_batch(self, start: int, end: int) -> str:
        return f"chapters {start}-{end}"


def test_run_extract_fires_on_progress_per_batch(tmp_path):
    bb = _mk_bb(tmp_path)
    stream = _FakeStream(total=50, batch_size=25)  # → 2 batches
    calls = []

    def on_progress(**kw):
        calls.append(kw)

    with patch(
        "src.genre_extractor.agents.extractor.GenreExtractor"
    ) as mock_cls:
        mock_cls.return_value.run = MagicMock()
        core.run_extract(
            bb, [(stream, 25)], on_progress=on_progress,
        )
    # 至少：0/2 (初始) + 1/2 + 2/2
    batch_curs = [
        c["sub_steps"]["batch_cur"] for c in calls
        if c.get("sub_steps") and "batch_cur" in c["sub_steps"]
    ]
    assert 0 in batch_curs
    assert 1 in batch_curs
    assert 2 in batch_curs
    # phase / phase_index 正确
    assert all(c.get("phase") == "extract" for c in calls if "phase" in c)
    assert all(c.get("phase_index") == 1 for c in calls if "phase_index" in c)


def test_run_extract_cancels_between_batches(tmp_path):
    bb = _mk_bb(tmp_path)
    stream = _FakeStream(total=75, batch_size=25)  # → 3 batches
    token = ThreadEventToken()
    seen_batches = []

    def on_progress(**kw):
        sub = kw.get("sub_steps") or {}
        if "batch_cur" in sub and sub["batch_cur"] == 1:
            token.cancel()  # 第 1 batch 完成后 cancel
        if "batch_cur" in sub:
            seen_batches.append(sub["batch_cur"])

    with patch(
        "src.genre_extractor.agents.extractor.GenreExtractor"
    ) as mock_cls:
        mock_cls.return_value.run = MagicMock()
        with pytest.raises(GenrePipelineAborted):
            core.run_extract(
                bb, [(stream, 25)], cancel=token, on_progress=on_progress,
            )
    # 应该跑完 batch 1，但 batch 2 之前被 cancel 打断，所以没 batch 2/3
    assert 1 in seen_batches
    assert 2 not in seen_batches
    assert 3 not in seen_batches


def test_run_extract_backwards_compat_without_new_args(tmp_path):
    """旧调用方（不传 cancel / on_progress）必须照常工作."""
    bb = _mk_bb(tmp_path)
    stream = _FakeStream(total=25, batch_size=25)  # → 1 batch
    with patch(
        "src.genre_extractor.agents.extractor.GenreExtractor"
    ) as mock_cls:
        mock_cls.return_value.run = MagicMock()
        core.run_extract(bb, [(stream, 25)])  # 无新参数
    # 不应抛错


def test_run_merge_fires_arc_progress_for_long_book(tmp_path):
    """当 batch 数量触发 multitier 时，arc loop 每次 iteration 都应报 arc_cur/total."""
    bb = _mk_bb(tmp_path)
    # 写足够多的 batch notes 使 multitier 路径触发（ARC_BATCH_COUNT=4）
    from src.genre_extractor.agents.arc_merger import ARC_BATCH_COUNT
    # 需要 > ARC_BATCH_COUNT 才进 multitier，给 8 批 → 2 arcs
    for i in range(1, 9):
        bb.write_yaml(
            f"extraction_notes/batch-{i:03d}.yaml",
            {"batch_id": i, "era_observations": []},
        )

    calls = []

    def on_progress(**kw):
        calls.append(kw)

    # mock arc_merger + book_distiller，只验回调而不真跑 LLM
    with patch(
        "src.genre_extractor.agents.arc_merger.GenreArcMerger"
    ) as m_arc, patch(
        "src.genre_extractor.agents.book_distiller.GenreBookDistiller"
    ) as m_book:
        arc_mock = MagicMock()
        # arc_merger.run 写个占位 arc yaml 给后续"单 arc 提升"逻辑读
        def _fake_arc_run(bb_, arc_id, batch_ids):
            bb_.write_yaml(
                f"extraction_notes/arcs/arc-{arc_id:03d}.yaml",
                {"arc_id": arc_id, "era_observations": []},
            )
        arc_mock.run = MagicMock(side_effect=_fake_arc_run)
        m_arc.return_value = arc_mock
        m_book.return_value.run = MagicMock()
        core.run_merge(bb, on_progress=on_progress)

    arc_curs = [
        c["sub_steps"]["arc_cur"] for c in calls
        if c.get("sub_steps") and "arc_cur" in c["sub_steps"]
    ]
    assert 1 in arc_curs
    # 8 batches / 4 per arc = 2 arcs
    assert 2 in arc_curs


def test_run_draft_checks_cancel_upfront(tmp_path):
    bb = _mk_bb(tmp_path)
    token = ThreadEventToken()
    token.cancel()  # 预先 cancel
    with pytest.raises(GenrePipelineAborted):
        core.run_draft(bb, "x", cancel=token)


def test_run_draft_fires_phase_progress(tmp_path):
    bb = _mk_bb(tmp_path)
    calls = []

    def on_progress(**kw):
        calls.append(kw)

    with patch(
        "src.genre_extractor.agents.drafter.GenreDrafter"
    ) as mock_cls:
        mock_cls.return_value.run = MagicMock()
        core.run_draft(bb, "x", on_progress=on_progress)
    assert any(c.get("phase") == "draft" for c in calls)
    assert any(c.get("phase_index") == 3 for c in calls)

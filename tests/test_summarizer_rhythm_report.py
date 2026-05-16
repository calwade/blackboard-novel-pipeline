"""Tests for ArcSummarizer + BookSummarizer 节奏报表 (P2 修复).

LLM-free — only exercises _build_prompts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents.multi_level_summarizer import ArcSummarizer, BookSummarizer


def _seed_arc_5_summaries(tmp_path: Path, start: int = 1) -> Blackboard:
    b = Blackboard(root=tmp_path)
    (tmp_path / "summaries").mkdir(exist_ok=True)
    for n in range(start, start + 5):
        b.write_text(f"summaries/ch{n:03d}.md", f"第{n}章发生了一些事。\n")
    return b


def _seed_volume_4_arcs(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    (tmp_path / "summaries" / "arcs").mkdir(parents=True, exist_ok=True)
    for a in range(1, 5):
        b.write_text(
            f"summaries/arcs/arc-{a:02d}.md",
            f"第{a}弧弧摘内容。\n\n## 节奏报表（用于 Planner 决策）\n- chapter_type 分布：战斗×1\n",
        )
    return b


# ---------------- 1. ArcSummarizer demands rhythm report ----------------

def test_arc_summarizer_demands_rhythm_report(tmp_path):
    b = _seed_arc_5_summaries(tmp_path, start=1)
    system, user, _ = ArcSummarizer()._build_prompts(b, chapter=5)

    # The rule must be in the system prompt
    assert "节奏报表" in system
    assert "chapter_type 分布" in system
    assert "主动 vs 被动" in system
    assert "dna anchor 兑现" in system
    assert "新增未回收伏笔" in system
    assert "节奏判断" in system

    # The system prompt must also include the exact section title to use
    assert "节奏报表（用于 Planner 决策）" in system


# ---------------- 2. BookSummarizer demands rhythm report ----------------

def test_book_summarizer_demands_rhythm_report(tmp_path):
    b = _seed_volume_4_arcs(tmp_path)
    system, user, _ = BookSummarizer()._build_prompts(b, chapter=20)

    assert "节奏报表" in system
    assert "chapter_type 分布" in system
    assert "主动 vs 被动" in system
    assert "dna anchor 兑现" in system
    assert "节奏判断" in system
    assert "节奏报表（用于 Planner 决策）" in system

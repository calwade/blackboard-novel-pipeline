"""Tests for Planner milestone forcing + anchor_quota status injection (P0+P1 续).

LLM-free — only exercises Planner._build_prompts.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.blackboard import Blackboard
from src.agents.planner import Planner


def _seed_basic(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "末世契约", "era": "X"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "陈牧"}})
    b.write_json(
        "outline.json",
        {"chapters": [{"ch": i, "title": f"第{i}章", "beats": [f"b{i}"]} for i in range(1, 51)]},
    )
    (tmp_path / "chapters").mkdir(exist_ok=True)
    (tmp_path / "summaries").mkdir(exist_ok=True)
    return b


def _write_plot_arc_with_milestone(tmp_path: Path) -> None:
    data = {
        "schema_version": 1,
        "total_chapters": 50,
        "ultimate_goal": "终极",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 15],
                "goal": "g1",
                "must_close_by_end": [],
            },
            {
                "name": "卷二",
                "range": [16, 30],
                "goal": "g2",
                "must_close_by_end": [],
                "milestones": [
                    {
                        "chapter": 18,
                        "type": "能力升级·烙印反向",
                        "anchor": "掌控感",
                        "force_chapter_type": "回收",
                        "force_advances": ["境界", "信息"],
                        "beat": "烙印第一次主动闪光帮主角避险",
                    }
                ],
                "anchor_quota": {"爽感": 2, "掌控感": 2, "黑色幽默": 1, "生存智慧": 3},
            },
            {"name": "卷三", "range": [31, 45], "must_close_by_end": []},
            {"name": "终卷", "range": [46, 50], "must_close_by_end": []},
        ],
    }
    (tmp_path / "plot_arc.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


# ---------------- 1. milestone block injected at milestone chapter ----------------

def test_planner_injects_milestone_block(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc_with_milestone(tmp_path)

    _, user, _ = Planner()._build_prompts(bb, chapter=18)
    assert "🎯 本章 milestone" in user
    assert "能力升级" in user  # type
    assert "掌控感" in user  # anchor
    assert "烙印第一次主动闪光" in user  # beat


# ---------------- 2. force_chapter_type injected ----------------

def test_planner_injects_force_chapter_type(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc_with_milestone(tmp_path)

    _, user, _ = Planner()._build_prompts(bb, chapter=18)
    assert "chapter_type 强制为：`回收`" in user


# ---------------- 3. anchor_quota status injected ----------------

def test_planner_injects_anchor_quota_status(tmp_path):
    """Even with no historical plans, the quota table itself should be visible."""
    bb = _seed_basic(tmp_path)
    _write_plot_arc_with_milestone(tmp_path)
    # Write some historical plans for ch16, ch17 (in 卷二 range, before ch18)
    bb.write_json(
        "chapters/ch016.plan.json",
        {
            "ch": 16,
            "chapter_type": "战斗",
            "scenes": [{"scene_id": 1, "location": "便利店", "advances": ["地位"]}],
        },
    )
    bb.write_json(
        "chapters/ch017.plan.json",
        {
            "ch": 17,
            "chapter_type": "过渡",
            "scenes": [{"scene_id": 1, "location": "便利店", "advances": ["信息"]}],
        },
    )

    _, user, _ = Planner()._build_prompts(bb, chapter=18)
    assert "anchor 配额" in user
    # anchor_quota table headers
    assert "已兑现" in user
    assert "缺口" in user


# ---------------- 4. no milestone → no 🎯 block ----------------

def test_planner_no_milestone_means_no_block(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc_with_milestone(tmp_path)

    # ch20 is in 卷二 but not a milestone chapter
    _, user, _ = Planner()._build_prompts(bb, chapter=20)
    assert "🎯 本章 milestone" not in user
    # But "next milestone" guidance might appear (we have ms at ch23 in this test set?
    # No — only ch18. ch23 not configured. But we do have act.next_act etc.)
    # Should not contain milestone forcing keywords:
    assert "chapter_type 强制为" not in user


# ---------------- 5. system prompt has rules 13 + 14 ----------------

def test_planner_system_prompt_has_milestone_rules(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc_with_milestone(tmp_path)

    system, _, _ = Planner()._build_prompts(bb, chapter=18)
    assert "13." in system and "milestone 强制律" in system
    assert "14." in system and "anchor 配额律" in system

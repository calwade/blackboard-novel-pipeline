"""Tests for plot_arc.yaml milestones + anchor_quota schema (P0+P1 续).

LLM-free — pure schema/dataclass tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.tools.plot_arc import (
    PlotAct,
    PlotArc,
    PlotMilestone,
    derive_planner_context,
    read_plot_arc,
)


def _write_yaml(p: Path, data: dict) -> None:
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ---------------- 1. valid milestone schema ----------------

def test_milestone_schema_valid(tmp_path: Path):
    data = {
        "schema_version": 1,
        "total_chapters": 30,
        "ultimate_goal": "终极",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 15],
                "goal": "g1",
                "must_close_by_end": [],
                "milestones": [
                    {
                        "chapter": 7,
                        "type": "暗格首启",
                        "anchor": "掌控感",
                        "force_chapter_type": "回收",
                        "force_advances": ["资源", "信息"],
                        "beat": "主角第一次主动触发暗格门",
                    },
                    {
                        "chapter": 12,
                        "type": "金属片首兑",
                        "anchor": "爽感",
                        "force_chapter_type": "战斗",
                        "force_advances": ["资源"],
                        "beat": "金属片换走十倍物资",
                    },
                ],
                "anchor_quota": {"爽感": 2, "掌控感": 2, "黑色幽默": 1, "生存智慧": 3},
            },
            {
                "name": "卷二",
                "range": [16, 30],
                "goal": "g2",
                "must_close_by_end": [],
            },
        ],
    }
    _write_yaml(tmp_path / "plot_arc.yaml", data)
    arc = read_plot_arc(tmp_path)
    assert arc is not None
    assert len(arc.acts) == 2
    a1 = arc.acts[0]
    assert len(a1.milestones) == 2
    ms = a1.milestones[0]
    assert isinstance(ms, PlotMilestone)
    assert ms.chapter == 7
    assert ms.anchor == "掌控感"
    assert ms.force_chapter_type == "回收"
    assert ms.force_advances == ["资源", "信息"]
    assert "暗格" in ms.beat
    assert a1.anchor_quota == {"爽感": 2, "掌控感": 2, "黑色幽默": 1, "生存智慧": 3}
    # act 2 没配 milestones → 默认空
    assert arc.acts[1].milestones == []
    assert arc.acts[1].anchor_quota == {}


# ---------------- 2. milestone.chapter must be in act.range ----------------

def test_milestone_chapter_must_be_in_act_range(tmp_path: Path):
    data = {
        "schema_version": 1,
        "total_chapters": 30,
        "ultimate_goal": "x",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 15],
                "must_close_by_end": [],
                "milestones": [
                    {
                        # ch20 不在 [1,15] 内
                        "chapter": 20,
                        "type": "X",
                        "anchor": "爽感",
                        "beat": "y",
                    }
                ],
            },
            {"name": "卷二", "range": [16, 30], "must_close_by_end": []},
        ],
    }
    _write_yaml(tmp_path / "plot_arc.yaml", data)
    with pytest.raises(ValueError, match=r"outside act\.range"):
        read_plot_arc(tmp_path)


# ---------------- 3. milestone.anchor must be valid ----------------

def test_milestone_anchor_must_be_valid(tmp_path: Path):
    data = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 10],
                "must_close_by_end": [],
                "milestones": [
                    {
                        "chapter": 5,
                        "type": "X",
                        "anchor": "非法值",  # 不在 VALID_ANCHORS 中
                        "beat": "y",
                    }
                ],
            }
        ],
    }
    _write_yaml(tmp_path / "plot_arc.yaml", data)
    with pytest.raises(ValueError, match=r"anchor must be one of"):
        read_plot_arc(tmp_path)


def test_milestone_force_chapter_type_must_be_valid(tmp_path: Path):
    data = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 10],
                "must_close_by_end": [],
                "milestones": [
                    {
                        "chapter": 5,
                        "type": "X",
                        "anchor": "爽感",
                        "force_chapter_type": "搞笑",  # 非法
                        "beat": "y",
                    }
                ],
            }
        ],
    }
    _write_yaml(tmp_path / "plot_arc.yaml", data)
    with pytest.raises(ValueError, match=r"force_chapter_type must be one of"):
        read_plot_arc(tmp_path)


# ---------------- 4. anchor_quota schema ----------------

def test_anchor_quota_schema_invalid_key(tmp_path: Path):
    data = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 10],
                "must_close_by_end": [],
                "anchor_quota": {"爽感": 2, "非法anchor": 1},
            }
        ],
    }
    _write_yaml(tmp_path / "plot_arc.yaml", data)
    with pytest.raises(ValueError, match=r"anchor_quota key"):
        read_plot_arc(tmp_path)


def test_anchor_quota_accepts_int_and_string(tmp_path: Path):
    data = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 10],
                "must_close_by_end": [],
                "anchor_quota": {"爽感": 2, "生存智慧": ">=8"},
            }
        ],
    }
    _write_yaml(tmp_path / "plot_arc.yaml", data)
    arc = read_plot_arc(tmp_path)
    assert arc is not None
    assert arc.acts[0].anchor_quota == {"爽感": 2, "生存智慧": ">=8"}


# ---------------- 5. derive current_milestone ----------------

def _arc_with_milestones() -> PlotArc:
    return PlotArc(
        schema_version=1,
        total_chapters=30,
        ultimate_goal="x",
        acts=[
            PlotAct(
                name="卷一",
                range=(1, 15),
                milestones=[
                    PlotMilestone(chapter=7, type="A1", anchor="掌控感", beat="b1"),
                ],
            ),
            PlotAct(
                name="卷二",
                range=(16, 30),
                milestones=[
                    PlotMilestone(chapter=18, type="A2", anchor="掌控感", beat="b2"),
                    PlotMilestone(chapter=23, type="A3", anchor="爽感", beat="b3"),
                ],
            ),
        ],
    )


def test_derive_current_milestone():
    arc = _arc_with_milestones()
    ctx = derive_planner_context(arc, 18)
    cm = ctx["current_milestone"]
    assert cm is not None
    assert cm.chapter == 18
    assert cm.type == "A2"
    assert cm.anchor == "掌控感"


# ---------------- 6. derive next_milestone distance ----------------

def test_derive_next_milestone_distance():
    arc = _arc_with_milestones()
    ctx = derive_planner_context(arc, 20)
    assert ctx["current_milestone"] is None
    nxt = ctx["next_milestone"]
    assert nxt is not None
    assert nxt.chapter == 23
    assert ctx["chapters_until_next_milestone"] == 3


def test_derive_next_milestone_none_at_end():
    """No more milestones after the last one → None."""
    arc = _arc_with_milestones()
    ctx = derive_planner_context(arc, 25)  # 25 > 23 (last milestone)
    assert ctx["current_milestone"] is None
    assert ctx["next_milestone"] is None
    assert ctx["chapters_until_next_milestone"] is None

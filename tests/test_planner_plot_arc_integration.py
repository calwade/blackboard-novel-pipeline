"""Tests for Planner reading plot_arc.yaml (Oracle P0+P1 修复).

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
    b.write_yaml("setting.yaml", {"genre": "末世契约", "era": "虫潮后第三年", "tone": "克制"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "陈牧"}})
    b.write_json(
        "outline.json",
        {
            "chapters": [
                {"ch": i, "title": f"第{i}章", "beats": [f"beat{i}"]}
                for i in range(1, 51)
            ]
        },
    )
    (tmp_path / "chapters").mkdir(exist_ok=True)
    (tmp_path / "summaries").mkdir(exist_ok=True)
    return b


def _write_plot_arc(tmp_path: Path) -> None:
    data = {
        "schema_version": 1,
        "total_chapters": 50,
        "ultimate_goal": "解开契约站真相",
        "acts": [
            {
                "name": "卷一·暗格觉醒",
                "range": [1, 15],
                "goal": "发现暗格通异界",
                "must_close_by_end": ["金属片用途", "灰风衣身份初现"],
            },
            {
                "name": "卷二·锅炉房真相",
                "range": [16, 30],
                "goal": "进入异界，揭锅炉房真相",
                "must_close_by_end": ["锅炉房真相", "赵铁城立场"],
            },
            {
                "name": "卷三·灰塔",
                "range": [31, 45],
                "goal": "深入灰塔",
                "must_close_by_end": ["灰塔位置", "幕后真身"],
            },
            {
                "name": "终卷·解契约",
                "range": [46, 50],
                "goal": "决战",
                "must_close_by_end": ["契约站瓦解"],
            },
        ],
    }
    (tmp_path / "plot_arc.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


# ---------------- 1. plot_arc present → injected ----------------

def test_planner_reads_plot_arc_when_present(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc(tmp_path)

    _, user, _ = Planner()._build_prompts(bb, chapter=8)
    assert "全书坐标系" in user
    assert "当前 act" in user
    assert "卷一·暗格觉醒" in user
    # 进度条数字
    assert "ch8/50" in user or "ch8" in user
    # act 内进度
    assert "ch8/15" in user or "act 内进度" in user


# ---------------- 2. plot_arc absent → no crash, no block ----------------

def test_planner_works_without_plot_arc(tmp_path):
    bb = _seed_basic(tmp_path)
    # No plot_arc.yaml written.
    _, user, inputs = Planner()._build_prompts(bb, chapter=1)
    # Should not raise; block must not be present.
    assert "全书坐标系" not in user
    assert "state/plot_arc.yaml" not in inputs


# ---------------- 3. inputs_read includes plot_arc.yaml ----------------

def test_planner_inputs_read_includes_plot_arc(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc(tmp_path)
    _, _, inputs = Planner()._build_prompts(bb, chapter=8)
    assert "state/plot_arc.yaml" in inputs


# ---------------- 4. act_finale warning shows up ----------------

def test_planner_act_finale_warning_in_prompt(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc(tmp_path)
    _, user, _ = Planner()._build_prompts(bb, chapter=15)  # 卷一末
    assert "⚠" in user
    assert "必须收束" in user
    # must_close 项应被列出
    assert "金属片用途" in user
    assert "灰风衣身份初现" in user


# ---------------- 5. mid-act → no act_finale warning ----------------

def test_planner_no_warning_in_mid_act(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc(tmp_path)
    _, user, _ = Planner()._build_prompts(bb, chapter=8)
    # Mid-act should still show 全书坐标系 but NOT the act_finale warning.
    assert "全书坐标系" in user
    assert "act_finale" not in user
    # 没有"⚠ **本章是当前 act 的最后一章" 这个特定 finale warning
    # （但仍有可能含其他 ⚠ 在别处——所以用更具体的字符串）
    assert "本章是当前 act 的最后一章" not in user


# ---------------- 6. system prompt has plot_arc rules ----------------

def test_planner_system_prompt_has_plot_arc_rules(tmp_path):
    bb = _seed_basic(tmp_path)
    _write_plot_arc(tmp_path)
    system, _, _ = Planner()._build_prompts(bb, chapter=8)
    assert "全书坐标系优先" in system
    assert "act_finale" in system
    assert "场景去重律" in system


# ---------------- 7. malformed plot_arc → silent fallback ----------------

def test_planner_silent_on_malformed_plot_arc(tmp_path):
    bb = _seed_basic(tmp_path)
    # Write an invalid plot_arc.yaml (gap)
    (tmp_path / "plot_arc.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "total_chapters": 10,
                "ultimate_goal": "x",
                "acts": [
                    {"name": "A", "range": [1, 4], "goal": "", "must_close_by_end": []},
                    # gap: skips ch5
                    {"name": "B", "range": [6, 10], "goal": "", "must_close_by_end": []},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    # Should not raise; falls back to no plot_arc block.
    _, user, inputs = Planner()._build_prompts(bb, chapter=1)
    assert "全书坐标系" not in user
    assert "state/plot_arc.yaml" not in inputs

"""Tests for Planner new fields: chapter_type, advances, writing_self_check,
status card + pending hooks consumption, golden-three feedback hint (C-31).

These tests are LLM-free — they exercise _build_prompts and helper logic only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents.planner import Planner, _collect_golden_three_hooks


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "都市言情", "era": "2024", "tone": "克制"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "沈若微"}})
    b.write_json(
        "outline.json",
        {
            "chapters": [
                {"ch": i, "title": f"第{i}章", "beats": [f"beat{i}"]}
                for i in range(1, 6)
            ]
        },
    )
    (tmp_path / "chapters").mkdir(exist_ok=True)
    (tmp_path / "summaries").mkdir(exist_ok=True)
    return b


# -------- chapter_type + advances requirement in prompt --------

def test_planner_prompt_requires_chapter_type(bb):
    system, user, _ = Planner()._build_prompts(bb, chapter=1)
    assert "chapter_type" in system
    # four types listed
    assert "战斗" in system and "布局" in system and "过渡" in system and "回收" in system


def test_planner_prompt_requires_scene_advances(bb):
    system, _, _ = Planner()._build_prompts(bb, chapter=1)
    assert "advances" in system
    # advances menu
    for token in ("信息", "地位", "资源", "伤亡", "仇恨", "境界"):
        assert token in system


def test_planner_output_schema_mentions_new_fields(bb):
    _, user, _ = Planner()._build_prompts(bb, chapter=1)
    assert '"chapter_type"' in user
    assert '"advances"' in user
    assert '"writing_self_check"' in user
    # all 6 self-check keys
    for key in (
        "ooc_risk",
        "info_leak_risk",
        "setting_conflict_risk",
        "power_scaling_risk",
        "pacing_risk",
        "vocab_fatigue_risk",
    ):
        assert key in user


# -------- status card + pending hooks consumption --------

def test_planner_mentions_status_card_in_user_prompt(bb):
    _, user, _ = Planner()._build_prompts(bb, chapter=1)
    assert "当前状态卡" in user
    # without any card yet, the placeholder text should be present
    assert "尚无状态卡" in user or "首章" in user


def test_planner_loads_existing_status_card(bb):
    bb.write_text("current_status_card.md", "# 当前状态卡\n\n| 当前章 | ch2 |")
    _, user, inputs = Planner()._build_prompts(bb, chapter=2)
    assert "state/current_status_card.md" in inputs
    assert "当前章 | ch2" in user


def test_planner_reads_pending_hooks_when_present(bb):
    bb.write_text("pending_hooks.md", "# 待回收伏笔池\n\n| hook_id | state |")
    _, user, inputs = Planner()._build_prompts(bb, chapter=2)
    assert "state/pending_hooks.md" in inputs
    assert "待回收伏笔池" in user


def test_planner_handles_missing_pending_hooks_gracefully(bb):
    _, user, inputs = Planner()._build_prompts(bb, chapter=1)
    # No pending_hooks file → placeholder text is printed, path NOT in inputs
    assert "state/pending_hooks.md" not in inputs
    assert "尚无伏笔池" in user


# -------- golden-three feedback hint (C-31) --------

def test_golden_three_only_activates_at_chapter_3(bb):
    for ch in (1, 2, 4, 5, 10):
        text, inputs = _collect_golden_three_hooks(bb, ch)
        assert text == ""
        assert inputs == []


def test_golden_three_chapter_3_without_plans_still_warns(bb):
    text, inputs = _collect_golden_three_hooks(bb, 3)
    assert "黄金三章" in text
    assert inputs == []


def test_golden_three_chapter_3_with_prior_plans_lists_hooks(bb):
    bb.write_json(
        "chapters/ch001.plan.json",
        {"opening_hook": "开篇1", "closing_hook": "悬念1"},
    )
    bb.write_json(
        "chapters/ch002.plan.json",
        {"opening_hook": "", "closing_hook": "悬念2"},
    )
    text, inputs = _collect_golden_three_hooks(bb, 3)
    assert "悬念1" in text
    assert "悬念2" in text
    assert "state/chapters/ch001.plan.json" in inputs
    assert "state/chapters/ch002.plan.json" in inputs


def test_planner_user_prompt_includes_golden_three_at_ch3(bb):
    bb.write_json(
        "chapters/ch001.plan.json",
        {"opening_hook": "o1", "closing_hook": "c1"},
    )
    bb.write_json(
        "chapters/ch002.plan.json",
        {"opening_hook": "o2", "closing_hook": "c2"},
    )
    _, user, inputs = Planner()._build_prompts(bb, chapter=3)
    assert "黄金三章" in user
    assert "c1" in user
    assert "state/chapters/ch001.plan.json" in inputs


def test_planner_ch1_user_prompt_has_no_golden_three_block(bb):
    _, user, _ = Planner()._build_prompts(bb, chapter=1)
    assert "黄金三章" not in user

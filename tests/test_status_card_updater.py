"""pytest-style tests for StatusCardUpdater (C-23)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents.status_card_updater import (
    StatusCardUpdater,
    read_current_status_card,
    STATUS_CARD_SKELETON,
)


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "都市言情", "era": "2024"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "沈若微"}})
    (tmp_path / "chapters").mkdir(exist_ok=True)
    return b


# -------- prompt-building branches --------

def test_prompt_ch1_no_prior_card_uses_skeleton(bb):
    bb.write_text("chapters/ch001.md", "# 第一章\n\n沈若微在地铁里收到消息。")
    system, user, inputs = StatusCardUpdater()._build_prompts(bb, chapter=1)
    assert "状态卡维护员" in system or "current_status_card.md" in system
    assert "首次生成" in user or "首章" in user
    # Skeleton is shown as the diff base
    assert "当前状态卡" in user
    assert "state/chapters/ch001.md" in inputs
    # First run: prior card does not exist yet → NOT in inputs
    assert "state/current_status_card.md" not in inputs


def test_prompt_ch2_with_prior_card_uses_diff_mode(bb):
    bb.write_text("current_status_card.md", "# 当前状态卡\n\n| 当前章 | ch1 |")
    bb.write_text("chapters/ch002.md", "# 第二章\n\n沈若微做了一个决定。")
    system, user, inputs = StatusCardUpdater()._build_prompts(bb, chapter=2)
    assert "state/current_status_card.md" in inputs
    # Prior card is passed through to the LLM for diffing
    assert "当前章 | ch1" in user
    # LLM is told to "update" not "initialize"
    assert "覆盖过期字段" in user or "diff 基准" in user


def test_prompt_includes_genre_and_era_from_setting(bb):
    bb.write_text("chapters/ch001.md", "# 第一章\n正文")
    system, _, _ = StatusCardUpdater()._build_prompts(bb, chapter=1)
    assert "都市言情" in system
    assert "2024" in system


def test_prompt_lesson3_boundary_forbids_reading_plan_verdict_issues(bb):
    bb.write_text("chapters/ch001.md", "正文")
    system, _, _ = StatusCardUpdater()._build_prompts(bb, chapter=1)
    # The explicit boundary: NEVER read plan / verdict / issues
    assert "不读" in system and "plan" in system


def test_skeleton_constant_has_all_required_sections():
    # Skeleton document hygiene — all 7 sections declared
    for section in (
        "时间与位置锚点",
        "主角当前状态",
        "主角本章目标与限制",
        "当前敌我关系",
        "当前资源与收益账本",
        "当前已知真相",
        "当前活跃伏笔",
        "下一章任务卡",
    ):
        assert section in STATUS_CARD_SKELETON


def test_skeleton_hooks_section_is_pointer_not_table():
    """2026-05-15 解耦：『当前活跃伏笔』段不再维护伏笔表（与 pending_hooks.md
    职能 100% 重叠），改为一行指针。HookKeeper 是权威来源。"""
    # 段标题保留（让作者知道伏笔在哪查）
    assert "## 当前活跃伏笔" in STATUS_CARD_SKELETON
    # 指向 pending_hooks.md 的指针存在
    assert "pending_hooks.md" in STATUS_CARD_SKELETON
    # 旧的伏笔表表头（预期回收窗口 / 待推进 等）已删除
    # （注：『下一章任务卡』里『建议推进的伏笔 | (hook_id 列表)』保留，是给
    # Planner 的引用提示，不是登记本身。）
    assert "预期回收窗口" not in STATUS_CARD_SKELETON
    assert "待推进/推进中/待回收" not in STATUS_CARD_SKELETON
    # 旧伏笔表 6 列表头（hook_id | 起始章 | 类型 | 当前状态 | 最近推进 | 预期回收窗口）
    # 整行已删除
    assert "起始章 | 类型 | 当前状态" not in STATUS_CARD_SKELETON
    # 提取『当前活跃伏笔』段验证段内不再有 6 列伏笔表
    start = STATUS_CARD_SKELETON.find("## 当前活跃伏笔")
    end = STATUS_CARD_SKELETON.find("## 下一章任务卡")
    section = STATUS_CARD_SKELETON[start:end]
    assert "hook_id" not in section, (
        "『当前活跃伏笔』段内仍有 hook_id 表头——应已替换为指针"
    )


def test_system_prompt_delegates_hooks_to_hookkeeper(bb):
    """system prompt 必须明确说明伏笔由 HookKeeper 接管，本卡不再登记。"""
    bb.write_text("chapters/ch001.md", "# 第一章\n正文")
    system, _, _ = StatusCardUpdater()._build_prompts(bb, chapter=1)
    assert "HookKeeper" in system
    assert "pending_hooks.md" in system
    # 旧的『本章新埋的未回收伏笔 → 加新行』已删除
    assert "新埋的未回收伏笔" not in system
    assert "从表中删除" not in system


# -------- output handling --------

def test_handle_output_strips_markdown_fences(bb):
    fenced = "```markdown\n# 当前状态卡\n\n| a | b |\n| - | - |\n| x | y |\n```"
    StatusCardUpdater()._handle_output(bb, fenced, chapter=2)
    text = bb.read_text("current_status_card.md")
    assert text.startswith("# 当前状态卡")
    assert "```" not in text


def test_handle_output_plain_markdown(bb):
    plain = "# 当前状态卡\n\n| a | b |\n| - | - |\n| 1 | 2 |"
    StatusCardUpdater()._handle_output(bb, plain, chapter=1)
    text = bb.read_text("current_status_card.md")
    assert text.startswith("# 当前状态卡")
    assert "```" not in text


def test_handle_output_is_overwriting_not_appending(bb):
    # Seed an old card, run handle_output, confirm old content is gone
    bb.write_text("current_status_card.md", "OLD CONTENT SHOULD DISAPPEAR")
    StatusCardUpdater()._handle_output(bb, "# 当前状态卡\n\n新内容", chapter=5)
    text = bb.read_text("current_status_card.md")
    assert "OLD CONTENT" not in text
    assert "新内容" in text


# -------- read_current_status_card helper --------

def test_read_helper_exists_branch(bb):
    bb.write_text("current_status_card.md", "# 当前状态卡\n\nxxx")
    text, inputs = read_current_status_card(bb)
    assert "当前状态卡" in text
    assert inputs == ["state/current_status_card.md"]


def test_read_helper_missing_branch(bb):
    text, inputs = read_current_status_card(bb)
    assert "尚无状态卡" in text
    assert inputs == []

"""CharacterGuard direct unit tests (P2).

Auditor fan-out 伙伴之一；职责是扫人设偏移。过去只在 test_fact_checker.py
间接验证调度，现在加直接单测覆盖：
- prompt 构造（读 characters.yaml + 历史 summaries）
- 职责隔离（不读 plan.json / verdict.json）
- 输出解析（正常 / 空 summaries 兜底）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.auditors.character_guard import CharacterGuard


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    (tmp_path / "chapters").mkdir(exist_ok=True)
    (tmp_path / "summaries").mkdir(exist_ok=True)
    (tmp_path / "fixes").mkdir(exist_ok=True)
    b.write_yaml(
        "characters.yaml",
        {"protagonist": {"name": "林家耀", "traits": ["极致利己"]}},
    )
    return b


def test_character_guard_reads_characters_and_history(bb):
    bb.write_text("summaries/ch001.md", "第一章摘要：林家耀出场。")
    bb.write_text("summaries/ch002.md", "第二章摘要：林家耀和阿Sir对峙。")
    bb.write_text("chapters/ch003.md", "第三章正文内容。")

    system, user, inputs = CharacterGuard()._build_prompts(bb, chapter=3)
    assert "state/chapters/ch003.md" in inputs
    assert "state/characters.yaml" in inputs
    assert "state/summaries/ch001.md" in inputs
    assert "state/summaries/ch002.md" in inputs
    # characters.yaml 内容被嵌入 user prompt
    assert "林家耀" in user
    assert "第一章摘要" in user
    # system 明确只管人设
    assert "OOC" in system or "人设" in system


def test_character_guard_does_not_read_plan_or_verdict(bb):
    """职责隔离：不读 plan.json / verdict.json。"""
    bb.write_text("chapters/ch001.md", "正文")
    bb.write_json("chapters/ch001.plan.json", {"note": "PLAN_LEAK_TOKEN"})
    bb.write_json("chapters/ch001.verdict.json", {"note": "VERDICT_LEAK_TOKEN"})

    _, user, inputs = CharacterGuard()._build_prompts(bb, chapter=1)
    assert not any("plan.json" in p for p in inputs)
    assert not any("verdict.json" in p for p in inputs)
    assert "PLAN_LEAK_TOKEN" not in user
    assert "VERDICT_LEAK_TOKEN" not in user


def test_character_guard_tolerates_missing_summaries(bb):
    """第 1 章无历史 summaries — inputs_read 中没有 summaries，但 prompt 不崩。"""
    bb.write_text("chapters/ch001.md", "首章正文")

    _, user, inputs = CharacterGuard()._build_prompts(bb, chapter=1)
    summary_inputs = [p for p in inputs if "summaries/" in p]
    assert summary_inputs == []
    # 占位文案出现在 user prompt 里
    assert "首章" in user or "无前情" in user


def test_character_guard_parses_audit_output(bb, monkeypatch):
    bb.write_text("chapters/ch003.md", "第三章正文")

    audit_json = json.dumps({
        "ooc_score": 5,
        "hits": [
            {
                "character": "林家耀",
                "deviation": "对小孩突然圣母心发作",
                "prior_baseline": "traits=['极致利己']",
                "suggested_fix": "改成冷漠扭头离开",
            }
        ],
    }, ensure_ascii=False)

    def fake_chat(*, agent_name, **_):
        assert agent_name == "character_guard"
        return audit_json

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    CharacterGuard().run(bb, chapter=3)
    patch = bb.read_text("fixes/ch003.char-patch.md")
    assert "CharacterGuard 补丁" in patch
    assert "5 / 10" in patch
    assert "林家耀" in patch
    assert "圣母心发作" in patch
    assert "冷漠扭头" in patch


def test_character_guard_handles_bad_json_gracefully(bb, monkeypatch):
    """解析失败不抛异常；patch 写入占位。"""
    bb.write_text("chapters/ch001.md", "正文")

    def fake_chat(**_):
        return "not valid json {{"

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    CharacterGuard().run(bb, chapter=1)
    patch = bb.read_text("fixes/ch001.char-patch.md")
    assert "CharacterGuard 补丁" in patch
    assert "-1" in patch
    assert "命中数**：0" in patch


def test_character_guard_truncates_summaries_when_cast_absent(bb):
    """ch30 + 无 cast → 只读最近 5 章 summaries（ch25-29），不是全部 29 份。

    历史 bug：旧实现 `for n in range(1, chapter)` 把全部历史摘要拼进 prompt，
    ch30+ 时单 LLM 调用就吞 25K+ tokens。2026-05-15 解耦：
    - cast 存在 → 不读 summaries（cast 是更高密度的先例库）
    - cast 不存在 → 仅读最近 5 章 summaries（窗口化）
    """
    # 准备 ch1..ch29 的 summaries 和 ch30 的正文（无 cast）
    for n in range(1, 30):
        bb.write_text(f"summaries/ch{n:03d}.md", f"第 {n} 章摘要内容。")
    bb.write_text("chapters/ch030.md", "# 第 30 章\n正文。")

    _, user, inputs = CharacterGuard()._build_prompts(bb, chapter=30)

    summary_inputs = [p for p in inputs if "summaries/" in p]
    # 只应有 ch25..ch29 共 5 份
    assert len(summary_inputs) == 5, (
        f"expected 5 summaries (ch25-29), got {len(summary_inputs)}: {summary_inputs}"
    )
    expected = {f"state/summaries/ch{n:03d}.md" for n in range(25, 30)}
    assert set(summary_inputs) == expected
    # ch01..ch24 必须不在 inputs / user
    for n in (1, 5, 10, 20, 24):
        assert f"state/summaries/ch{n:03d}.md" not in inputs
        assert f"第 {n} 章摘要内容。" not in user
    # ch29 必须在 user（窗口边界）
    assert "第 29 章摘要内容。" in user


def test_character_guard_skips_summaries_when_cast_present(bb):
    """cast 存在 → 不读任何 summaries（cast 是更高密度先例库，summaries 冗余）。"""
    bb.write_yaml(
        "characters-cast.yaml",
        {"schema_version": 1, "last_updated_chapter": 9, "cast": []},
    )
    for n in range(1, 10):
        bb.write_text(f"summaries/ch{n:03d}.md", f"第 {n} 章摘要内容。")
    bb.write_text("chapters/ch010.md", "# 第 10 章\n正文。")

    _, user, inputs = CharacterGuard()._build_prompts(bb, chapter=10)

    summary_inputs = [p for p in inputs if "summaries/" in p]
    assert summary_inputs == [], (
        f"cast present should disable summaries reading, got: {summary_inputs}"
    )
    # 但 cast 必须读
    assert "state/characters-cast.yaml" in inputs

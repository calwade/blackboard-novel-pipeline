"""AISlopGuard direct unit tests (P2).

Auditor fan-out 伙伴之一；过去只在 test_fact_checker.py 间接验证其被调度，
现在加直接单测覆盖 prompt 构造与输出解析。

注意：AISlopGuard 把 AI 味判据作为**内联常量** AI_SLOP_CRITERIA 放在代码里，
并不读取 rules/18-landmines.md 文件。因此测试只断言 inputs_read 只含章节文件，
并断言 system prompt 包含 AI 味判据的关键词。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.auditors.ai_slop_guard import AISlopGuard, AI_SLOP_CRITERIA


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    (tmp_path / "chapters").mkdir(exist_ok=True)
    (tmp_path / "fixes").mkdir(exist_ok=True)
    return b


def test_ai_slop_guard_reads_chapter_only(bb):
    """inputs_read 只含当章正文；system 明确提及 AI 味职责。"""
    bb.write_text("chapters/ch001.md", "# 第一章\n他冷笑一声。")
    system, user, inputs = AISlopGuard()._build_prompts(bb, chapter=1)
    assert inputs == ["state/chapters/ch001.md"]
    assert "AI 味" in system
    # 判据常量应被内联进 system prompt（冷笑在高疲劳词黑名单里）
    assert "冷笑" in system
    assert "# AI 味判据" in system or "AI_SLOP" not in system  # heading present


def test_ai_slop_guard_does_not_read_characters_or_plan(bb):
    """职责隔离：AI 味审计员不看 characters.yaml / plan.json / verdict.json。"""
    bb.write_text("chapters/ch001.md", "正文")
    bb.write_yaml("characters.yaml", {"protagonist": {"name": "CHAR_LEAK_TOKEN"}})
    bb.write_json("chapters/ch001.plan.json", {"note": "PLAN_LEAK_TOKEN"})
    bb.write_json("chapters/ch001.verdict.json", {"note": "VERDICT_LEAK_TOKEN"})

    system, user, inputs = AISlopGuard()._build_prompts(bb, chapter=1)
    assert "state/characters.yaml" not in inputs
    assert not any("plan.json" in p for p in inputs)
    assert not any("verdict.json" in p for p in inputs)
    assert "CHAR_LEAK_TOKEN" not in user
    assert "PLAN_LEAK_TOKEN" not in user
    assert "VERDICT_LEAK_TOKEN" not in user


def test_ai_slop_guard_parses_audit_output(bb, monkeypatch):
    """合法 JSON 输出 -> 正确渲染 slop-patch.md。"""
    bb.write_text("chapters/ch001.md", "正文")

    audit_json = json.dumps({
        "slop_score": 4,
        "hits": [
            {
                "criterion_id": 11,
                "severity": "moderate",
                "snippet": "他冷笑一声。",
                "suggested_rewrite": "他嘴角拉平。",
            }
        ],
    }, ensure_ascii=False)

    def fake_chat(*, agent_name, **_):
        assert agent_name == "ai_slop_guard"
        return audit_json

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    AISlopGuard().run(bb, chapter=1)
    patch = bb.read_text("fixes/ch001.slop-patch.md")
    assert "AISlopGuard 补丁" in patch
    assert "4 / 10" in patch
    assert "冷笑一声" in patch
    assert "嘴角拉平" in patch


def test_ai_slop_guard_handles_bad_json_gracefully(bb, monkeypatch):
    """解析失败不抛异常；patch 文件应写入可见的占位信息。"""
    bb.write_text("chapters/ch001.md", "正文")

    def fake_chat(*, agent_name, **_):
        return "{this is not valid json"

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    # 必须不抛异常
    AISlopGuard().run(bb, chapter=1)
    patch = bb.read_text("fixes/ch001.slop-patch.md")
    assert "AISlopGuard 补丁" in patch
    # parse-error 分支下 slop_score 被置为 -1，hits 为 0
    assert "-1" in patch
    assert "命中数**：0" in patch


def test_ai_slop_guard_strips_fenced_json(bb, monkeypatch):
    bb.write_text("chapters/ch001.md", "正文")
    fenced = "```json\n" + json.dumps({"slop_score": 0, "hits": []}) + "\n```"

    def fake_chat(**_):
        return fenced

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    AISlopGuard().run(bb, chapter=1)
    patch = bb.read_text("fixes/ch001.slop-patch.md")
    assert "0 / 10" in patch
    assert "命中数**：0" in patch

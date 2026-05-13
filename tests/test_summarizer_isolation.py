"""Summarizer isolation tests (P2).

Lesson-3 防 framing 泄漏的最硬约束：Summarizer 对每章的唯一输入是
state/chapters/ch{N:03d}.md。它绝对不能读 plan.json / verdict.json /
issues.jsonl — 否则 Generator 的自我叙事会透过 summary 污染未来的 Planner。

这几项直接单测覆盖该约束，防止有人无意间在 _build_prompts 里塞进其他文件。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents.summarizer import Summarizer


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    (tmp_path / "chapters").mkdir(exist_ok=True)
    (tmp_path / "summaries").mkdir(exist_ok=True)
    return b


def test_summarizer_only_reads_chapter_prose(bb):
    """Core Lesson-3 guarantee: inputs_read contains ONLY the chapter file."""
    bb.write_text("chapters/ch001.md", "# 第一章\n林家耀走进汇丰楼下。")
    # Seed plan/verdict/issues — Summarizer must NOT read them
    bb.write_json("chapters/ch001.plan.json", {"ch": 1, "secret_framing": "X"})
    bb.write_json("chapters/ch001.verdict.json", {"overall_pass": False})
    bb.write_text("issues.jsonl", '{"issue": "leaked framing"}\n')

    system, user, inputs_read = Summarizer()._build_prompts(bb, chapter=1)
    assert inputs_read == ["state/chapters/ch001.md"]
    # User prompt must not contain any of the forbidden content
    assert "secret_framing" not in user
    assert "overall_pass" not in user
    assert "leaked framing" not in user


def test_summarizer_does_not_read_plan_even_if_exists(bb):
    bb.write_text("chapters/ch002.md", "正文内容")
    bb.write_json("chapters/ch002.plan.json", {"opening_hook": "FRAMING_LEAK_TOKEN"})
    _, user, inputs_read = Summarizer()._build_prompts(bb, chapter=2)
    assert "state/chapters/ch002.plan.json" not in inputs_read
    assert "FRAMING_LEAK_TOKEN" not in user


def test_summarizer_does_not_read_verdict_even_if_exists(bb):
    bb.write_text("chapters/ch003.md", "正文内容")
    bb.write_json(
        "chapters/ch003.verdict.json",
        {"top_3_fixes": [{"note": "VERDICT_LEAK_TOKEN"}]},
    )
    _, user, inputs_read = Summarizer()._build_prompts(bb, chapter=3)
    assert "state/chapters/ch003.verdict.json" not in inputs_read
    assert "VERDICT_LEAK_TOKEN" not in user


def test_summarizer_writes_to_summaries_dir(bb, monkeypatch):
    bb.write_text("chapters/ch001.md", "原文")

    def fake_chat(*, system, user, agent_name, **_):
        assert agent_name == "summarizer"
        return "第一章摘要内容"

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    Summarizer().run(bb, chapter=1)
    assert bb.exists("summaries/ch001.md")
    assert bb.read_text("summaries/ch001.md").strip() == "第一章摘要内容"


def test_summarizer_temperature_is_low():
    """temp=0.2 限制摘要漂移；Lesson-3 要求摘要客观白描。"""
    assert Summarizer.temperature == 0.2
    assert Summarizer.response_format == "text"

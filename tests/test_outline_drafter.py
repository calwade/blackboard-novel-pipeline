"""OutlineDrafter: synopsis (free text) → structured outline.json."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def stub_llm(monkeypatch):
    """Patch the shared LLM client to return a canned JSON string.

    注意：这里故意用 `index` 字段模拟模型可能返回的旧字段名，
    drafter 应当把它归一化为契约字段 `ch`。
    """
    def fake_chat(system, user, *, agent_name, **kwargs):
        return json.dumps({
            "title": "Test Book",
            "chapters": [
                {"index": 1, "title": "Arrival", "beats": ["开场", "建立冲突"]},
                {"index": 2, "title": "Plot Thickens", "beats": ["反转"]},
            ]
        }, ensure_ascii=False)
    monkeypatch.setattr("src.llm.chat", fake_chat)
    return fake_chat


def test_outline_drafter_produces_structured_outline(stub_llm):
    from src.agents.outline_drafter import OutlineDrafter
    agent = OutlineDrafter()
    out = agent.run(
        synopsis="主角从福建来港，加入社团，一年内做大。",
        chapter_count_target=2,
        display_name="Test Book",
    )
    assert out["title"] == "Test Book"
    assert len(out["chapters"]) == 2
    # 契约字段是 ch，不是 index（Planner/Packaging 消费 c["ch"]）
    assert out["chapters"][0]["ch"] == 1
    assert out["chapters"][1]["ch"] == 2
    # 旧字段应被清理，防止下游看到两份序号
    assert "index" not in out["chapters"][0]
    assert "beats" in out["chapters"][0]


def test_outline_drafter_empty_synopsis_returns_blank_shell():
    from src.agents.outline_drafter import OutlineDrafter
    agent = OutlineDrafter()
    out = agent.run(synopsis="", chapter_count_target=10, display_name="Blank")
    assert out["title"] == "Blank"
    assert out["chapters"] == []


def test_outline_drafter_falls_back_to_shell_on_bad_json(monkeypatch):
    """If LLM returns non-JSON gibberish, return a blank shell instead of crashing."""
    def bad_chat(system, user, *, agent_name, **kwargs):
        return "not valid json at all"
    monkeypatch.setattr("src.llm.chat", bad_chat)
    from src.agents.outline_drafter import OutlineDrafter
    agent = OutlineDrafter()
    out = agent.run(synopsis="something", chapter_count_target=5, display_name="X")
    assert out["title"] == "X"
    assert isinstance(out["chapters"], list)  # shell, not crash


def test_outline_drafter_enforces_max_chapters(stub_llm):
    """Even if LLM returns more chapters than requested, keep only the first N."""
    # already 2 in stub; request 1 → truncate
    from src.agents.outline_drafter import OutlineDrafter
    agent = OutlineDrafter()
    out = agent.run(synopsis="xxx", chapter_count_target=1, display_name="T")
    assert len(out["chapters"]) == 1

"""OutlineDrafter schema 契约测试（P0-1 回归防护）。

问题背景：OutlineDrafter 早期版本把章节序号字段写成 `index`，但 Planner
(`src/agents/planner.py`) 和 Packaging (`src/agents/packaging.py`) 消费的都是 `ch`。
导致新向导起草的 outline.json 拿去跑 ch1 会立刻抛
`ValueError(f"Chapter {chapter} not in outline")`。

本测试锁定契约：drafter 必须输出 `ch` 字段，不管模型返回 `index` 还是 `ch`
还是两者皆无，都要归一化到 `ch`，并且可以被 Planner 的查找逻辑命中。
"""
from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers: 不同"模型返回风格"的 stub
# ---------------------------------------------------------------------------

def _patch_llm(monkeypatch, payload: dict) -> None:
    """用给定的 JSON payload 替换 src.llm.chat。"""
    def fake_chat(system, user, *, agent_name, **kwargs):
        return json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr("src.llm.chat", fake_chat)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_drafter_normalizes_index_to_ch(monkeypatch):
    """模型返回 `index` 字段（旧 schema），drafter 必须转成 `ch`。"""
    _patch_llm(monkeypatch, {
        "title": "测试书",
        "chapters": [
            {"index": 1, "title": "序章", "beats": ["开场", "建立冲突"]},
            {"index": 2, "title": "中盘", "beats": ["反转", "小高潮"]},
            {"index": 3, "title": "尾声", "beats": ["收束", "钩子"]},
        ],
    })
    from src.agents.outline_drafter import OutlineDrafter
    out = OutlineDrafter().run(
        synopsis="一段梗概", chapter_count_target=3, display_name="测试书"
    )
    assert len(out["chapters"]) == 3
    for i, ch in enumerate(out["chapters"], start=1):
        assert ch["ch"] == i, f"chapter {i} 必须有 ch 字段"
        assert "index" not in ch, "index 旧字段必须被清理"


def test_drafter_preserves_ch_field(monkeypatch):
    """模型返回 `ch` 字段（新 schema），drafter 应保留并强制连续。"""
    _patch_llm(monkeypatch, {
        "title": "测试书",
        "chapters": [
            {"ch": 1, "title": "序章", "beats": ["开场", "冲突"]},
            {"ch": 2, "title": "中盘", "beats": ["反转", "高潮"]},
            {"ch": 3, "title": "尾声", "beats": ["收束", "钩子"]},
        ],
    })
    from src.agents.outline_drafter import OutlineDrafter
    out = OutlineDrafter().run(
        synopsis="一段梗概", chapter_count_target=3, display_name="测试书"
    )
    assert [c["ch"] for c in out["chapters"]] == [1, 2, 3]


def test_drafter_output_is_planner_compatible(monkeypatch):
    """回归保护：drafter 产物能被 Planner 的查找逻辑命中。

    Planner 的代码：`next((c for c in chapters if c["ch"] == chapter), None)`
    如果 drafter 输出里没有 `ch` 字段，这里会 KeyError 或返回 None，
    触发 `ValueError(f"Chapter {chapter} not in outline")`。
    """
    _patch_llm(monkeypatch, {
        "title": "测试书",
        "chapters": [
            {"index": 1, "title": "A", "beats": ["a1", "a2"]},
            {"index": 2, "title": "B", "beats": ["b1", "b2"]},
            {"index": 3, "title": "C", "beats": ["c1", "c2"]},
        ],
    })
    from src.agents.outline_drafter import OutlineDrafter
    out = OutlineDrafter().run(
        synopsis="x", chapter_count_target=3, display_name="测试书"
    )
    chapters = out["chapters"]

    # 模拟 Planner 的查找逻辑（src/agents/planner.py:34）
    cur = next((c for c in chapters if c["ch"] == 1), None)
    assert cur is not None, "Planner 的 next() 查找必须命中 ch=1"
    assert cur["title"] == "A"

    cur3 = next((c for c in chapters if c["ch"] == 3), None)
    assert cur3 is not None
    assert cur3["title"] == "C"


def test_drafter_empty_synopsis_returns_shell_with_empty_chapters():
    """synopsis 为空走 shell 分支，返回 {title, chapters: []}，不调 LLM。"""
    from src.agents.outline_drafter import OutlineDrafter
    out = OutlineDrafter().run(
        synopsis="", chapter_count_target=5, display_name="空壳书"
    )
    assert out == {"title": "空壳书", "chapters": []}

    # whitespace-only 也应该走 shell
    out2 = OutlineDrafter().run(
        synopsis="   \n\t  ", chapter_count_target=5, display_name="空壳书"
    )
    assert out2 == {"title": "空壳书", "chapters": []}


def test_drafter_handles_chapters_without_any_index_field(monkeypatch):
    """模型忘了写序号字段，drafter 必须用循环序号兜底。"""
    _patch_llm(monkeypatch, {
        "title": "测试书",
        "chapters": [
            {"title": "A", "beats": ["a1"]},
            {"title": "B", "beats": ["b1"]},
        ],
    })
    from src.agents.outline_drafter import OutlineDrafter
    out = OutlineDrafter().run(
        synopsis="x", chapter_count_target=2, display_name="测试书"
    )
    assert [c["ch"] for c in out["chapters"]] == [1, 2]

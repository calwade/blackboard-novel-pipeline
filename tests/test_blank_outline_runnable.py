"""Regression: blank outline 必须能跑通 Planner（不能 chapters=[]）。

历史 bug：create_project(blank_outline=True) 写 `{"chapters": []}`，而
Planner 按 `ch` 字段 next() 查当前章节条目 —— 找不到就 raise
`ValueError("Chapter 1 not in outline")`，流水线第一章直接崩。

修复：blank outline 预填 N 个空壳章节（N = chapter_count_target），让
Planner 依赖 status_card + pending_hooks + 前情摘要即兴写；并给 Planner
加防御性兜底，处理历史坏数据或作者手动删条目的情况。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixture: fake_repo（模仿 tests/test_bootstrap_book_centric.py）
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch):
    from src import config
    preset = tmp_path / "presets" / "alpha"
    preset.mkdir(parents=True)
    (preset / "genre.yaml").write_text(
        "id: alpha\ndisplay_name: Alpha\ntone: dark\n", encoding="utf-8"
    )
    (preset / "era.md").write_text("# alpha era\n", encoding="utf-8")
    (preset / "writing-style-extra.md").write_text("# alpha style\n", encoding="utf-8")
    (preset / "iron-laws-extra.md").write_text("# alpha laws\n", encoding="utf-8")

    (tmp_path / "projects").mkdir()

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: blank_outline 预填 N 个空壳章节
# ---------------------------------------------------------------------------

def test_blank_outline_prefills_chapters(fake_repo):
    """create_project(blank_outline=True) 必须写 N 个空壳章节，不是 []。"""
    from src.bootstrap import create_project

    book_dir = create_project(
        "blankbook",
        display_name="空壳书",
        protagonist_name="主角",
        chapter_count_target=5,
        from_preset="alpha",
        blank_outline=True,
        blank_characters=True,
    )
    outline = json.loads((book_dir / "outline.json").read_text(encoding="utf-8"))
    assert outline["title"] == "空壳书"
    chapters = outline["chapters"]
    assert len(chapters) == 5, "blank outline 应预填 chapter_count_target 个空壳"
    # 每个条目必须带 ch 字段（Planner 查找的契约键）+ title + 空 beats
    for i, ch in enumerate(chapters, start=1):
        assert ch["ch"] == i
        assert ch["title"] == f"第 {i} 章"
        assert ch["beats"] == []


def test_blank_outline_with_drafter_failure_also_prefills(fake_repo, monkeypatch):
    """OutlineDrafter 失败走兜底分支时，同样要预填 N 个空壳（不是 chapters=[]）。"""
    from src import bootstrap

    # 让 drafter 直接抛异常，触发 except 分支
    def boom(self, *, synopsis, chapter_count_target, display_name):
        raise RuntimeError("simulated LLM failure")

    monkeypatch.setattr("src.agents.outline_drafter.OutlineDrafter.run", boom)

    warnings: list = []
    book_dir = bootstrap.create_project(
        "drafter-fail-book",
        display_name="失败兜底书",
        protagonist_name="H",
        chapter_count_target=4,
        from_preset="alpha",
        outline_synopsis="一段梗概。",
        blank_characters=True,
        warnings_collector=warnings,
    )
    outline = json.loads((book_dir / "outline.json").read_text(encoding="utf-8"))
    # 兜底也要是 4 个空壳，不是 []
    assert len(outline["chapters"]) == 4
    assert outline["chapters"][0] == {"ch": 1, "title": "第 1 章", "beats": []}
    # warnings 记录了 drafter 失败（保留原有语义）
    assert len(warnings) == 1
    assert warnings[0]["field"] == "outline"


# ---------------------------------------------------------------------------
# Test 2: Planner 对残缺 outline 做防御性兜底
# ---------------------------------------------------------------------------

def test_planner_handles_missing_chapter_gracefully(tmp_path):
    """历史坏数据：chapters=[] 也不能让 Planner 抛 ValueError.

    Planner._build_prompts 在找不到当前章节时应该用空壳兜底，继续用
    status_card / pending_hooks / 前情摘要即兴写，而不是直接崩。
    """
    from src.agents.planner import Planner
    from src.blackboard import Blackboard

    bb = Blackboard(root=tmp_path)
    bb.write_json("progress.json", {"current_chapter": 1, "completed": []})
    # 关键：模拟历史坏数据——chapters 为空
    bb.write_json("outline.json", {"title": "T", "chapters": []})
    bb.write_yaml("setting.yaml", {"genre": "通用小说", "era": ""})

    # 不应抛 ValueError；_build_prompts 必须返回三元组
    system, user, inputs = Planner()._build_prompts(bb, chapter=1)
    assert isinstance(system, str) and len(system) > 0
    assert isinstance(user, str) and len(user) > 0
    assert "state/outline.json" in inputs


def test_planner_handles_chapter_not_in_sparse_outline(tmp_path):
    """Outline 里只有 ch1/ch2，跑到 ch5 也不能崩（作者可能边写边扩）。"""
    from src.agents.planner import Planner
    from src.blackboard import Blackboard

    bb = Blackboard(root=tmp_path)
    bb.write_json("progress.json", {"current_chapter": 5, "completed": [1, 2]})
    bb.write_json("outline.json", {
        "title": "T",
        "chapters": [
            {"ch": 1, "title": "开场", "beats": ["a"]},
            {"ch": 2, "title": "发展", "beats": ["b"]},
        ],
    })
    bb.write_yaml("setting.yaml", {"genre": "通用", "era": ""})

    # ch5 不在 outline 里 —— 应用空壳兜底，不抛 ValueError
    system, user, inputs = Planner()._build_prompts(bb, chapter=5)
    assert isinstance(user, str) and len(user) > 0

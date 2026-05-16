"""Tests for Evaluator iron_law_29 进度律 (Oracle P0+P1 修复).

LLM-free — only exercises Evaluator._build_prompts and rule files on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents.evaluator import Evaluator


def _seed_min(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "末世契约", "era": "虫潮后第三年"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "陈牧"}, "supporting": []})
    b.write_text("timeline.yaml", "events: []\n")
    b.write_text("iron-laws-extra.md", "# extra\n")
    (tmp_path / "chapters").mkdir(exist_ok=True)
    b.write_text(
        "chapters/ch006.md",
        "# 第六章\n\n陈牧走出便利店，看着锈蚀的停车场。\n" * 20,
    )
    return b


def _seed_recent_plans(b: Blackboard, tmp_path: Path) -> None:
    """Write 5 plan.json files for ch1..ch5 with intentionally repetitive
    locations + advances to make iron_law_29 detection trivially testable."""
    for n in range(1, 6):
        b.write_json(
            f"chapters/ch{n:03d}.plan.json",
            {
                "ch": n,
                "title": f"第{n}章",
                "chapter_type": "过渡",
                "scenes": [
                    {"scene_id": 1, "location": "便利店", "advances": ["信息"]},
                    {"scene_id": 2, "location": "停车场", "advances": ["信息"]},
                ],
            },
        )


# ---------------- 1. recent plans loaded when chapter >= 2 ----------------

def test_evaluator_loads_recent_plans_when_chapter_gte_2(tmp_path):
    b = _seed_min(tmp_path)
    _seed_recent_plans(b, tmp_path)

    _, user, inputs = Evaluator()._build_prompts(b, chapter=6)

    assert "最近 5 章 plan 对照表" in user
    assert "iron_law_29" in user
    # the table must show actual ch numbers + locations
    assert "便利店" in user
    assert "停车场" in user
    # inputs_read should include each plan path
    for n in range(1, 6):
        assert f"state/chapters/ch{n:03d}.plan.json" in inputs


# ---------------- 2. chapter == 1 → no recent-plans block ----------------

def test_evaluator_skips_recent_plans_at_chapter_1(tmp_path):
    b = _seed_min(tmp_path)
    # Need ch001.md instead of ch006.md for chapter=1
    b.write_text(
        "chapters/ch001.md",
        "# 第一章\n\n陈牧走出便利店，看着锈蚀的停车场。\n" * 20,
    )
    _, user, inputs = Evaluator()._build_prompts(b, chapter=1)
    assert "最近 5 章 plan 对照表" not in user
    # No plan paths in inputs since lookback was empty.
    assert not any("plan.json" in p for p in inputs)


# ---------------- 3. iron_law_29 in iron-laws.md ----------------

def test_iron_law_29_in_iron_laws_md():
    repo = Path(__file__).resolve().parent.parent
    rules_text = (repo / "rules" / "iron-laws.md").read_text(encoding="utf-8")
    assert "iron_law_29" in rules_text
    assert "进度律" in rules_text
    assert "原地打转" in rules_text or "场景循环" in rules_text


# ---------------- 4. plot_arc.yaml in inputs when present ----------------

def test_evaluator_inputs_read_includes_plot_arc_when_present(tmp_path):
    b = _seed_min(tmp_path)
    _seed_recent_plans(b, tmp_path)
    # Bring plot_arc.yaml into the state dir
    import yaml

    (tmp_path / "plot_arc.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "total_chapters": 50,
                "ultimate_goal": "x",
                "acts": [
                    {"name": "A", "range": [1, 50], "goal": "", "must_close_by_end": []},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    _, _, inputs = Evaluator()._build_prompts(b, chapter=6)
    assert "state/plot_arc.yaml" in inputs


# ---------------- 5. plot_arc.yaml absent → not in inputs ----------------

def test_evaluator_inputs_no_plot_arc_when_absent(tmp_path):
    b = _seed_min(tmp_path)
    _seed_recent_plans(b, tmp_path)
    _, _, inputs = Evaluator()._build_prompts(b, chapter=6)
    assert "state/plot_arc.yaml" not in inputs


# ---------------- 6. recent plans block present in docs/rules mirror ----------------

def test_iron_law_29_in_docs_rules_mirror():
    repo = Path(__file__).resolve().parent.parent
    docs_text = (repo / "docs" / "rules" / "iron-laws.md").read_text(encoding="utf-8")
    assert "iron_law_29" in docs_text
    assert "进度律" in docs_text

"""Tests for Evaluator iron_law_30 全局节奏律 (P3 修复).

LLM-free — only exercises Evaluator._build_prompts and rule files.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.blackboard import Blackboard
from src.agents.evaluator import Evaluator


def _seed_min(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "末世", "era": "X"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "陈牧"}, "supporting": []})
    b.write_text("timeline.yaml", "events: []\n")
    b.write_text("iron-laws-extra.md", "# extra\n")
    (tmp_path / "chapters").mkdir(exist_ok=True)
    b.write_text("chapters/ch018.md", "# ch18\n\n陈牧在便利店。\n" * 30)
    return b


def _seed_5_passive_plans(b: Blackboard, start: int = 13) -> None:
    """Seed 5 plans (ch13..ch17) all with chapter_type=过渡 + advances=[信息].
    These should all infer to anchor=None (passive, no payoff)."""
    for n in range(start, start + 5):
        b.write_json(
            f"chapters/ch{n:03d}.plan.json",
            {
                "ch": n,
                "chapter_type": "过渡",
                "scenes": [{"scene_id": 1, "location": "便利店", "advances": ["信息"]}],
            },
        )


def _write_plot_arc_with_milestone(tmp_path: Path) -> None:
    data = {
        "schema_version": 1,
        "total_chapters": 50,
        "ultimate_goal": "x",
        "acts": [
            {"name": "卷一", "range": [1, 15], "must_close_by_end": []},
            {
                "name": "卷二",
                "range": [16, 30],
                "must_close_by_end": [],
                "milestones": [
                    {
                        "chapter": 18,
                        "type": "能力升级·烙印反向",
                        "anchor": "掌控感",
                        "force_chapter_type": "回收",
                        "force_advances": ["境界", "信息"],
                        "beat": "烙印第一次主动闪光帮主角避险",
                    }
                ],
            },
            {"name": "卷三", "range": [31, 45], "must_close_by_end": []},
            {"name": "终卷", "range": [46, 50], "must_close_by_end": []},
        ],
    }
    (tmp_path / "plot_arc.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


# ---------------- 1. global rhythm block injected ----------------

def test_evaluator_injects_global_rhythm_block(tmp_path):
    b = _seed_min(tmp_path)
    _seed_5_passive_plans(b, start=13)
    _write_plot_arc_with_milestone(tmp_path)

    _, user, _ = Evaluator()._build_prompts(b, chapter=18)

    assert "全局节奏检测" in user
    assert "iron_law_30" in user
    assert "anchor 计数" in user
    # All 5 plans were passive → 0 爽感 + 0 掌控感 → flagged
    assert "命中 iron_law_30" in user
    # The section header
    assert "最近" in user and "anchor 推断" in user


# ---------------- 2. milestone warning when current chapter is milestone ----------------

def test_evaluator_warns_at_milestone_chapter(tmp_path):
    b = _seed_min(tmp_path)
    _seed_5_passive_plans(b, start=13)
    _write_plot_arc_with_milestone(tmp_path)

    _, user, _ = Evaluator()._build_prompts(b, chapter=18)

    assert "本章是 plot_arc.yaml 配置的 milestone 章节" in user
    assert "milestone.beat" in user
    assert "能力升级·烙印反向" in user
    assert "掌控感" in user
    assert "≥150 字" in user
    # Severity = high if not delivered
    assert "severity=high" in user


# ---------------- 3. iron_law_30 in iron-laws.md + docs mirror ----------------

def test_iron_law_30_in_iron_laws_md():
    repo = Path(__file__).resolve().parent.parent
    rules_text = (repo / "rules" / "iron-laws.md").read_text(encoding="utf-8")
    assert "iron_law_30" in rules_text
    assert "全局节奏律" in rules_text
    assert "每 5 章必须命中" in rules_text


def test_iron_law_30_in_docs_rules_mirror():
    repo = Path(__file__).resolve().parent.parent
    docs_text = (repo / "docs" / "rules" / "iron-laws.md").read_text(encoding="utf-8")
    assert "iron_law_30" in docs_text
    assert "全局节奏律" in docs_text


# ---------------- 4. no plot_arc → no milestone warning, but rhythm block still works ----------------

def test_evaluator_no_milestone_warning_without_plot_arc(tmp_path):
    b = _seed_min(tmp_path)
    _seed_5_passive_plans(b, start=13)
    # No plot_arc.yaml.
    _, user, _ = Evaluator()._build_prompts(b, chapter=18)

    # Rhythm block still appears (uses recent_plans)
    assert "全局节奏检测" in user
    assert "anchor 计数" in user
    # But milestone warning must be absent
    assert "本章是 plot_arc.yaml 配置的 milestone 章节" not in user


# ---------------- 5. anchor inference: 战斗 + 资源/地位 → 爽感 ----------------

def test_evaluator_recognises_payoff_anchors(tmp_path):
    b = _seed_min(tmp_path)
    # ch16 战斗 + 资源/地位 → 爽感; rest 过渡 + 信息 → None
    b.write_json(
        "chapters/ch016.plan.json",
        {
            "ch": 16,
            "chapter_type": "战斗",
            "scenes": [{"scene_id": 1, "location": "X", "advances": ["地位", "资源"]}],
        },
    )
    for n in range(13, 18):
        if n == 16:
            continue
        b.write_json(
            f"chapters/ch{n:03d}.plan.json",
            {
                "ch": n,
                "chapter_type": "过渡",
                "scenes": [{"scene_id": 1, "location": "X", "advances": ["信息"]}],
            },
        )

    _, user, _ = Evaluator()._build_prompts(b, chapter=18)
    assert "爽感×1" in user
    # Now we DO have a payoff anchor → no flag
    assert "命中 iron_law_30" not in user

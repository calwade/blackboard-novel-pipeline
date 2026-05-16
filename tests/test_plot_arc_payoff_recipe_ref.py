"""Tests for plot_arc.yaml milestone.payoff_recipe_ref + Planner injection (P3 in fix-3).

LLM-free.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.blackboard import Blackboard
from src.agents.planner import Planner, _resolve_recipe
from src.tools.plot_arc import read_plot_arc


def _write(p: Path, data: dict) -> None:
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ---------------- 1. milestone accepts payoff_recipe_ref ----------------

def test_milestone_accepts_payoff_recipe_ref(tmp_path: Path):
    """Both 'anchor' and 'anchor.pattern' forms must validate."""
    data = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 10],
                "must_close_by_end": [],
                "milestones": [
                    {
                        "chapter": 3,
                        "type": "X",
                        "anchor": "爽感",
                        "beat": "B",
                        "payoff_recipe_ref": "爽感",
                    },
                    {
                        "chapter": 7,
                        "type": "Y",
                        "anchor": "掌控感",
                        "beat": "B2",
                        "payoff_recipe_ref": "掌控感.系统机制反制",
                    },
                ],
            }
        ],
    }
    _write(tmp_path / "plot_arc.yaml", data)
    arc = read_plot_arc(tmp_path)
    assert arc is not None
    ms_list = arc.acts[0].milestones
    assert ms_list[0].payoff_recipe_ref == "爽感"
    assert ms_list[1].payoff_recipe_ref == "掌控感.系统机制反制"


# ---------------- 2. Invalid format raises ----------------

def test_milestone_invalid_recipe_ref_format_raises(tmp_path: Path):
    """Anchor-prefix not in VALID_ANCHORS must raise ValueError."""
    data = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 10],
                "must_close_by_end": [],
                "milestones": [
                    {
                        "chapter": 3,
                        "type": "X",
                        "anchor": "爽感",
                        "beat": "B",
                        "payoff_recipe_ref": "非法anchor.X",
                    }
                ],
            }
        ],
    }
    _write(tmp_path / "plot_arc.yaml", data)
    with pytest.raises(ValueError, match=r"anchor part"):
        read_plot_arc(tmp_path)


def test_milestone_recipe_ref_empty_pattern_raises(tmp_path: Path):
    """Empty pattern after dot must raise."""
    data = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {
                "name": "卷一",
                "range": [1, 10],
                "must_close_by_end": [],
                "milestones": [
                    {
                        "chapter": 3,
                        "type": "X",
                        "anchor": "爽感",
                        "beat": "B",
                        "payoff_recipe_ref": "爽感.",
                    }
                ],
            }
        ],
    }
    _write(tmp_path / "plot_arc.yaml", data)
    with pytest.raises(ValueError, match=r"pattern part is empty"):
        read_plot_arc(tmp_path)


# ---------------- 3. _resolve_recipe behavior ----------------

def test_resolve_recipe_anchor_only():
    dna = {
        "payoff_recipes": {
            "爽感": {
                "formula": "冷场→秒杀→点评",
                "dialog_template": [{"speaker": "protagonist", "beats": ["出手"]}],
                "sample_50_chars": "X",
            }
        }
    }
    r = _resolve_recipe(dna, "爽感")
    assert r is not None
    assert r["anchor"] == "爽感"
    assert r["pattern"] is None
    assert "冷场" in r["formula"]


def test_resolve_recipe_with_pattern():
    dna = {
        "payoff_recipes": {
            "掌控感": {"formula": "通用工艺", "dialog_template": [], "sample_50_chars": ""}
        },
        "villain_defeat_patterns": [
            {
                "pattern": "系统机制反制",
                "setup": "反派以为系统帮他",
                "twist": "主角懂漏洞",
                "payoff_line_template": "原来如此。",
            }
        ],
    }
    r = _resolve_recipe(dna, "掌控感.系统机制反制")
    assert r is not None
    assert r["anchor"] == "掌控感"
    assert r["pattern"] == "系统机制反制"
    assert "反派以为系统帮他" in r["formula"]
    assert r["setup"] == "反派以为系统帮他"


def test_resolve_recipe_missing_returns_none():
    assert _resolve_recipe({}, "爽感") is None
    assert _resolve_recipe({"payoff_recipes": {}}, "不存在的anchor") is None


# ---------------- 4. Planner injects recipe block when ref present ----------------

def _seed_planner_bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "末世", "era": "X"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "陈牧"}})
    b.write_json(
        "outline.json",
        {"chapters": [{"ch": i, "title": f"第{i}章", "beats": []} for i in range(1, 11)]},
    )
    (tmp_path / "chapters").mkdir()
    (tmp_path / "summaries").mkdir()
    return b


def test_planner_injects_recipe_when_milestone_has_ref(tmp_path):
    bb = _seed_planner_bb(tmp_path)
    bb.write_yaml(
        "dna_structured.yaml",
        {
            "schema_version": 1,
            "payoff_recipes": {
                "掌控感": {
                    "formula": "反派狂言→主角设局→规则反制",
                    "dialog_template": [
                        {"speaker": "villain", "beats": ["展示"]},
                        {"speaker": "protagonist", "beats": ["短句反击"]},
                    ],
                    "sample_50_chars": "你以为你赢了？我从未输过。",
                }
            },
            "villain_defeat_patterns": [
                {
                    "pattern": "系统机制反制",
                    "setup": "反派以为系统帮他",
                    "twist": "主角懂漏洞",
                    "payoff_line_template": "原来如此。",
                }
            ],
        },
    )
    bb.write_yaml(
        "plot_arc.yaml",
        {
            "schema_version": 1,
            "total_chapters": 10,
            "ultimate_goal": "x",
            "acts": [
                {
                    "name": "A",
                    "range": [1, 10],
                    "must_close_by_end": [],
                    "milestones": [
                        {
                            "chapter": 3,
                            "type": "能力升级",
                            "anchor": "掌控感",
                            "beat": "X",
                            "payoff_recipe_ref": "掌控感.系统机制反制",
                        }
                    ],
                }
            ],
        },
    )

    _, user, _ = Planner()._build_prompts(bb, chapter=3)
    # The recipe block must appear, with the ref string and concrete fields
    assert "📖" in user
    assert "本章 milestone 对应的 dna 配方" in user
    assert "工艺链" in user
    assert "对话剧本" in user
    assert "系统机制反制" in user  # pattern name
    assert "反派以为系统帮他" in user  # setup
    # Anchor's sample_50_chars surfaces too (from villain pattern's anchor fallback)
    assert "你以为你赢了" in user


def test_planner_no_recipe_block_when_no_ref(tmp_path):
    """Milestone without payoff_recipe_ref → no 📖 recipe block."""
    bb = _seed_planner_bb(tmp_path)
    bb.write_yaml(
        "dna_structured.yaml",
        {
            "schema_version": 1,
            "payoff_recipes": {"掌控感": {"formula": "X", "dialog_template": [], "sample_50_chars": ""}},
        },
    )
    bb.write_yaml(
        "plot_arc.yaml",
        {
            "schema_version": 1,
            "total_chapters": 10,
            "ultimate_goal": "x",
            "acts": [
                {
                    "name": "A",
                    "range": [1, 10],
                    "must_close_by_end": [],
                    "milestones": [
                        {
                            "chapter": 3,
                            "type": "X",
                            "anchor": "掌控感",
                            "beat": "B",
                            # no payoff_recipe_ref
                        }
                    ],
                }
            ],
        },
    )
    _, user, _ = Planner()._build_prompts(bb, chapter=3)
    # Milestone block (🎯) still appears, but no recipe block (📖)
    assert "🎯" in user
    assert "本章 milestone 对应的 dna 配方" not in user

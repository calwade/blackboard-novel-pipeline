"""Tests for Generator consuming dna_structured.yaml.payoff_recipes (P3 in fix-3).

LLM-free.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents.generator import Generator


def _seed_generator_bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "末世", "era": "X", "tone": "冷峻"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "陈牧"}, "supporting": []})
    b.write_text("era.md", "# era\n")
    b.write_text("writing-style-extra.md", "# style\n")
    (tmp_path / "chapters").mkdir()
    (tmp_path / "summaries").mkdir()
    b.write_json(
        "chapters/ch005.plan.json",
        {
            "ch": 5,
            "title": "第五章",
            "chapter_type": "回收",
            "opening_hook": "x",
            "closing_hook": "y",
            "scenes": [
                {
                    "scene_id": 1,
                    "location": "便利店",
                    "cast": ["陈牧"],
                    "conflict": "X",
                    "purpose": "推进主线",
                    "sensory_prompts": ["A"],
                    "advances": ["信息"],
                    "word_target": 1500,
                }
            ],
            "landmines_to_avoid": [],
            "writing_self_check": {},
        },
    )
    return b


# ---------------- 1. Generator system prompt contains payoff_recipes formulas ----------------

def test_generator_reads_payoff_recipes(tmp_path):
    bb = _seed_generator_bb(tmp_path)
    bb.write_yaml(
        "dna_structured.yaml",
        {
            "schema_version": 1,
            "payoff_recipes": {
                "爽感": {
                    "formula": "冷场→主角秒杀→旁观者震惊",
                    "dialog_template": [{"speaker": "protagonist", "beats": ["出手"]}],
                    "sample_50_chars": "X",
                },
                "掌控感": {
                    "formula": "反派狂言→主角设局→规则反制",
                    "dialog_template": [],
                    "sample_50_chars": "",
                },
                "黑色幽默": {"formula": "", "dialog_template": [], "sample_50_chars": ""},
                "生存智慧": {"formula": "", "dialog_template": [], "sample_50_chars": ""},
            },
        },
    )

    sys_prompt, _, inputs = Generator()._build_prompts(bb, chapter=5)
    # The 📖 dna 爽点配方 block must be present
    assert "📖 dna 爽点配方" in sys_prompt
    # At least one anchor's formula text leaks through
    assert "冷场→主角秒杀→旁观者震惊" in sys_prompt
    assert "反派狂言→主角设局→规则反制" in sys_prompt
    # input file recorded
    assert "state/dna_structured.yaml" in inputs


def test_generator_milestone_recipe_emphasis(tmp_path):
    """When chapter is a milestone with payoff_recipe_ref, generator must
    surface a `⚠ 本章是 milestone` recipe-emphasis block."""
    bb = _seed_generator_bb(tmp_path)
    bb.write_yaml(
        "dna_structured.yaml",
        {
            "schema_version": 1,
            "payoff_recipes": {
                "掌控感": {
                    "formula": "通用工艺",
                    "dialog_template": [{"speaker": "protagonist", "beats": ["短句"]}],
                    "sample_50_chars": "通用样本",
                },
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
                            "chapter": 5,
                            "type": "能力升级",
                            "anchor": "掌控感",
                            "beat": "B",
                            "payoff_recipe_ref": "掌控感.系统机制反制",
                        }
                    ],
                }
            ],
        },
    )

    sys_prompt, _, inputs = Generator()._build_prompts(bb, chapter=5)
    assert "⚠ 本章是 milestone" in sys_prompt
    # The pattern's setup/twist must surface
    assert "系统机制反制" in sys_prompt
    assert "反派以为系统帮他" in sys_prompt
    # plot_arc.yaml is registered as input
    assert "state/plot_arc.yaml" in inputs


def test_generator_no_recipe_block_without_dna(tmp_path):
    """Backward compat: no dna_structured.yaml → no 📖 block."""
    bb = _seed_generator_bb(tmp_path)
    sys_prompt, _, inputs = Generator()._build_prompts(bb, chapter=5)
    assert "📖 dna 爽点配方" not in sys_prompt
    assert "state/dna_structured.yaml" not in inputs

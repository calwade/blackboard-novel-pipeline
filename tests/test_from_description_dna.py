"""Tests for from_description path producing dna_structured.yaml (P2 in fix-3).

LLM-free — uses _render_files_from_blueprint directly with synthetic blueprint.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.genre_extractor.from_description import (
    SYSTEM_PROMPT,
    _ensure_dna_structured_schema,
    _render_files_from_blueprint,
)


# ---------------- 1. SYSTEM_PROMPT demands dna_structured ----------------

def test_from_description_system_prompt_demands_dna_structured():
    assert "dna_structured" in SYSTEM_PROMPT
    # Must request all 4 new top-level fields too
    for kw in (
        "plot_unit_structure",
        "payoff_recipes",
        "villain_defeat_patterns",
        "volume_transition_techniques",
    ):
        assert kw in SYSTEM_PROMPT, f"{kw} missing in from_description SYSTEM_PROMPT"
    # 4 anchors must be enumerated
    for anchor in ("爽感", "掌控感", "黑色幽默", "生存智慧"):
        assert anchor in SYSTEM_PROMPT, f"anchor {anchor} not requested"


# ---------------- 2. _render_files_from_blueprint writes dna_structured.yaml ----------------

def test_from_description_renders_dna_yaml(tmp_path: Path):
    blueprint = {
        "era": {"content": "# Era\n\n世界设定。\n"},
        "writing_style_extra": {"content": "# Style\n\n冷峻。\n"},
        "iron_laws_extra": {"content": "# Iron Laws\n\n1. xxx\n"},
        "resource_schema": None,
        "dna_structured": {
            "schema_version": 1,
            "tips_by_chapter_type": {"战斗": ["快"], "布局": [], "过渡": [], "回收": []},
            "payoff_recipes": {
                "爽感": {
                    "formula": "冷场→秒杀→点评",
                    "dialog_template": [{"speaker": "protagonist", "beats": ["出手"]}],
                    "sample_50_chars": "X",
                },
            },
            "villain_defeat_patterns": [
                {"pattern": "信息差打脸", "setup": "X", "twist": "Y", "payoff_line_template": "Z"},
            ],
        },
    }
    written = _render_files_from_blueprint(blueprint, out_dir=tmp_path)
    dna_path = tmp_path / "dna_structured.yaml"
    assert dna_path in written
    assert dna_path.exists()

    text = dna_path.read_text(encoding="utf-8")
    # File header marker
    assert "AUTO-GENERATED from sparse description" in text
    # Schema must round-trip valid YAML and contain key buckets
    body = text.split("\n", 3)[3] if text.startswith("#") else text  # strip comment header
    parsed = yaml.safe_load(text)
    assert parsed["schema_version"] == 1
    assert "payoff_recipes" in parsed
    assert "villain_defeat_patterns" in parsed
    # Schema-fill ensured all 4 anchors appear (爽感 had data;掌控感等被补默认)
    for anchor in ("爽感", "掌控感", "黑色幽默", "生存智慧"):
        assert anchor in parsed["payoff_recipes"]


def test_from_description_skips_dna_yaml_when_blueprint_has_none(tmp_path: Path):
    """Backward-compat: blueprint without dna_structured must not write empty file."""
    blueprint = {
        "era": {"content": "# Era\n"},
        "writing_style_extra": {"content": "# Style\n"},
        "iron_laws_extra": {"content": "# Iron\n"},
        "resource_schema": None,
        "dna_structured": None,
    }
    written = _render_files_from_blueprint(blueprint, out_dir=tmp_path)
    dna_path = tmp_path / "dna_structured.yaml"
    assert dna_path not in written
    assert not dna_path.exists()


# ---------------- 3. Schema parity with NovelDNA Stage 2.5 ----------------

def test_from_description_dna_yaml_schema_matches_novel_dna():
    """Top-level keys produced by from_description's _ensure_dna_structured_schema
    must match the keys produced by NovelDNA Stage 2.5's _structure_dna_tips
    post-process."""
    out = _ensure_dna_structured_schema({})

    expected_top_level = {
        "schema_version",
        "tips_by_chapter_type",
        "tips_by_scene_purpose",
        "hook_recipes",
        "universal",
        "plot_unit_structure",
        "payoff_recipes",
        "villain_defeat_patterns",
        "volume_transition_techniques",
    }
    assert expected_top_level.issubset(set(out.keys()))

    # 4-bucket keys that downstream查表期望
    assert set(out["tips_by_chapter_type"].keys()) >= {"战斗", "布局", "过渡", "回收"}
    assert set(out["tips_by_scene_purpose"].keys()) >= {"推进主线", "塑造人物", "埋伏笔"}
    assert set(out["payoff_recipes"].keys()) >= {"爽感", "掌控感", "黑色幽默", "生存智慧"}

    # plot_unit_structure shape
    assert "unit_size" in out["plot_unit_structure"]
    assert "pattern" in out["plot_unit_structure"]
    assert "pacing" in out["plot_unit_structure"]

    # volume_transition_techniques shape
    vtt = out["volume_transition_techniques"]
    for k in ("scaling_method", "arc_closer_template", "next_arc_opener_template"):
        assert k in vtt

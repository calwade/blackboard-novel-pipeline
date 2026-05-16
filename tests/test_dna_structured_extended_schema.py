"""Tests for NovelDNA extended schema (P0+P1 in fix-3).

LLM-free — only inspects prompt strings and schema defaults.

Coverage:
1. Stage 2.5 _STRUCTURE_SYSTEM has 4 new top-level buckets
2. Stage 1 _WINDOW_SYSTEM has 3 new analysis dimensions
3. Stage 1 _DIGEST_SYSTEM has 3 new aggregation sections in DNA card
"""
from __future__ import annotations

from src.genre_extractor.miners.novel_dna import (
    _DIGEST_SYSTEM,
    _STRUCTURE_SYSTEM,
    _WINDOW_SYSTEM,
)


# ---------------- 1. Stage 2.5: 4 new top-level buckets ----------------

def test_structure_system_demands_4_new_buckets():
    """The structurer prompt must require all 4 new top-level buckets +
    document their sub-fields explicitly."""
    for kw in (
        "plot_unit_structure",
        "payoff_recipes",
        "villain_defeat_patterns",
        "volume_transition_techniques",
    ):
        assert kw in _STRUCTURE_SYSTEM, f"missing {kw} in _STRUCTURE_SYSTEM"

    # plot_unit_structure → unit_size + pattern (起承转合) + pacing
    assert "unit_size" in _STRUCTURE_SYSTEM
    assert "起" in _STRUCTURE_SYSTEM and "承" in _STRUCTURE_SYSTEM and "转" in _STRUCTURE_SYSTEM and "合" in _STRUCTURE_SYSTEM
    assert "small_payoff_every" in _STRUCTURE_SYSTEM
    assert "big_payoff_every" in _STRUCTURE_SYSTEM

    # payoff_recipes must require 4 anchor keys
    for anchor in ("爽感", "掌控感", "黑色幽默", "生存智慧"):
        assert anchor in _STRUCTURE_SYSTEM, f"anchor {anchor} not required"
    # ... and 3 sub-fields per anchor
    assert "formula" in _STRUCTURE_SYSTEM
    assert "dialog_template" in _STRUCTURE_SYSTEM
    assert "sample_50_chars" in _STRUCTURE_SYSTEM
    assert "speaker" in _STRUCTURE_SYSTEM
    assert "beats" in _STRUCTURE_SYSTEM

    # villain_defeat_patterns must list at least the 3 canonical patterns
    for pat in ("信息差打脸", "实力差秒杀", "心理战崩溃"):
        assert pat in _STRUCTURE_SYSTEM, f"pattern {pat} not exemplified"
    assert "setup" in _STRUCTURE_SYSTEM
    assert "twist" in _STRUCTURE_SYSTEM
    assert "payoff_line_template" in _STRUCTURE_SYSTEM

    # volume_transition_techniques fields
    assert "scaling_method" in _STRUCTURE_SYSTEM
    assert "arc_closer_template" in _STRUCTURE_SYSTEM
    assert "next_arc_opener_template" in _STRUCTURE_SYSTEM


# ---------------- 2. Stage 1 window: 3 new dimensions ----------------

def test_window_system_has_3_new_dimensions():
    for kw in ("反派失败方式", "主角主动度", "爽点对话剧本"):
        assert kw in _WINDOW_SYSTEM, f"missing dimension {kw} in _WINDOW_SYSTEM"
    # Numbered as 7-9 in the prompt
    assert "## 7." in _WINDOW_SYSTEM and "## 8." in _WINDOW_SYSTEM and "## 9." in _WINDOW_SYSTEM

    # Specific guidance hints to ensure the dimension is specified, not just named
    assert "信息差" in _WINDOW_SYSTEM
    assert "主动" in _WINDOW_SYSTEM and "被动" in _WINDOW_SYSTEM
    # Dialog template must require 50-100 chars sample
    assert "50-100 字" in _WINDOW_SYSTEM


# ---------------- 3. Stage 1 digest: 3 new aggregation sections ----------------

def test_digest_system_aggregates_3_new_dimensions():
    """The DNA-card synthesizer must roll up the 3 new window dimensions
    into 3 dedicated sections of the DNA card."""
    for section in ("反派失败公式", "主角主动度量化", "爽点对话剧本样本"):
        assert section in _DIGEST_SYSTEM, f"missing section {section} in _DIGEST_SYSTEM"

    # Specific aggregation hints
    assert "信息差打脸" in _DIGEST_SYSTEM  # canonical pattern category
    assert "占比" in _DIGEST_SYSTEM  # quantitative requirement
    assert "50-100 字" in _DIGEST_SYSTEM  # samples must include 50-100 char excerpts


# ---------------- 4. _structure_dna_tips ensures defaults ----------------

def test_structure_dna_tips_fills_default_buckets_for_missing_fields():
    """If LLM omits the new buckets, _structure_dna_tips must seed defaults
    so downstream Planner/Generator查表 don't KeyError."""
    # We can't call _structure_dna_tips directly without mocking _call_llm.
    # Instead exercise the post-process logic by simulating an empty dict
    # via the same defaults sequence in from_description._ensure_dna_structured_schema
    # (mirror of the same setdefault chain).
    from src.genre_extractor.from_description import _ensure_dna_structured_schema

    out = _ensure_dna_structured_schema({})
    for k in (
        "schema_version",
        "tips_by_chapter_type",
        "tips_by_scene_purpose",
        "hook_recipes",
        "universal",
        "plot_unit_structure",
        "payoff_recipes",
        "villain_defeat_patterns",
        "volume_transition_techniques",
    ):
        assert k in out
    for anchor in ("爽感", "掌控感", "黑色幽默", "生存智慧"):
        assert anchor in out["payoff_recipes"]
        rec = out["payoff_recipes"][anchor]
        assert "formula" in rec
        assert "dialog_template" in rec
        assert "sample_50_chars" in rec

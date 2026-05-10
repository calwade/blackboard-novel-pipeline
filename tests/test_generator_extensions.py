"""Tests for Generator new behavior:
- prohibited_styles from setting.yaml injected into system prompt (C-32)
- chapter_type block swapped based on plan.chapter_type (C-29)
- writing_self_check table rendered from plan.writing_self_check (A-5)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents.generator import (
    Generator,
    _chapter_type_emphasis,
    _format_self_check,
)


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml(
        "setting.yaml",
        {
            "genre": "都市言情",
            "era": "2024",
            "tone": "克制",
            "author_persona_hints": ["成年人的选择"],
            "prohibited_styles": ["霸总腔", "玄幻修仙腔", "影视剧本腔"],
        },
    )
    b.write_yaml(
        "characters.yaml",
        {"protagonist": {"name": "沈若微"}, "supporting": []},
    )
    b.write_text("era.md", "2024 China era facts.")
    b.write_text("writing-style-extra.md", "urban-romance style extras.")
    (tmp_path / "chapters").mkdir(exist_ok=True)
    return b


# -------- chapter_type emphasis (pure helper) --------

@pytest.mark.parametrize(
    "ctype,marker",
    [
        ("战斗", "战斗章"),
        ("布局", "布局章"),
        ("过渡", "过渡章"),
        ("回收", "回收章"),
    ],
)
def test_chapter_type_emphasis_matches(ctype, marker):
    out = _chapter_type_emphasis(ctype)
    assert marker in out


def test_chapter_type_emphasis_unknown_returns_default():
    out = _chapter_type_emphasis("不存在的类型")
    assert "Planner 未指定章节类型" in out or "默认节奏" in out


def test_chapter_type_emphasis_empty_returns_default():
    out = _chapter_type_emphasis("")
    assert "Planner 未指定章节类型" in out or "默认节奏" in out


# -------- writing_self_check table formatting --------

def test_format_self_check_empty_returns_placeholder():
    text = _format_self_check({})
    assert "Planner 未提供 writing_self_check" in text or "通用铁律自律" in text


def test_format_self_check_renders_table_with_all_rows():
    sc = {
        "ooc_risk": "沈若微不得会议撒娇",
        "info_leak_risk": "无",
        "setting_conflict_risk": "",  # empty string → fallback text
        "power_scaling_risk": "无",
        "pacing_risk": "避免第一幕超 800 字",
        "vocab_fatigue_risk": "禁止『心跳漏了一拍』",
    }
    text = _format_self_check(sc)
    assert "| 检查项 | Planner 提示 |" in text
    assert "人物 OOC 风险" in text
    assert "沈若微不得会议撒娇" in text
    assert "禁止『心跳漏了一拍』" in text
    # empty string is shown as "未填写" fallback
    assert "（未填写，按通用铁律自律）" in text


# -------- Generator full prompt integration --------

def test_generator_system_has_prohibited_styles_block(bb):
    bb.write_json(
        "chapters/ch001.plan.json",
        {
            "ch": 1,
            "title": "t",
            "scenes": [{"scene_id": 1, "cast": ["沈若微"]}],
            "chapter_type": "布局",
        },
    )
    system, _, _ = Generator()._build_prompts(bb, chapter=1)
    assert "风格锁定" in system
    assert "霸总腔" in system
    assert "玄幻修仙腔" in system
    assert "影视剧本腔" in system


def test_generator_system_has_chapter_type_block(bb):
    bb.write_json(
        "chapters/ch001.plan.json",
        {
            "ch": 1,
            "title": "t",
            "scenes": [{"scene_id": 1, "cast": ["沈若微"]}],
            "chapter_type": "战斗",
        },
    )
    system, _, _ = Generator()._build_prompts(bb, chapter=1)
    assert "本章类型" in system
    assert "战斗章" in system


def test_generator_missing_chapter_type_falls_back(bb):
    bb.write_json(
        "chapters/ch001.plan.json",
        {"ch": 1, "title": "t", "scenes": [{"scene_id": 1, "cast": ["沈若微"]}]},
    )
    system, _, _ = Generator()._build_prompts(bb, chapter=1)
    assert "本章类型" in system
    # "未指定" appears in the heading AND the default body
    assert "未指定" in system


def test_generator_renders_writing_self_check(bb):
    bb.write_json(
        "chapters/ch001.plan.json",
        {
            "ch": 1,
            "title": "t",
            "scenes": [{"scene_id": 1, "cast": ["沈若微"]}],
            "chapter_type": "过渡",
            "writing_self_check": {
                "ooc_risk": "禁止撒娇",
                "pacing_risk": "无",
                "vocab_fatigue_risk": "禁止『心跳漏了一拍』",
            },
        },
    )
    system, _, _ = Generator()._build_prompts(bb, chapter=1)
    assert "写作自检" in system
    assert "禁止撒娇" in system
    assert "禁止『心跳漏了一拍』" in system


def test_generator_handles_missing_prohibited_styles(bb, tmp_path):
    # Remove prohibited_styles to ensure graceful fallback
    setting = bb.read_yaml("setting.yaml")
    setting.pop("prohibited_styles", None)
    bb.write_yaml("setting.yaml", setting)

    bb.write_json(
        "chapters/ch001.plan.json",
        {"ch": 1, "title": "t", "scenes": [{"scene_id": 1, "cast": ["沈若微"]}]},
    )
    system, _, _ = Generator()._build_prompts(bb, chapter=1)
    assert "风格锁定" in system
    assert "本 setting 未声明风格禁止清单" in system

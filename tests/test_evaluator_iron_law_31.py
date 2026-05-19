"""Tests for iron_law_31 题材一致性律 (genre consistency).

Why: ora-1 environment-5 fix. LLM training intuition makes it easy for a
modern post-apocalypse outline to drift into Ming-dynasty / xianxia voice
("无名" / "嘉靖二年" / "棺材钉" instead of era.md's "苏烬" / "末世第三年" /
"灰烬契书"). Evaluator's rubric pre-iron_law_31 had zero genre-anchor
checks (all 30 prior laws are narrative/structure-level), so a totally-
genre-drifted ch1 sailed through Evaluator without complaint.

These tests lock in:
 1. _extract_era_keywords pulls protagonist / era anchors / core objects /
    landmarks from a representative era.md.
 2. _check_genre_consistency emits high-severity hits when the chapter
    fails to mention any of the three primary axes.
 3. _check_genre_consistency stays silent (hit=False) when chapter aligns.
 4. Evaluator's _handle_output short-circuits on genre drift WITHOUT
    needing the LLM to cooperate (mocked LLM returns all-clean verdict).
 5. iron_law_31 is documented in rules/iron-laws.md AND header is bumped
    to "31 条铁律".
 6. Evaluator's inputs_read includes state/era.md when present.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents._verdict_schema import LANDMINE_IDS
from src.agents.evaluator import (
    Evaluator,
    _check_genre_consistency,
    _extract_era_keywords,
)


# ---------- mock era.md ----------


_MOCK_ERA = """# 灰烬契书 · 世界观设定

## 反常规则：灰烬契书

末世第三年，一种名为"灰烬"的物质从地裂中涌出，覆盖全球。主角苏烬，
正是掮客中最狠的一种：他专替人写"安全契书"。**灰烬契书**是核心道具。

## 时代锚点：G22 服务区遗址

故事主舞台位于 G22 高速服务区遗址。
**灰烬炉**位于交易大厅。

## 主要场景：码头 / 茶餐厅
"""


# ---------- chapter fixtures ----------


def _drifted_chapter() -> str:
    """A chapter that completely drifts into Ming-dynasty voice — no
    protagonist name, no era anchor, no core object."""
    return (
        "# 第一章\n\n"
        "嘉靖二年的秋日，无名走过鸡鸣驿外的官道。\n\n"
        "他从怀里掏出一只算盘，敲了三下，又取出一根棺材钉。\n\n"
        "城隍庙的香烟正盛，蓟镇总兵府的捕快从街角拐过。\n\n"
        "一个老和尚坐在桥头，对他说：『施主，戒嗔。』\n\n"
        "无名笑了笑，没回答，转身走入城外的官道。\n\n"
        "夜深，月凉，他摸出那张古旧的票引，眯着眼读了一遍。"
    )


def _aligned_chapter() -> str:
    """A chapter that hits all three axes: protagonist + era + ≥1 core object."""
    return (
        "# 第一章\n\n"
        "末世第三年，苏烬走进 G22 服务区遗址，怀里揣着昨夜代写的灰烬契书。\n\n"
        "灰烬炉正在缓缓吞噬上一份契书。他坐到隔间办公室，开始草拟下一份。\n\n"
        "苏烬的指节叩了叩桌面，目光落在窗外的野坟堆上，开始默写灰烬语法。"
    )


# ---------- 1. helper: extract_era_keywords ----------


def test_extract_era_keywords_simple():
    """era.md 给出明确的主角/时代/道具/地标，4 个轴都应抽到。"""
    kws = _extract_era_keywords(_MOCK_ERA)
    assert kws["protagonist"] == "苏烬", (
        f"expected protagonist=苏烬, got {kws['protagonist']!r}"
    )
    assert "末世第三年" in kws["era_anchors"], (
        f"era anchors missed '末世第三年': {kws['era_anchors']}"
    )
    # core_objects via **X** bold markers (limited to short Chinese tokens)
    assert "灰烬契书" in kws["core_objects"], (
        f"core_objects missed '灰烬契书': {kws['core_objects']}"
    )
    assert "灰烬炉" in kws["core_objects"]
    # Landmarks from "## ..." titles
    assert any("码头" in lm or "茶餐厅" in lm for lm in kws["landmarks"]), (
        f"landmarks missing 码头/茶餐厅: {kws['landmarks']}"
    )


def test_extract_era_keywords_empty_text_returns_empty():
    """era.md missing or blank → returns empty fields (no crash)."""
    kws = _extract_era_keywords("")
    assert kws["protagonist"] == ""
    assert kws["era_anchors"] == []
    assert kws["core_objects"] == []
    assert kws["landmarks"] == []


# ---------- 2. helper: check_genre_consistency ----------


def test_check_genre_consistency_high_severity_when_protagonist_missing():
    """Protagonist name missing from chapter → severity=high (致命)."""
    kws = {
        "protagonist": "苏烬",
        "era_anchors": ["末世第三年"],
        "core_objects": ["灰烬契书"],
        "landmarks": [],
    }
    chapter = "嘉靖二年，无名走过鸡鸣驿。"  # 完全跑偏
    res = _check_genre_consistency(chapter, kws)
    assert res["hit"] is True
    assert res["severity"] == "high"
    assert "苏烬" in res["evidence"]


def test_check_genre_consistency_pass_when_all_match():
    """Chapter hits protagonist + era + ≥50% core objects → no hit."""
    kws = {
        "protagonist": "苏烬",
        "era_anchors": ["末世第三年"],
        "core_objects": ["灰烬契书", "灰烬炉"],
        "landmarks": ["G22"],
    }
    chapter = (
        "末世第三年，苏烬把灰烬契书塞进灰烬炉。"
        "G22 服务区里灯光昏暗，他低头数了数残余的契书。"
    )
    res = _check_genre_consistency(chapter, kws)
    assert res["hit"] is False
    assert res["severity"] is None
    assert res["evidence"] is None


def test_check_genre_consistency_medium_when_only_landmarks_miss():
    """Only landmarks missed (protagonist/era/objects all present) → medium."""
    kws = {
        "protagonist": "苏烬",
        "era_anchors": ["末世第三年"],
        "core_objects": ["灰烬契书"],
        "landmarks": ["G22"],
    }
    # Hits protagonist+era+object but NOT G22
    chapter = "末世第三年的某个夜晚，苏烬展开手中的灰烬契书，目光冷峻。"
    res = _check_genre_consistency(chapter, kws)
    assert res["hit"] is True
    assert res["severity"] == "medium"
    assert "G22" in res["evidence"]


# ---------- 3. evaluator integration: short-circuit on genre drift ----------


def _seed_evaluator_state(tmp_path: Path) -> Blackboard:
    """Mirror the minimum bb fixture used by other evaluator tests."""
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "末世废土", "era": "灰烬纪年"})
    b.write_yaml(
        "characters.yaml",
        {"protagonist": {"name": "苏烬"}, "supporting": []},
    )
    b.write_text("timeline.yaml", "末世第三年: []\n")
    b.write_text("iron-laws-extra.md", "## iron_law_extra_1 placeholder\n")
    b.write_text("era.md", _MOCK_ERA)
    (tmp_path / "chapters").mkdir(exist_ok=True)
    return b


def _all_false_landmines() -> dict:
    return {
        mid: {"hit": False, "evidence": None, "severity": None}
        for mid in LANDMINE_IDS
    }


def _llm_clean_response() -> str:
    return json.dumps(
        {
            "overall_pass": True,
            "landmines": _all_false_landmines(),
            "top_3_fixes": [],
        },
        ensure_ascii=False,
    )


def _patch_llm(monkeypatch, response: str) -> list:
    captured: list = []

    def fake_chat(*, system, user, agent_name, **_):
        captured.append((system, user))
        return response

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    return captured


def test_evaluator_short_circuits_on_genre_drift(tmp_path, monkeypatch):
    """Even when LLM lies and returns all-clean, mechanical iron_law_31 scan
    must catch a fully-drifted chapter and force overall_pass=False."""
    b = _seed_evaluator_state(tmp_path)
    b.write_text("chapters/ch001.md", _drifted_chapter())
    _patch_llm(monkeypatch, _llm_clean_response())

    Evaluator().run(b, chapter=1)

    verdict = b.read_json("chapters/ch001.verdict.json")
    # iron_law_violations must contain iron_law_31
    violations = verdict.get("iron_law_violations") or []
    assert any(v.get("iron_law") == "iron_law_31" for v in violations), (
        f"iron_law_31 not in violations: {violations}"
    )
    iron31 = next(v for v in violations if v["iron_law"] == "iron_law_31")
    assert iron31["severity"] == "high", iron31
    assert iron31["_source"] == "mechanical_scan", iron31
    # high severity → overall_pass forced to False
    assert verdict["overall_pass"] is False, (
        "iron_law_31 high severity must force overall_pass=False"
    )


def test_evaluator_does_not_short_circuit_on_aligned_chapter(tmp_path, monkeypatch):
    """When chapter aligns with era.md, iron_law_31 must NOT fire."""
    b = _seed_evaluator_state(tmp_path)
    b.write_text("chapters/ch001.md", _aligned_chapter())
    _patch_llm(monkeypatch, _llm_clean_response())

    Evaluator().run(b, chapter=1)

    verdict = b.read_json("chapters/ch001.verdict.json")
    violations = verdict.get("iron_law_violations") or []
    iron31_hits = [v for v in violations if v.get("iron_law") == "iron_law_31"]
    assert iron31_hits == [], (
        f"iron_law_31 should not fire on aligned chapter, got {iron31_hits}"
    )


# ---------- 4. inputs_read includes era.md ----------


def test_evaluator_inputs_read_includes_era_md(tmp_path):
    """When era.md exists in bb, _build_prompts must list it under
    inputs_read so the Inspector reflects what the Evaluator actually read."""
    b = _seed_evaluator_state(tmp_path)
    b.write_text("chapters/ch001.md", _aligned_chapter())

    ev = Evaluator()
    _system, _user, inputs_read = ev._build_prompts(b, chapter=1)
    assert "state/era.md" in inputs_read, (
        f"state/era.md missing from inputs_read: {inputs_read}"
    )


# ---------- 5. iron_law_31 documented in rules/iron-laws.md ----------


def test_iron_law_31_in_iron_laws_md():
    """Both rules/iron-laws.md and docs/rules/iron-laws.md must document
    iron_law_31 + bump the header to '31 条铁律'."""
    repo = Path(__file__).resolve().parent.parent
    for rel in ("rules/iron-laws.md", "docs/rules/iron-laws.md"):
        text = (repo / rel).read_text(encoding="utf-8")
        assert "iron_law_31" in text, f"{rel} missing iron_law_31 anchor"
        assert "题材一致性" in text, f"{rel} missing '题材一致性' label"
        assert "31 条铁律" in text, (
            f"{rel} header not bumped to '31 条铁律' "
            "(check the metadata block at top of file)"
        )

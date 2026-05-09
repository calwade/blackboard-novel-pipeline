"""Tests for _verdict_schema: schema validation + skeleton detector.

Covers:
- Genuine clean pass (no hits, no fixes) is NOT flagged as skeleton
- Genuine problem verdict (real evidence + real fixes) is NOT flagged
- Skeleton via placeholder top_3_fixes IS detected
- Skeleton via too-short top_3_fixes IS detected
- Skeleton via placeholder evidence on all hits IS detected
- Missing landmine keys are defaulted safely
- Invalid severity values are coerced with warning
- Non-dict input is turned into failing synthetic verdict
- overall_pass is recomputed regardless of what the LLM said
"""
from __future__ import annotations

import pytest

from src.agents._verdict_schema import (
    LANDMINE_IDS,
    MIN_EVIDENCE_LEN,
    MIN_WHAT_LEN,
    MIN_WHERE_LEN,
    validate_verdict,
)


def _all_clean_mines():
    """All 18 landmines, none hit. Represents a truly clean chapter."""
    return {
        mid: {"hit": False, "evidence": None, "severity": None}
        for mid in LANDMINE_IDS
    }


def _one_real_hit():
    """One landmine with realistic evidence + severity."""
    mines = _all_clean_mines()
    mines["landmine_10"] = {
        "hit": True,
        "evidence": "林家耀突然主动分食，与 characters.yaml 中的『极致利己』trait 不符。",
        "severity": "high",
    }
    return mines


# -------- genuine pass / fail cases --------

def test_genuine_clean_pass_not_skeleton():
    """0 hits + 0 fixes should pass cleanly and NOT trigger skeleton detector."""
    result = validate_verdict(
        {
            "overall_pass": True,
            "landmines": _all_clean_mines(),
            "top_3_fixes": [],
        }
    )
    assert result["skeleton_detected"] is False
    assert result["clean_verdict"]["overall_pass"] is True
    assert result["clean_verdict"]["_severity_counts"] == {"high": 0, "medium": 0}


def test_genuine_problem_with_real_evidence_not_skeleton():
    """Real hit + real top_3_fixes should NOT be flagged as skeleton."""
    result = validate_verdict(
        {
            "overall_pass": False,
            "landmines": _one_real_hit(),
            "top_3_fixes": [
                {
                    "where": "第三段『林家耀把自己碗里的云吞夹了两只放进阿威碗里』",
                    "what": "删除分食动作或补一句内心独白说明这是算计而非同情。",
                }
            ],
        }
    )
    assert result["skeleton_detected"] is False
    assert result["clean_verdict"]["overall_pass"] is False
    assert result["clean_verdict"]["_severity_counts"]["high"] == 1


def test_overall_pass_is_recomputed_not_trusted():
    """LLM claims pass=True but has a high hit; we MUST override to False."""
    mines = _one_real_hit()
    result = validate_verdict(
        {
            "overall_pass": True,  # LLM lying or confused
            "landmines": mines,
            "top_3_fixes": [
                {"where": "真实引文超过6字", "what": "具体改写方向超过10字的文本"}
            ],
        }
    )
    assert result["skeleton_detected"] is False
    # Server-side recomputation: any high → fail
    assert result["clean_verdict"]["overall_pass"] is False


def test_two_medium_hits_fails_even_if_no_high():
    mines = _all_clean_mines()
    mines["landmine_5"] = {"hit": True, "evidence": "节奏混乱的证据片段在此。", "severity": "medium"}
    mines["landmine_8"] = {"hit": True, "evidence": "爽点缺失的证据片段在此。", "severity": "medium"}
    result = validate_verdict({"landmines": mines, "top_3_fixes": [
        {"where": "真实引文超过6字的", "what": "具体改写方向的文本超过十字"}
    ]})
    assert result["skeleton_detected"] is False
    assert result["clean_verdict"]["overall_pass"] is False


# -------- skeleton detection: placeholder top_3_fixes --------

@pytest.mark.parametrize(
    "where,what",
    [
        ("…", "…"),
        ("...", "..."),
        ("", ""),
        ("<string>", "<str>"),
        ("。。。", "。。。"),
    ],
)
def test_skeleton_via_placeholder_markers(where, what):
    """All top_3_fixes have placeholder where/what → skeleton."""
    result = validate_verdict(
        {
            "landmines": _all_clean_mines(),
            "top_3_fixes": [{"where": where, "what": what}] * 3,
        }
    )
    assert result["skeleton_detected"] is True
    assert result["clean_verdict"]["overall_pass"] is False
    assert result["clean_verdict"]["_skeleton_detected"] is True


def test_skeleton_via_too_short_where():
    """where < 6 chars triggers skeleton detection."""
    result = validate_verdict(
        {
            "landmines": _all_clean_mines(),
            "top_3_fixes": [
                {"where": "短", "what": "这是一个足够长的改写方向，超过十字。"}
            ],
        }
    )
    assert result["skeleton_detected"] is True


def test_skeleton_via_too_short_what():
    """what < 10 chars triggers skeleton detection."""
    result = validate_verdict(
        {
            "landmines": _all_clean_mines(),
            "top_3_fixes": [
                {"where": "一段长到足够引用的原文", "what": "太短。"}
            ],
        }
    )
    assert result["skeleton_detected"] is True


def test_one_real_fix_among_placeholders_saves_verdict():
    """If AT LEAST ONE fix is real, it's not a skeleton (LLM did some work)."""
    result = validate_verdict(
        {
            "landmines": _all_clean_mines(),
            "top_3_fixes": [
                {"where": "…", "what": "…"},  # placeholder
                {
                    "where": "真实的原文引文超过六个字的",
                    "what": "真实的改写方向超过十个字的文本在此。",
                },  # real
            ],
        }
    )
    assert result["skeleton_detected"] is False


# -------- skeleton detection: placeholder evidence --------

def test_skeleton_via_all_hits_having_placeholder_evidence():
    """Hits exist but all evidences are '...' → LLM echoed schema, not chapter."""
    mines = _all_clean_mines()
    mines["landmine_3"] = {"hit": True, "evidence": "...", "severity": "high"}
    mines["landmine_7"] = {"hit": True, "evidence": "…", "severity": "medium"}
    result = validate_verdict(
        {
            "landmines": mines,
            # Has real fixes so vector 1 doesn't fire...
            "top_3_fixes": [
                {
                    "where": "实际引文在此超过六字的原文",
                    "what": "实际改写方向在此超过十字。",
                }
            ],
        }
    )
    # ...but vector 2 (evidence) fires
    assert result["skeleton_detected"] is True


def test_mixed_evidence_real_and_placeholder_not_skeleton():
    """Some placeholder evidence mixed with real → not skeleton (benefit of doubt)."""
    mines = _all_clean_mines()
    mines["landmine_3"] = {"hit": True, "evidence": "...", "severity": "medium"}  # fake
    mines["landmine_7"] = {
        "hit": True,
        "evidence": "第三段『他脸色一沉』属于 tell-not-show。",
        "severity": "medium",
    }
    result = validate_verdict(
        {
            "landmines": mines,
            "top_3_fixes": [
                {
                    "where": "实际引文在此超过六字的原文",
                    "what": "实际改写方向在此超过十字的文本。",
                }
            ],
        }
    )
    assert result["skeleton_detected"] is False


# -------- missing fields --------

def test_missing_landmines_defaulted():
    """landmines dict missing half the keys → defaulted safely, warning emitted."""
    partial = {
        "landmine_1": {"hit": False, "evidence": None, "severity": None},
        "landmine_2": {"hit": False, "evidence": None, "severity": None},
    }
    result = validate_verdict(
        {"landmines": partial, "top_3_fixes": []}
    )
    assert result["skeleton_detected"] is False
    cv = result["clean_verdict"]
    for mid in LANDMINE_IDS:
        assert mid in cv["landmines"]
    assert any("missing" in w for w in result["validation_warnings"])


def test_missing_landmines_field_entirely():
    result = validate_verdict({"top_3_fixes": []})
    # All 18 defaulted to not hit → clean pass
    assert result["skeleton_detected"] is False
    assert result["clean_verdict"]["overall_pass"] is True


# -------- invalid types / enums --------

def test_invalid_severity_coerced():
    mines = _all_clean_mines()
    mines["landmine_3"] = {"hit": True, "evidence": "一段真实的原文证据引用", "severity": "critical"}
    result = validate_verdict(
        {
            "landmines": mines,
            "top_3_fixes": [
                {
                    "where": "真实的原文引文超过六字",
                    "what": "真实的改写方向超过十字的文本。",
                }
            ],
        }
    )
    # Invalid severity → coerced to "medium" + warning
    assert result["clean_verdict"]["landmines"]["landmine_3"]["severity"] == "medium"
    assert any("severity" in w for w in result["validation_warnings"])


def test_hit_is_truthy_coerced_to_bool():
    mines = _all_clean_mines()
    mines["landmine_3"] = {
        "hit": "yes",
        "evidence": "这是一段足够长的原文引用可以避免 skeleton 触发",
        "severity": "low",
    }
    result = validate_verdict({"landmines": mines, "top_3_fixes": []})
    assert result["skeleton_detected"] is False
    assert result["clean_verdict"]["landmines"]["landmine_3"]["hit"] is True


def test_non_dict_input_synthesizes_fail():
    """LLM returned a string, number, list — should fail safely."""
    for bad in ["just a string", 42, [1, 2, 3], None]:
        result = validate_verdict(bad)
        assert result["skeleton_detected"] is True
        assert result["clean_verdict"]["overall_pass"] is False
        assert "landmine_1" in result["clean_verdict"]["landmines"]


def test_evidence_wrong_type_nulled():
    mines = _all_clean_mines()
    mines["landmine_3"] = {"hit": True, "evidence": 12345, "severity": "low"}
    result = validate_verdict({"landmines": mines, "top_3_fixes": []})
    assert result["clean_verdict"]["landmines"]["landmine_3"]["evidence"] is None
    assert any("evidence" in w.lower() for w in result["validation_warnings"])


def test_top_3_fixes_wrong_type():
    """top_3_fixes is a string instead of list → treated as empty + warning."""
    result = validate_verdict(
        {
            "landmines": _all_clean_mines(),
            "top_3_fixes": "not a list",
        }
    )
    assert result["clean_verdict"]["top_3_fixes"] == []
    assert any("top_3_fixes" in w for w in result["validation_warnings"])


# -------- invariants --------

def test_clean_verdict_always_has_all_18_landmines():
    """No matter what garbage input, clean_verdict has all 18 landmine keys."""
    for bad_input in [
        {},
        {"landmines": {}},
        {"landmines": {"landmine_1": {"hit": True, "evidence": "ok一段长文本", "severity": "high"}}},
        "garbage",
        None,
    ]:
        result = validate_verdict(bad_input)
        mines = result["clean_verdict"].get("landmines", {})
        assert set(mines.keys()) == set(LANDMINE_IDS)


def test_min_length_constants_are_what_prompt_promises():
    """Sanity: the constants match the values in evaluator.py user prompt."""
    assert MIN_WHERE_LEN == 6
    assert MIN_WHAT_LEN == 10
    assert MIN_EVIDENCE_LEN == 6

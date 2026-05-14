"""Static AI-rhythm scanner tests (zero LLM calls).

Covers the 2026-05 灯下黑 tightening: Generator / Evaluator / AISlopGuard
all share the same LLM training bias and miss 4 deterministic rhythm
patterns (否定对比 / 破折号 / 短段 / 明喻). `static_scan_ai_rhythm` is the
non-LLM backstop; these tests lock in its thresholds and regex semantics.

**重要**：本文件所有测试都是纯 Python regex/string 断言，不触发任何 LLM
调用，不需要 DEEPSEEK_API_KEY。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import config
from src.auditors.ai_slop_guard import (
    SLOP_THRESHOLDS,
    static_scan_ai_rhythm,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _hit(scan: dict, criterion: str) -> dict | None:
    for h in scan["hits"]:
        if h["criterion"] == criterion:
            return h
    return None


def test_scan_detects_neg_contrast_severe():
    """10 个 '不是X，是Y' 句式 -> severe."""
    sentence = "不是偶然，是必然。"
    text = "\n\n".join(sentence for _ in range(10))
    scan = static_scan_ai_rhythm(text)
    h = _hit(scan, "rhythm_neg_contrast")
    assert h is not None, f"expected rhythm_neg_contrast hit, got {scan['hits']}"
    assert h["severity"] == "severe"
    assert h["count"] == 10
    assert scan["metrics"]["neg_contrast"] == 10


def test_scan_detects_emdash_moderate_vs_severe():
    """22 破折号 -> moderate；35 破折号 -> severe."""
    base_para = "描写段落内容，很普通。"

    # 22 emdashes: moderate
    text_mod = base_para + ("走到窗前——推开窗。" * 22)
    scan = static_scan_ai_rhythm(text_mod)
    h = _hit(scan, "rhythm_emdash")
    assert h is not None
    assert h["severity"] == "moderate"
    assert h["count"] == 22

    # 35 emdashes: severe
    text_sev = base_para + ("走到窗前——推开窗。" * 35)
    scan2 = static_scan_ai_rhythm(text_sev)
    h2 = _hit(scan2, "rhythm_emdash")
    assert h2 is not None
    assert h2["severity"] == "severe"
    assert h2["count"] == 35


def test_scan_short_para_ratio():
    """12/20 短段 -> 60% -> severe；5/20 短段 -> 25% -> 不命中."""
    # severe: 12 short + 8 long
    short = "他转头。"          # 4 字，算短段
    long_para = "他走到窗前，看着外面的街道，人声鼎沸，一辆双层巴士缓缓驶过，车身的广告招贴在夕阳下泛着微光，他站了很久，才缓慢地叹了一口气。"
    assert len(short) < 30
    assert len(long_para) >= 30
    text_sev = "\n\n".join([short] * 12 + [long_para] * 8)
    scan = static_scan_ai_rhythm(text_sev)
    h = _hit(scan, "rhythm_short_para")
    assert h is not None
    assert h["severity"] == "severe"
    assert scan["metrics"]["short_para_ratio"] == 0.6
    assert scan["metrics"]["total_paras"] == 20

    # not triggered: 5/20 = 25%
    text_ok = "\n\n".join([short] * 5 + [long_para] * 15)
    scan2 = static_scan_ai_rhythm(text_ok)
    assert _hit(scan2, "rhythm_short_para") is None
    assert scan2["metrics"]["short_para_ratio"] == 0.25


def test_scan_simile_moderate():
    """26 个 '像X' -> moderate（25 <= 26 < 40 severe）."""
    # Use varied sentences so regex matches independently, separated by 。
    sentence = "他的眼睛像刀子一样锋利。"
    text = sentence * 26
    scan = static_scan_ai_rhythm(text)
    h = _hit(scan, "rhythm_simile")
    assert h is not None, f"expected rhythm_simile hit; hits={scan['hits']} metrics={scan['metrics']}"
    assert h["severity"] == "moderate"
    assert h["count"] == 26


def test_scan_ignores_dialogue_emdash():
    """对话里的 '——' 不计数，描写里的计数."""
    # 20 dialogue emdashes (should be stripped) + 5 narration emdashes
    dialogue_line = '他说："你——"\n\n'
    narration_line = "他转身——走向门口。\n\n"
    text = dialogue_line * 20 + narration_line * 5
    scan = static_scan_ai_rhythm(text)
    # emdash count should be 5, not 25
    assert scan["metrics"]["emdash"] == 5, (
        f"expected 5 narration emdashes (dialogue stripped), got {scan['metrics']['emdash']}"
    )
    # 5 < 20 moderate threshold -> no hit
    assert _hit(scan, "rhythm_emdash") is None


def test_scan_ch026_regression():
    """ch026 真章节回归锁定：≥3 个 severe hit（Oracle 报告过 neg/emdash/short_para 都 severe）.

    如果 ch026 不存在（例如在 CI 里没这本书），直接 skip；pytest 不会 fail。
    """
    ch026 = (
        REPO_ROOT / "projects" / "book-e3f4fc9b" / "state" / "chapters" / "ch026.md"
    )
    if not ch026.exists():
        pytest.skip(f"{ch026} not present; skipping regression lock")
    text = ch026.read_text(encoding="utf-8")
    scan = static_scan_ai_rhythm(text)
    severe_hits = [h for h in scan["hits"] if h["severity"] == "severe"]
    assert len(severe_hits) >= 3, (
        f"ch026 regression: expected >=3 severe hits, got {len(severe_hits)}. "
        f"hits={scan['hits']} metrics={scan['metrics']}"
    )


def test_thresholds_documented():
    """landmines.md 必须列出 4 个子雷 (18a-18d)."""
    text = (config.RULES_DIR / "landmines.md").read_text(encoding="utf-8")
    assert "子雷 18a" in text
    assert "子雷 18b" in text
    assert "子雷 18c" in text
    assert "子雷 18d" in text


def test_writing_style_core_has_new_taboos():
    """writing-style-core.md 必须增加 'AI 时代新增禁忌' 节."""
    text = (config.RULES_DIR / "writing-style-core.md").read_text(encoding="utf-8")
    assert "AI 时代新增禁忌" in text


def test_slop_thresholds_table_shape():
    """表结构不能被意外改坏——四个 criterion + moderate/severe 两档."""
    assert set(SLOP_THRESHOLDS.keys()) == {
        "neg_contrast", "emdash", "short_para", "simile"
    }
    for k, v in SLOP_THRESHOLDS.items():
        assert "moderate" in v and "severe" in v, f"{k} missing threshold tier"
        assert v["moderate"] < v["severe"], (
            f"{k}: moderate ({v['moderate']}) must be < severe ({v['severe']})"
        )

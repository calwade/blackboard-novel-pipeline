"""Planner · 题材锚定 · P1 环节 3.

锁定 Planner system prompt 中"题材锚定段"的存在、位置、强度：
- 必须出现在所有 numbered rules 之前（顶部最高优先级）
- 必须含具体反例关键词（嘉靖/烙疤/棺木 等典型跑偏符号）
- 必须强制 writing_self_check.genre_drift_risk 字段（自检凭证）

不调真实 LLM。
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _mk_bb(tmp_path: Path):
    from src.blackboard import Blackboard
    bb = Blackboard(root=tmp_path)
    bb.write_json("progress.json", {"current_chapter": 1, "completed": []})
    bb.write_json("outline.json", {
        "title": "T", "subtitle": "", "protagonist": "苏烬",
        "chapters": [
            {"ch": 1, "title": "第 1 章 · 灰烬契书",
             "beats": ["苏烬醒来", "拿到第一份契书"]},
        ],
    })
    bb.write_yaml("setting.yaml", {"genre": "末世奇幻", "era": "G22 纪元末世"})
    return bb


def test_system_prompt_has_genre_anchor_section(tmp_path):
    """题材锚定段必须存在 + 含关键词 + 含具体反例."""
    from src.agents.planner import Planner
    bb = _mk_bb(tmp_path)
    system, _user, _inputs = Planner()._build_prompts(bb, chapter=1)

    # 锚定段标记
    assert "🔴" in system, "题材锚定段必须用 🔴 高亮标识"
    assert "题材锚定" in system, "system prompt 必须含『题材锚定』标题"
    assert "凌驾" in system, "必须声明凌驾所有其他规则（最高优先级）"

    # 必须明确指向 era.md / writing-style-extra.md 作为权威
    assert "era.md" in system
    assert "writing-style-extra.md" in system

    # 关键约束：主角名/道具名/地名/时代锚点
    for keyword in ("主角名", "道具名", "地名", "时代锚点"):
        assert keyword in system, f"题材锚定段必须列出锚定维度：{keyword}"


def test_system_prompt_demands_genre_drift_risk_field(tmp_path):
    """writing_self_check.genre_drift_risk 必填字段必须出现在 system + JSON schema."""
    from src.agents.planner import Planner
    bb = _mk_bb(tmp_path)
    system, user, _ = Planner()._build_prompts(bb, chapter=1)

    # 字段名出现在 system prompt（解释字段意图）+ user prompt（JSON schema 要求填）
    assert "genre_drift_risk" in system, (
        "system prompt 必须含 genre_drift_risk 字段说明（rule 15 解释）"
    )
    assert "genre_drift_risk" in user, (
        "user prompt JSON schema 必须含 genre_drift_risk 字段（强制 LLM 输出）"
    )

    # system 中必须给出"自检凭证"格式范例：要求填实际值
    assert "已对齐 era.md" in system, (
        "system 必须给出 genre_drift_risk 的合法填法示例（如 '已对齐 era.md（主角=X，时代=Y）'）"
    )


def test_genre_anchor_section_appears_before_numbered_rules(tmp_path):
    """锚定段必须在 numbered rules（"1. " / "2. " ...）之前——确保是顶部最高优先级."""
    from src.agents.planner import Planner
    bb = _mk_bb(tmp_path)
    system, _, _ = Planner()._build_prompts(bb, chapter=1)

    pos_anchor = system.find("🔴")
    pos_rule_1 = system.find("\n1. ")
    pos_rule_15 = system.find("15.")

    assert pos_anchor > 0, "🔴 题材锚定段必须存在"
    assert pos_rule_1 > 0, "system 必须含 numbered rule '1. ...'"
    assert pos_anchor < pos_rule_1, (
        f"🔴 锚定段（@{pos_anchor}）必须出现在第 1 条 numbered rule（@{pos_rule_1}）之前——"
        "否则失去『最高优先级』含义"
    )
    # rule 15（genre_drift_risk 必填）应在 rule 1 之后（按编号）
    if pos_rule_15 > 0:
        assert pos_rule_1 < pos_rule_15, "rule 15 必须在 rule 1 之后"


def test_planner_prompt_examples_include_era_drift_warning(tmp_path):
    """system 必须含具体反例关键词，让 LLM 一眼识别"跑偏"长什么样.

    锁定的反例是真实事故素材：本来是末世题材，Planner 输出却出现『嘉靖通宝/棺木/烙疤』
    等明清/古风/民俗符号——这是 Oracle 报告里典型的跑偏关键词组合.
    """
    from src.agents.planner import Planner
    bb = _mk_bb(tmp_path)
    system, _, _ = Planner()._build_prompts(bb, chapter=1)

    # 至少出现 2 个典型跑偏反例符号——保证 LLM 看到具体禁词，不只看抽象规则
    drift_examples = ["嘉靖通宝", "烙疤", "棺木"]
    hits = sum(1 for ex in drift_examples if ex in system)
    assert hits >= 2, (
        f"system 必须含至少 2 个具体跑偏反例符号（如 嘉靖通宝/烙疤/棺木），"
        f"实际命中 {hits} 个：{[ex for ex in drift_examples if ex in system]}"
    )

    # 必须出现『驳回』『retry』『失效』等强约束词——让 LLM 知道这不是软建议
    assert any(kw in system for kw in ("驳回", "retry", "失效")), (
        "题材锚定段必须含驳回/retry/失效等强约束词，不是软建议"
    )

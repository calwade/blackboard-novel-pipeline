"""Generator · 动笔前检查（plan vs era.md 仲裁）· P1 环节 4.

锁定 Generator system prompt 中"动笔前检查"段的存在、位置、强度：
- 必须出现在 era.md 拼接段之后（保证 LLM 已先看 era.md 才看到仲裁规则）
- 必须给出 _planner_drift HTML 注释格式样例
- 必须明确"以 era.md 为准"

同时校验 rules/00-information-priority.md 已加入"题材锚 vs 计划锚"小节。

不调真实 LLM。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import config


def _mk_bb(tmp_path: Path):
    from src.blackboard import Blackboard
    bb = Blackboard(root=tmp_path)
    bb.write_yaml(
        "setting.yaml",
        {"genre": "末世奇幻", "era": "G22 纪元末世", "tone": "冷峻"},
    )
    bb.write_yaml(
        "characters.yaml",
        {"protagonist": {"name": "苏烬"}, "supporting": []},
    )
    bb.write_text("era.md", "末世 G22 纪元；核心道具：契书 / 灰烬 / 废墟")
    bb.write_text("writing-style-extra.md", "末世题材：少废话，多动作")
    (tmp_path / "chapters").mkdir(exist_ok=True)
    bb.write_json(
        "chapters/ch001.plan.json",
        {
            "ch": 1,
            "title": "第 1 章 · 灰烬契书",
            "scenes": [{"scene_id": 1, "cast": ["苏烬"]}],
            "chapter_type": "战斗",
        },
    )
    return bb


# ---------- Generator system prompt: drift correction clause ----------

def test_system_prompt_has_drift_correction_clause(tmp_path):
    """动笔前检查段必须存在 + 含 _planner_drift 注释格式 + 仲裁原则."""
    from src.agents.generator import Generator
    bb = _mk_bb(tmp_path)
    system, _, _ = Generator()._build_prompts(bb, chapter=1)

    # 标识：用 🔴 突出 + 标题"动笔前检查"
    assert "🔴" in system, "动笔前检查段必须用 🔴 高亮"
    assert "动笔前检查" in system, "system 必须含『动笔前检查』标题"

    # HTML 注释格式样例必须显式给出（不只是名字）
    assert "_planner_drift" in system, (
        "必须给出 _planner_drift HTML 注释命名约定让 Evaluator 看到仲裁结果"
    )

    # 仲裁原则
    assert "era.md" in system and "为准" in system, (
        "必须明确『以 era.md 为准』的仲裁结论"
    )


def test_drift_clause_position_after_era_md(tmp_path):
    """动笔前检查段必须在 era.md 拼接段之后——保证 LLM 已先看 era.md 才看到仲裁规则."""
    from src.agents.generator import Generator
    bb = _mk_bb(tmp_path)
    system, _, _ = Generator()._build_prompts(bb, chapter=1)

    pos_era = system.find("时代/世界观事实包")
    pos_drift = system.find("动笔前检查")

    assert pos_era > 0, "system 必须含『时代/世界观事实包』段（era.md 注入位）"
    assert pos_drift > 0, "system 必须含『动笔前检查』段"
    assert pos_era < pos_drift, (
        f"动笔前检查（@{pos_drift}）必须在『时代/世界观事实包』（@{pos_era}）之后——"
        "否则 LLM 看到仲裁规则时还没读 era.md，规则失效"
    )

    # 同时必须仍在 # 最终硬规则（ai-rhythm-taboos）之前——不能跑到尾部硬规则之后
    pos_taboo = system.find("最终硬规则")
    if pos_taboo > 0:
        assert pos_drift < pos_taboo, (
            "动笔前检查应该在『最终硬规则』（ai-rhythm-taboos 尾部）之前；"
            "尾部 recency-bias 位留给节奏硬上限"
        )


def test_drift_clause_examples_show_concrete_correction(tmp_path):
    """动笔前检查段必须含具体修正注释格式（[plan里X] → [era里Y]），不能只说"加注释"."""
    from src.agents.generator import Generator
    bb = _mk_bb(tmp_path)
    system, _, _ = Generator()._build_prompts(bb, chapter=1)

    # 必须含至少一个具体注释样式 — 用箭头/破折号示意修正方向
    has_arrow = "→" in system or "->" in system
    drift_idx = system.find("_planner_drift")
    # 在 _planner_drift 周围 200 字符内必须有「修正」+ 占位符
    window = system[max(0, drift_idx - 50): drift_idx + 250]
    assert "修正" in window, (
        "动笔前检查必须显式说明『修正 [plan里X] → [era里Y]』，不是只丢一个注释名"
    )
    assert has_arrow, "必须用 → 箭头展示修正方向（plan里X → era里Y）"

    # 必须涵盖"完全脱节"兜底路径（≥3 处冲突 → 拒写返回说明）
    assert "脱节" in system or ">3" in system or "完全冲突" in system or "abort" in system.lower(), (
        "必须含『若 plan 与 era.md 完全脱节则不要硬写』的兜底路径，避免 Generator 强行编造"
    )


# ---------- rules/00-information-priority.md sync ----------

def test_information_priority_md_has_genre_consistency_section():
    """rules/00-information-priority.md 必须新增『题材锚 vs 计划锚』小节，
    把 era.md / writing-style-extra.md 显式置于 plan.json 之上（题材一致性维度）."""
    p = config.RULES_DIR / "00-information-priority.md"
    assert p.exists(), "rules/00-information-priority.md 不存在"
    text = p.read_text(encoding="utf-8")

    # 新小节标题
    assert "题材锚 vs 计划锚" in text, (
        "缺少『题材锚 vs 计划锚（题材一致性维度）』小节——"
        "Generator 引用此文件做仲裁时找不到可锚定的条款"
    )

    # 必须明确 era.md 高于 plan.json
    assert "era.md" in text and "plan.json" in text
    assert "为准" in text, "必须给出明确『以 era.md 为准』的仲裁结论"

    # 必须含 _planner_drift 注释约定（与 Generator system prompt 对齐）
    assert "_planner_drift" in text, (
        "rules 文件必须记录 _planner_drift HTML 注释约定，作为跨 Agent 通信契约"
    )

    # 必须声明范围：只覆盖题材一致性维度，不污染其他维度
    assert "其他维度" in text or "只覆盖" in text, (
        "必须显式声明该规则的适用范围（只覆盖题材一致性，不无视 plan 的全部）"
    )

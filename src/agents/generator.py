"""Generator — writes the actual chapter prose.

Reads (all genre content comes from the active setting pack via state/):
  - state/chapters/ch{N:03d}.plan.json     — Planner's beat sheet
  - state/characters.yaml                  — character canon (setting-specific)
  - state/setting.yaml                     — active setting metadata
  - state/era.md                           — setting's world/era facts
  - state/writing-style-extra.md           — setting-specific style quirks
  - rules/writing-iron-laws.md             — 19 writing iron laws (subset of iron-laws.md, plot-logic red lines)
  - rules/writing-style-core.md            — 句段词描写技法手册 (technique manual, not rules)
  - rules/ai-rhythm-taboos.md              — AI-rhythm 4-threshold authority, appended last (conflict arbitration)
  - state/summaries/ch{N-1}.md             — continuity from prior chapter

Writes:
  - state/chapters/ch{N:03d}.md   (~3000 characters)

Temperature 0.85 — prose should have voice.
"""
from __future__ import annotations

import json

from ._base import BaseAgent
from ..blackboard import Blackboard


class Generator(BaseAgent):
    name = "generator"
    temperature = 0.85
    response_format = "text"
    max_tokens = 8000

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        plan_path = f"chapters/ch{chapter:03d}.plan.json"
        plan = bb.read_json(plan_path)
        characters = bb.read_yaml("characters.yaml")
        setting = bb.read_yaml("setting.yaml")

        writing_style_core = self._read_rule("writing-style-core.md")
        writing_style_extra = bb.read_text("writing-style-extra.md")
        writing_iron_laws = self._read_rule("writing-iron-laws.md")
        ai_rhythm_taboos = self._read_rule("ai-rhythm-taboos.md")
        era = bb.read_text("era.md")

        # Chapter-type-specific emphasis (skill #12)
        chapter_type = plan.get("chapter_type", "")
        chapter_type_block = _chapter_type_emphasis(chapter_type)

        # Writing self-check (A-5, Planner-authored risk scan). Skill #14.
        self_check = plan.get("writing_self_check", {}) or {}
        self_check_block = _format_self_check(self_check)

        inputs_read = [
            f"state/{plan_path}",
            "state/characters.yaml",
            "state/setting.yaml",
            "state/era.md",
            "state/writing-style-extra.md",
            "rules/writing-iron-laws.md",
            "rules/writing-style-core.md",
            "rules/ai-rhythm-taboos.md",
        ]

        # DNA tips (NovelDNA Stage 2.5): 按 chapter_type × scene_purpose 索引
        # 的创作手法样本库。Generator 写正文时按本章 chapter_type + scenes 的
        # purpose 查表。不存在 → 跳过（100% 向后兼容）。
        from .planner import _read_dna_tips
        dna_tips_block, dna_tips_inputs = _read_dna_tips(bb, for_agent="generator")
        inputs_read.extend(dna_tips_inputs)

        # P3：milestone 章节专属 payoff_recipes 注入。
        # 如果本章是 plot_arc.yaml 配置的 milestone，从 dna_structured.yaml 拉
        # 对应 anchor 的完整 recipe（formula + dialog_template + sample_50_chars），
        # 让 Generator 写正文时直接照抄对话节奏与工艺链。
        milestone_recipe_block, milestone_recipe_inputs = _read_milestone_recipe_for_generator(
            bb, chapter
        )
        inputs_read.extend(milestone_recipe_inputs)

        prior_summary = ""
        if chapter >= 2:
            p = f"summaries/ch{chapter-1:03d}.md"
            if bb.exists(p):
                prior_summary = bb.read_text(p)
                inputs_read.append(f"state/{p}")

        # Excerpt character canon — keep only protagonist + cast of this chapter
        cast_names = set()
        for scene in plan.get("scenes", []):
            for c in scene.get("cast", []):
                cast_names.add(c)
        cast_block = _extract_relevant_characters(characters, cast_names)

        # Setting-driven persona lines (keep it short)
        persona_lines = setting.get("author_persona_hints", []) or []
        persona_block = (
            "\n".join(f"- {h}" for h in persona_lines)
            if persona_lines
            else "- （本 setting 未提供作者画像提示）"
        )
        genre = setting.get("genre", "通用小说")
        era_label = setting.get("era", "")
        tone = setting.get("tone", "")

        # Style lock — the non-negotiable "must NOT drift into" list.
        # Source: skill #24 — long-chain writing drifts easily; declare
        # prohibited voices explicitly at the top of every Generator call.
        prohibited_styles = setting.get("prohibited_styles", []) or []
        if prohibited_styles:
            prohibited_block = "\n".join(f"- {s}" for s in prohibited_styles)
        else:
            prohibited_block = "- （本 setting 未声明风格禁止清单）"

        system = (
            f"你是一名职业网文作家。本次创作的题材与基调由下方 setting 决定，\n"
            f"你的任务：把节拍表写成约 3000 字的中文章节正文。\n"
            f"\n"
            f"# 风格锁定（不可逾越的基调下限）\n"
            f"本作品属于：{genre}，基调：{tone}。\n"
            f"**严禁跨题材串味**，以下风格任何一条都视为基调崩坏：\n"
            f"{prohibited_block}\n"
            f"\n"
            f"# 当前 Setting\n"
            f"- 题材：{genre}\n"
            f"- 时代/世界观：{era_label}\n"
            f"- 基调：{tone}\n"
            f"- 作者画像提示：\n{persona_block}\n"
            f"\n"
            f"# 通用铁律\n"
            f"1. Show-Don't-Tell：不直接宣告情绪（❌他很愤怒），用行动细节展示（✅他捏碎了茶杯）。\n"
            f"2. 严禁 AI 味：少用『了』字；避免『虽然...但是...』转折词堆砌；\n"
            f"   避免四字成语堆砌与固定句式；段落长短错落，每段 1 个核心信息点，3-5 行。\n"
            f"   群像反应禁止写成『全场震惊』『众人倒吸凉气』；改为 1-2 个**具体角色**的身体反应、判断偏差或利益震荡。\n"
            f"3. 人物动机必须利益化：主角行动必须有算计；反派不能降智；配角不是工具人。\n"
            f"   留人/钓鱼/示弱/借刀可以，**前提只能是利益更大，绝不能是心软**。\n"
            f"4. 严格按节拍表的 scene 顺序写，不遗漏也不擅自新增情节。\n"
            f"5. 开篇要承接 opening_hook 的精神（不是照抄），结尾要留下 closing_hook。\n"
            f"6. 不写任何元注释、不加章节小标题以外的 meta 内容。\n"
            f"7. 输出格式：第一行章节标题（用 Markdown `# ` 前缀），然后正文。\n"
            f"8. **禁止百科式堆砌设定**。下方 era.md 是参考资料，它的事实必须**融入场景的感官/动作/对白**；\n"
            f"   严禁以解说性段落形式复述世界观、制度、时代背景。\n"
            f"9. **每个场景至少推进一项**：信息 / 地位 / 资源 / 伤亡 / 仇恨 / 境界。\n"
            f"   小冲突尽快兑现反馈，不要把爽点无限后置。\n"
            f"10. 收益必须**具体化**。不得用『更强了』『暴涨』『海量』『难以估量』掩盖数值跳变；\n"
            f"    具体落到道具名、资源单位、地位变化或已回收伏笔。\n"
            f"\n"
            f"# 动笔前的检查\n\n"
            f"违反任何 iron_law 都会被 Evaluator 抓——写作时主动向 Evaluator 兼容。\n"
            f"具体红线见下方「创作铁律」段（7 条核心，写正文前先把每条在心里过一遍）。\n"
            f"\n"
            f"# 本章类型：{chapter_type or '未指定'}\n\n"
            f"{chapter_type_block}\n"
            f"\n"
            f"# 写作自检（Planner 标注的风险扫描 —— 本章必须主动规避）\n\n"
            f"{self_check_block}\n"
            f"\n"
            f"# 创作铁律（剧情逻辑红线，违反必被 Evaluator 抓）\n\n"
            + writing_iron_laws
            + f"\n\n# 通用写作风格规范\n\n"
            + writing_style_core
            + f"\n\n# 题材特有风格补充（由 setting 注入）\n\n"
            + writing_style_extra
            + f"\n\n# 时代/世界观事实包（仅供融入场景，严禁整段复述）\n\n"
            + era
            + (f"\n\n{dna_tips_block}" if dna_tips_block else "")
            + (f"\n\n{milestone_recipe_block}" if milestone_recipe_block else "")
            + "\n\n# ⚠ 最终硬规则（冲突仲裁：与上文冲突时以此为准）\n\n"
            + ai_rhythm_taboos
        )

        user = (
            f"# 本章节拍表\n\n```json\n{json.dumps(plan, ensure_ascii=False, indent=2)}\n```\n\n"
            f"# 本章出场人物档案\n\n```yaml\n{cast_block}\n```\n\n"
            f"# 上一章摘要（连续性用，不是复述）\n\n"
            + (prior_summary if prior_summary else "（这是首章）")
            + "\n\n"
            f"# 任务\n\n"
            f"严格按节拍表把本章（第 {chapter} 章）写成约 3000 字的中文小说正文。"
            f"第一行是章节标题（用 `# ` 前缀），接下来是正文。不要任何其他输出。"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        bb.write_text(f"chapters/ch{chapter:03d}.md", raw.strip() + "\n")


def _extract_relevant_characters(characters: dict, names: set[str]) -> str:
    """Return a YAML-like snippet with only the relevant protagonist + supporting."""
    import yaml

    out = {}
    proto = characters.get("protagonist", {})
    if proto.get("name") in names or not names:
        out["protagonist"] = proto

    supporting = []
    for c in characters.get("supporting", []):
        if not names or c.get("name") in names or any(
            n in c.get("name", "") for n in names
        ):
            supporting.append(c)
    if supporting:
        out["supporting"] = supporting

    # Fallback: if no match, return everything (don't leave Generator blind)
    if not out or not supporting:
        out = characters

    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _chapter_type_emphasis(chapter_type: str) -> str:
    """Return per-chapter-type writing emphasis.

    Source: skill #12 — chapter types must be written with different
    intensity. A 过渡 chapter written like a 战斗 chapter = pacing failure.
    """
    table = {
        "战斗": (
            "这是**战斗章**。核心是正面冲突。\n"
            "- 强调画面感：具体动作（谁出手、击中了哪里、谁挡住了）> 形容词堆砌\n"
            "- 强调受力与代价：每一次交锋都要有**可量化的损失**（伤势位置、武器损耗、内力消耗、筹码变化）\n"
            "- 强调节奏：短句与长句交替，动作密集段段落要短（1-3 行）\n"
            "- 结尾必须给出**谁赢了什么 / 输了什么**——不是『终于打完了』的模糊感\n"
            "- 禁止：群像『全场震惊』、抽象『一股巨力涌来』、数据模糊『实力暴涨』\n"
        ),
        "布局": (
            "这是**布局章**。核心是暗流、试探、信息交换。\n"
            "- 强调对话层次：每句台词都要推进**立场 / 情报 / 关系**中的一项\n"
            "- 强调信息差：清楚标注谁知道什么、谁误判什么、谁在诈谁（可在心理独白或暗示中体现）\n"
            "- 强调场景张力：不需要动手，但空气要紧——一个手势、一杯茶、一个眼神都有分量\n"
            "- 结尾必须让读者意识到：**局已经铺开**，下一章某个点会触发连锁\n"
            "- 禁止：对话变成信息倾倒（某角色一口气讲完所有背景）\n"
        ),
        "过渡": (
            "这是**过渡章**。核心是状态变化与钩子。\n"
            "- 节奏较缓但**不得无推进**：位置 / 时间 / 心态 / 身份中至少一项要发生变化\n"
            "- 强调钩子：开篇钩子承上，章末钩子必须**诱导读者进入下一章**\n"
            "- 篇幅可以略短，但场景不得超过 3 个，避免散乱\n"
            "- 可安排轻度插曲：回忆、伏笔暗示、配角闲谈推进世界观\n"
            "- 禁止：拖稿（整章都是走路 / 吃饭 / 回忆）、无冲突的风景文\n"
        ),
        "回收": (
            "这是**回收章**。核心是兑现前文伏笔、结算旧账。\n"
            "- 强调满足感：被伏笔吊了 N 章的读者**此刻等着这一幕**，不要稀释情绪\n"
            "- 必须明确标注回收了哪些 hook_id（在状态卡的活跃伏笔表中删除对应行）\n"
            "- 回收方式要有**意外性**：不是直接兑现读者预期，而是在预期之上多转一层（例：敌人回来了但不是来复仇，是来求救）\n"
            "- 结尾必须**顺势开新循环**：老债已清，下一笔新债已下意识埋下\n"
            "- 禁止：回收过于敷衍（一句话带过）、回收后无后续钩子\n"
        ),
    }
    return table.get(
        chapter_type,
        "（Planner 未指定章节类型——按默认节奏写，但必须在每个 scene 的 `advances` 字段\n"
        "中说明本场景推进了信息 / 地位 / 资源 / 伤亡 / 仇恨 / 境界 中的哪一项。）",
    )


def _format_self_check(self_check: dict) -> str:
    """Render Planner's writing_self_check into a Markdown table for Generator.

    Source: skill #14 (A-5 reopened) — the Planner-authored risk scan table.
    Each non-empty, non-"无" entry becomes a concrete constraint Generator
    must work around when writing prose.
    """
    label_map = {
        "ooc_risk": "人物 OOC 风险",
        "info_leak_risk": "反派/配角信息越界风险",
        "setting_conflict_risk": "世界观/时代冲突风险",
        "power_scaling_risk": "战力/资源跳数量级风险",
        "pacing_risk": "节奏拖沓或爽点后置风险",
        "vocab_fatigue_risk": "高疲劳词风险",
    }
    if not self_check:
        return (
            "（Planner 未提供 writing_self_check。按通用铁律自律：OOC / 信息越界 / "
            "战力跳级 / 拖稿 / 疲劳词 五项自查。）"
        )

    lines = ["| 检查项 | Planner 提示 |", "|---|---|"]
    for key, label in label_map.items():
        val = self_check.get(key, "").strip() if isinstance(self_check.get(key), str) else ""
        if not val:
            val = "（未填写，按通用铁律自律）"
        lines.append(f"| {label} | {val} |")
    lines.append("")
    lines.append("**写作原则**：以上任何**非『无』**的提示，都必须在本章正文中显式规避。")
    return "\n".join(lines)


# ---------- P3: payoff_recipes injection (milestone-aware) ----------

def _read_milestone_recipe_for_generator(bb, chapter: int) -> tuple[str, list[str]]:
    """Render the payoff_recipes block (动笔前必读) for Generator.

    行为：
      1. 读 state/dna_structured.yaml；不存在或无 payoff_recipes 字段 → 返回空。
      2. 渲染 payoff_recipes 全表（4 个 anchor 的 formula + dialog_template + sample）。
      3. 若 plot_arc.yaml 存在且 current_chapter 命中某 milestone：
           - 优先用 milestone.payoff_recipe_ref 解析的具体 recipe（含 villain_defeat_patterns
             pattern 命中）作为"⚠ 本章必须按此节奏写"的特别强调段
           - milestone 无 payoff_recipe_ref 时，用 milestone.anchor 取通用 recipe
      4. 失败 / 全空 → 返回空字符串 + 空 inputs。

    返回 (block_markdown, inputs_read_paths)。
    """
    if not bb.exists("dna_structured.yaml"):
        return "", []
    try:
        dna = bb.read_yaml("dna_structured.yaml") or {}
    except Exception:
        return "", []
    if not isinstance(dna, dict):
        return "", []

    payoff_recipes = dna.get("payoff_recipes") or {}
    if not isinstance(payoff_recipes, dict) or not payoff_recipes:
        return "", []

    inputs: list[str] = ["state/dna_structured.yaml"]
    out: list[str] = []
    out.append("# 📖 dna 爽点配方（payoff_recipes —— 动笔前必读）")
    out.append("")
    out.append(
        "下面 4 个 anchor 的 recipe 来自源小说 DNA 提取——是本作品里"
        "**已被验证有效**的爽点工艺链。写到对应类型场景时，按 dialog_template "
        "的 speaker × beats 节奏推进，不要凭空发挥。"
    )
    out.append("")

    def _render_recipe(anchor: str, recipe: dict, *, emphasized: bool = False) -> list[str]:
        sub: list[str] = []
        head = f"## {anchor} 配方" + ("（⚠ 本章重点）" if emphasized else "")
        sub.append(head)
        sub.append("")
        formula = (recipe.get("formula") or "").strip()
        if formula:
            sub.append(f"- 工艺链：{formula}")
        dlg = recipe.get("dialog_template") or []
        if isinstance(dlg, list) and dlg:
            sub.append("- 对话剧本（speaker × beats）：")
            for step in dlg:
                if not isinstance(step, dict):
                    continue
                speaker = str(step.get("speaker", "?"))
                beats = step.get("beats") or []
                if isinstance(beats, list):
                    beats_str = " / ".join(str(b) for b in beats)
                else:
                    beats_str = str(beats)
                sub.append(f"  - {speaker}: {beats_str}")
        sample = (recipe.get("sample_50_chars") or "").strip()
        if sample:
            sample_one_line = sample.replace("\n", " ")
            sub.append(f"- 50-100 字样本：{sample_one_line}")
        sub.append("")
        return sub

    # 全 4 个 anchor 默认全渲染（即便某些 anchor 是空 dict，也会被 _render_recipe 跳过空字段）
    canonical_order = ("爽感", "掌控感", "黑色幽默", "生存智慧")
    for anchor in canonical_order:
        recipe = payoff_recipes.get(anchor)
        if isinstance(recipe, dict) and (
            recipe.get("formula") or recipe.get("dialog_template") or recipe.get("sample_50_chars")
        ):
            out.extend(_render_recipe(anchor, recipe))

    # 也把 LLM 输出里偏离 4 anchor 的额外 key（罕见）加上
    for anchor, recipe in payoff_recipes.items():
        if anchor in canonical_order:
            continue
        if isinstance(recipe, dict) and (
            recipe.get("formula") or recipe.get("dialog_template") or recipe.get("sample_50_chars")
        ):
            out.extend(_render_recipe(anchor, recipe))

    # P3 续：milestone 章节 → 拉 plot_arc.yaml + 在末尾加"本章必须按此 recipe 写"特别强调段
    milestone_block = _resolve_chapter_milestone_recipe(bb, dna, chapter)
    if milestone_block:
        if "state/plot_arc.yaml" not in inputs:
            inputs.append("state/plot_arc.yaml")
        out.append("")
        out.append("---")
        out.append("")
        out.append(milestone_block)

    if len(out) <= 4:
        # 4 行 = header + 1 空行 + 1 描述行 + 1 空行；说明 4 个 anchor 都空且无 milestone
        return "", []

    return "\n".join(out) + "\n", inputs


def _resolve_chapter_milestone_recipe(bb, dna: dict, chapter: int) -> str:
    """If `chapter` is a milestone (per plot_arc.yaml), render an extra
    `⚠ 本章必须按此 recipe 写` block. Returns "" otherwise / on any failure.
    """
    if not bb.exists("plot_arc.yaml"):
        return ""
    try:
        from src.tools.plot_arc import read_plot_arc, derive_planner_context

        arc = read_plot_arc(bb.root)
    except Exception:
        return ""
    if arc is None:
        return ""
    try:
        ctx = derive_planner_context(arc, chapter)
    except ValueError:
        return ""
    cur_ms = ctx.get("current_milestone")
    if cur_ms is None:
        return ""

    # Determine ref: prefer payoff_recipe_ref, fall back to anchor only
    ref = getattr(cur_ms, "payoff_recipe_ref", None) or cur_ms.anchor
    from .planner import _resolve_recipe

    recipe = _resolve_recipe(dna, ref)
    if not recipe:
        return ""

    out = [
        f"## ⚠ 本章是 milestone（ch{cur_ms.chapter} · {cur_ms.type}）—— 必须按此 recipe 写正文",
        "",
        f"- payoff_recipe_ref：`{ref}`（anchor={recipe['anchor']}"
        + (f" · pattern={recipe['pattern']}" if recipe.get("pattern") else "")
        + ")",
    ]
    if recipe.get("formula"):
        out.append(f"- 工艺链：{recipe['formula']}")
    if recipe.get("setup"):
        out.append(f"- setup（反派初态）：{recipe['setup']}")
    if recipe.get("twist"):
        out.append(f"- twist（破局点）：{recipe['twist']}")
    if recipe.get("payoff_line_template"):
        out.append(f"- 主角点评句式模板：{recipe['payoff_line_template']}")

    dlg = recipe.get("dialog_template") or []
    if dlg:
        out.append("- 对话剧本（speaker × beats）：")
        for step in dlg:
            if not isinstance(step, dict):
                continue
            speaker = str(step.get("speaker", "?"))
            beats = step.get("beats") or []
            if isinstance(beats, list):
                beats_str = " / ".join(str(b) for b in beats)
            else:
                beats_str = str(beats)
            out.append(f"  - {speaker}: {beats_str}")

    if recipe.get("sample_50_chars"):
        out.append(f"- 50-100 字样本：{str(recipe['sample_50_chars']).replace(chr(10), ' ')}")

    out.append("")
    out.append(
        "**写本章正文时**：必须有一段≥150 字直接对应工艺链 + dialog_template；"
        "speaker 轮换节奏要保留；50-100 字样本是**风格锚点**（不是抄句子，"
        "是抄『句法/节奏/留白方式』）。"
    )
    return "\n".join(out)

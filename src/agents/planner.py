"""Planner — produces the beat sheet for a given chapter.

Reads:
  - state/outline.json (this chapter's entry + 1 prior + 1 next for context)
  - state/progress.json (for progress awareness, not for context accumulation)
  - state/summaries/ch{N-1}.md and ch{N-2}.md (at most, if exist)

Writes:
  - state/chapters/ch{N:03d}.plan.json

The Planner does NOT write prose. It takes the outline's high-level beats
and turns them into a fine-grained scene-by-scene plan the Generator can
execute faithfully.
"""
from __future__ import annotations

import json
import re

from ._base import BaseAgent
from ..blackboard import Blackboard


class Planner(BaseAgent):
    name = "planner"
    temperature = 0.4
    response_format = "json"
    max_tokens = 3000

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        outline = bb.read_json("outline.json")
        chapters = outline["chapters"]
        # Find the current chapter entry
        cur = next((c for c in chapters if c["ch"] == chapter), None)
        if cur is None:
            raise ValueError(f"Chapter {chapter} not in outline")

        # Setting metadata for the persona line
        try:
            setting = bb.read_yaml("setting.yaml")
        except (OSError, Exception):
            setting = {}
        genre = setting.get("genre", "通用小说")
        era_label = setting.get("era", "")

        # Multi-level summary context (L1 last-2 + L2 most-recent-arc +
        # L3 most-recent-volume if applicable). This scales to 50+ chapters
        # without context overflow.
        from .multi_level_summarizer import assemble_long_chain_context
        from .status_card_updater import read_current_status_card
        from .hook_keeper import read_pending_hooks

        prior_summary_block, summary_inputs = assemble_long_chain_context(bb, chapter)
        status_card_text, status_card_inputs = read_current_status_card(bb)
        pending_hooks_text, pending_hooks_inputs = read_pending_hooks(bb)

        # Golden-three reflection (C-31): when planning ch3, surface the
        # closing_hook of ch1 + ch2 so Planner must deliver at least one
        # feedback (reveal/payoff/reversal/status-change) within ch3.
        golden_three_block, golden_three_inputs = _collect_golden_three_hooks(bb, chapter)

        inputs_read: list[str] = (
            ["state/outline.json", "state/setting.yaml"]
            + summary_inputs
            + status_card_inputs
            + pending_hooks_inputs
            + golden_three_inputs
        )

        system = (
            f"你是拥有 20 年经验的网络小说责编。当前题材：{genre}；时代/世界观：{era_label}。\n"
            "你的任务：把一章的『大纲条目』细化为 Generator 可以直接下笔的『节拍表』。\n"
            "绝对铁律：\n"
            "1. 严格输出 JSON，不写任何散文或解释。\n"
            "2. 每个 scene（场景）必须包含：scene_id、场景地点、出场人物、冲突或张力、"
            "目的（推进主线/塑造人物/埋伏笔）、预估字数。\n"
            "3. 一章拆成 3-5 个 scene，总字数目标 ~3000 字。\n"
            "4. 每个 scene 必须提供至少 2 处『具体感官细节』的写作提示（视觉/听觉/触觉/气味/味觉）。\n"
            "5. 必须给出开篇钩子（opening_hook，≤30 字）和章末钩子（closing_hook，≤40 字）。\n"
            "6. 必须列出 3-5 个 landmines_to_avoid（写作时要回避的具体雷点）。\n"
            "7. 不编造大纲里没有的情节，但可以为大纲的 beats 补充细节与过渡。\n"
            "8. **必读『当前状态卡』**：如果存在，它是当前时间点的权威状态覆盖文件——\n"
            "   时间锚点、敌我关系、资源、已知真相、活跃伏笔、建议的下一章任务都以它为准。\n"
            "   计划中的 scene 必须与状态卡一致；状态卡的『下一章任务卡』是你写本章 plan 的**种子建议**。\n"
            "   如果大纲和状态卡冲突（如主角已在状态卡中死亡但大纲仍让他出场），以**最新正文+状态卡**为准。\n"
            "9. **必标 chapter_type**（章节类型），四选一：\n"
            "   - `战斗`：本章主要冲突是物理/言语/策略对抗（动手、对线、博弈正面交锋）——\n"
            "     强调画面、受力、节奏感、收益（谁输了什么、谁赢了什么）。\n"
            "   - `布局`：本章主要是试探、交易、威慑、信息交换、埋线——\n"
            "     强调暗流、立场变化、对话层次、信息差（谁知道什么）。\n"
            "   - `过渡`：本章推进地点/时间/状态，节奏较缓——\n"
            "     强调状态变化、钩子（把读者引向下一章）、避免无意义拖延。\n"
            "   - `回收`：本章主要回应前文埋设的伏笔、兑现旧承诺、结算旧仇——\n"
            "     强调满足感（读者等这一刻）、因果收束、以及顺势启动新循环。\n"
            "   **每个 scene 也可以独立标注 scene_type**（可选），但章节整体 chapter_type 必填。\n"
            "   每个 scene 必须在 `advances` 字段声明本场景至少推进了以下哪一项：\n"
            "   `信息` / `地位` / `资源` / `伤亡` / `仇恨` / `境界`——**不得为空或笼统**。\n"
            "10. **必填 `writing_self_check`（写作自检表）**：这是 Generator 动笔前的风险扫描表，\n"
            "    告诉 Generator 本章最该避开的坑。必须基于大纲 + 状态卡 + 前情，识别出下列每项的风险并给具体提示：\n"
            "    - `ooc_risk`：本章哪些人物的哪些行为最容易写 OOC（人物档案+redlines）\n"
            "    - `info_leak_risk`：反派/配角是否可能写成'知道本不应知道的信息'（对照状态卡的已知真相表）\n"
            "    - `setting_conflict_risk`：与世界观/时代/物价可能冲突的点（对照 era.md）\n"
            "    - `power_scaling_risk`：战力、资源、境界可能跳数量级的点\n"
            "    - `pacing_risk`：节奏拖沓或爽点后置的风险\n"
            "    - `vocab_fatigue_risk`：本章易出现的高疲劳词（冷笑/倒吸凉气/心跳漏了一拍等）\n"
            "    每项为一句话具体提示（≤30 字），无风险写 `无`。\n"
        )

        cur_json = json.dumps(cur, ensure_ascii=False, indent=2)
        user = (
            f"# 本章（第 {chapter} 章）大纲条目\n\n```json\n{cur_json}\n```\n\n"
            f"# 当前状态卡（当前时间点的权威状态，优先于摘要；冲突以正文+状态卡为准）\n\n"
            f"{status_card_text}\n\n"
            f"# 待回收伏笔池（优先安排回收旧钩子，不要只埋新坑）\n\n"
            f"{pending_hooks_text}\n\n"
            + golden_three_block
            + f"# 前情摘要（Context Reset，只有这一点上下文）\n\n{prior_summary_block}\n\n"
            f"# 输出 JSON 结构\n\n"
            "```json\n"
            "{\n"
            '  "ch": <int>,\n'
            '  "title": "<str>",\n'
            '  "chapter_type": "战斗|布局|过渡|回收",\n'
            '  "opening_hook": "<≤30字>",\n'
            '  "scenes": [\n'
            "    {\n"
            '      "scene_id": 1,\n'
            '      "location": "<str>",\n'
            '      "cast": ["<人名>", ...],\n'
            '      "conflict": "<一句话冲突/张力>",\n'
            '      "purpose": "推进主线|塑造人物|埋伏笔",\n'
            '      "sensory_prompts": ["<细节1>", "<细节2>"],\n'
            '      "advances": ["信息|地位|资源|伤亡|仇恨|境界 中至少一项"],\n'
            '      "word_target": <int>\n'
            "    }, ...\n"
            "  ],\n"
            '  "closing_hook": "<≤40字>",\n'
            '  "landmines_to_avoid": ["<具体雷点>", ...],\n'
            '  "writing_self_check": {\n'
            '    "ooc_risk": "<具体提示或 无>",\n'
            '    "info_leak_risk": "<具体提示或 无>",\n'
            '    "setting_conflict_risk": "<具体提示或 无>",\n'
            '    "power_scaling_risk": "<具体提示或 无>",\n'
            '    "pacing_risk": "<具体提示或 无>",\n'
            '    "vocab_fatigue_risk": "<具体提示或 无>"\n'
            '  }\n'
            "}\n"
            "```"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        # Parse JSON, be forgiving of common LLM quirks
        plan = _parse_json(raw)
        plan["ch"] = chapter  # enforce consistency
        bb.write_json(f"chapters/ch{chapter:03d}.plan.json", plan)


def _parse_json(raw: str):
    """Strip ```json fences if present, then json.loads."""
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
    if m:
        s = m.group(1)
    return json.loads(s)


def _collect_golden_three_hooks(bb: Blackboard, chapter: int) -> tuple[str, list[str]]:
    """Return (block_text, inputs_read) for the golden-three feedback rule (C-31).

    Only produces content when `chapter == 3` (the last of the golden three).
    Reads ch1/ch2 plan.json's closing_hook to remind Planner that ch3 must
    deliver at least one concrete payoff (信息反转 / 打脸 / 收益兑现 / 地位变化),
    not just plant more hooks.

    For chapter != 3, returns empty string and empty inputs list (silent).
    """
    if chapter != 3:
        return "", []

    hooks = []
    inputs = []
    for n in (1, 2):
        plan_path = f"chapters/ch{n:03d}.plan.json"
        if bb.exists(plan_path):
            try:
                plan = bb.read_json(plan_path)
                closing = (plan.get("closing_hook") or "").strip()
                opening = (plan.get("opening_hook") or "").strip()
                if closing or opening:
                    hooks.append(
                        f"- ch{n}.opening_hook: {opening or '（无）'}\n"
                        f"  ch{n}.closing_hook: {closing or '（无）'}"
                    )
                    inputs.append(f"state/{plan_path}")
            except Exception:
                pass

    if not hooks:
        return (
            "# 黄金三章反馈检（C-31）\n\n"
            "本章是第 3 章。虽然前两章的 plan 不可用，但仍请**至少兑现一个具体反馈**——\n"
            "不是『预告下一章会爽』，而是当下发生：信息反转 / 打脸 / 收益兑现 / 地位变化 / 回收某个伏笔。\n"
            "禁止把整个三章都变成铺垫。\n\n"
        ), inputs

    joined = "\n".join(hooks)
    return (
        "# 黄金三章反馈检（C-31）\n\n"
        "本章是第 3 章。黄金三章原则：**三章内必须有至少一次具体反馈兑现**。\n"
        "反馈形式不限于『打人』——可以是信息反转、打脸、收益兑现（资源/地位变化）、伏笔回收、关系质变。\n"
        "下面是前两章的 hook 钩子，请在本章 plan 中**至少回应其中一个**，给出**当下兑现**的场景：\n\n"
        f"{joined}\n\n"
        "**禁止**把整个前三章都当铺垫——本章不得只埋新坑不收旧账。\n\n",
        inputs,
    )

"""CharacterGuard — background auditor for character drift / OOC behavior.

Dual-source 判据（2026-05-15 重构）
-----------------------------------
读两份角色档案，区分两套判据：

1. **基线宪法 `characters.yaml`**（作者意图，不可变）
   - 违反基线人物的 `traits` / `redlines` = **严重 OOC**

2. **运行时演员表 `characters-cast.yaml`**（先例库，由 CastUpdater 维护）
   - 已有条目（且 `first_appeared_ch < 当前章`）的角色，本章行为与 cast 中
     `traits` / `voice_tags` / `relations` 冲突 = **中等自相矛盾**
   - 本章首次出现的全新角色（`first_appeared_ch == 当前章` 或不在 cast 里）
     = **不报警**（避免对刚出场的方洪/老刘等做出"无中生有"假阳性）

当 cast 文件不存在时（`cast_tracking_enabled=False` 的旧作品），
CharacterGuard 退回到只读基线 + 历史摘要的旧行为（100% 向后兼容）。

Reads:
  - state/chapters/ch{N:03d}.md
  - state/characters.yaml
  - state/characters-cast.yaml             — 可选；存在时启用先例判据
  - state/summaries/ch*.md                 — 历史一致性

Writes:
  - state/fixes/ch{N:03d}.char-patch.md

Independent Fan-Out partner to AISlopGuard.
"""
from __future__ import annotations

import json

from ..agents._base import BaseAgent
from ..blackboard import Blackboard


class CharacterGuard(BaseAgent):
    name = "character_guard"
    temperature = 0.2
    response_format = "json"
    max_tokens = 3000

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        chapter_path = f"chapters/ch{chapter:03d}.md"
        text = bb.read_text(chapter_path)
        characters = bb.read_text("characters.yaml")
        inputs_read = [f"state/{chapter_path}", "state/characters.yaml"]

        # Optional: running cast (CastUpdater output). 仅当存在时启用先例判据。
        cast_yaml: str | None = None
        if bb.exists("characters-cast.yaml"):
            cast_yaml = bb.read_text("characters-cast.yaml")
            inputs_read.append("state/characters-cast.yaml")

        # Summaries 窗口化（2026-05-15 解耦）
        # cast 启用时 cast.yaml 已经是更高密度的『先例库』，summaries 冗余 → 不读
        # cast 缺失时退回旧行为，但只取最近 5 章避免 ch30+ 时 prompt 过载（25K+ tokens）
        if cast_yaml is not None:
            summary_chapters: list[int] = []
        else:
            start = max(1, chapter - 5)
            summary_chapters = list(range(start, chapter))

        prior_summaries_parts = []
        for n in summary_chapters:
            p = f"summaries/ch{n:03d}.md"
            if bb.exists(p):
                prior_summaries_parts.append(f"### 第 {n} 章摘要\n" + bb.read_text(p))
                inputs_read.append(f"state/{p}")
        prior_block = (
            "\n\n".join(prior_summaries_parts)
            if prior_summaries_parts
            else "（这是首章，无前情）"
        )

        # ---------- system prompt ----------
        system_lines = [
            "你是专门扫描人设偏移（OOC）的独立审计员。",
            "你的职责范围只有人设一致性——AI 味、剧情 pacing 等问题不归你管。",
            "",
        ]

        if cast_yaml is not None:
            # 双档判据
            system_lines += [
                "# 你有两份角色档案，对应两套判据",
                "",
                "## 档案 A · 基线宪法（characters.yaml）",
                "",
                "作者明确写下的角色设定。**严重 OOC** 判据：",
                "1. 主角行为是否违反 characters.yaml 中的 `traits` 或 `redlines`？",
                "   - 比如『极致利己』的主角突然圣母心发作？",
                "   - 比如『不碰毒品生意』被越界？",
                "2. 配角行为是否与该配角的 `motivation` 或 `loyalty_source` 一致？",
                "",
                "## 档案 B · 运行时演员表（characters-cast.yaml）",
                "",
                "由 CastUpdater 在每章末维护的『先例库』——记录从前几章累积观察到的",
                "性格特征、说话风格、关系演进。**中等自相矛盾** 判据：",
                "3. 已建立的累积人物（`in_baseline=false` 且 `first_appeared_ch < 当前章`），",
                "   本章行为是否与 cast 中累积的 `traits` / `voice_tags` / `relations` 冲突？",
                "4. 口头禅、说话风格是否与 cast 中的 `voice_tags` 一致？",
                "",
                "## 不报警的情况",
                "",
                "5. **本章首次出现的全新角色**（`first_appeared_ch == 当前章`，或角色不在 cast 里）",
                "   不要报『无中生有』——LLM 自然引入新人物是被允许的，CastUpdater 会在本章末登记。",
                "6. 基线人物本章未登场，与人设无关，不要报。",
                "",
            ]
        else:
            # 单档（旧）判据
            system_lines += [
                "# 你的判据",
                "",
                "1. 主角行为是否违反 characters.yaml 中的 traits 或 redlines？",
                "   - 比如『极致利己』的主角突然圣母心发作？",
                "   - 比如『不碰毒品生意』被越界？",
                "2. 配角行为是否与该配角的 motivation 或 loyalty_source 一致？",
                "3. 角色之间的关系发展是否有前文铺垫支撑（不看大纲，只看前情摘要）？",
                "4. 口头禅、说话风格是否与角色标签一致？",
                "",
                "（注：本作品未启用 cast tracking — characters-cast.yaml 不存在。",
                "『无中生有』类报警仅在没有 cast 文件时生效；有 cast 时由 CastUpdater 接管登记。）",
                "",
            ]

        system_lines += [
            "# 输出要求",
            "",
            "严格 JSON。包含 ooc_score（0 零偏移 — 10 严重崩坏）、hits（每条：character、",
            "deviation（如何偏移）、prior_baseline（引用依据）、suggested_fix）。",
            "宁可漏判也不要强行编造。",
        ]
        if cast_yaml is not None:
            system_lines.insert(
                -1,
                "（prior_baseline 字段请注明来自档案 A『基线宪法』还是档案 B『运行时演员表』。）",
            )
        system = "\n".join(system_lines) + "\n"

        # ---------- user prompt ----------
        if cast_yaml is not None:
            user_parts = [
                f"# 档案 A · 基线宪法 (characters.yaml)\n\n```yaml\n{characters}\n```\n",
                f"# 档案 B · 运行时演员表 (characters-cast.yaml，截至上一章末)\n\n"
                f"```yaml\n{cast_yaml}\n```\n",
            ]
            example_baseline = "<引用档案 A 的 trait/redline 或档案 B 的累积观察>"
        else:
            user_parts = [
                f"# 人物档案 (characters.yaml)\n\n```yaml\n{characters}\n```\n",
            ]
            example_baseline = "<引用 characters.yaml 或前情摘要作为依据>"

        user_parts += [
            f"# 前情摘要\n\n{prior_block}\n",
            f"# 待审章节（第 {chapter} 章）\n\n{text}\n",
            "# 输出 JSON 结构示例\n"
            + json.dumps(
                {
                    "ooc_score": 2,
                    "hits": [
                        {
                            "character": "<角色名>",
                            "deviation": "<具体说明本章哪里违反>",
                            "prior_baseline": example_baseline,
                            "suggested_fix": "<具体的修改方向>",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
        ]
        user = "\n".join(user_parts)
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        import re

        s = raw.strip()
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
        if m:
            s = m.group(1)
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            obj = {
                "ooc_score": -1,
                "hits": [],
                "_parse_error": str(e),
                "_raw_excerpt": raw[-500:],
            }

        md = [
            f"# CharacterGuard 补丁 · 第 {chapter} 章",
            "",
            f"**OOC 偏移分数**：{obj.get('ooc_score', 'N/A')} / 10",
            "",
            f"**命中数**：{len(obj.get('hits', []))}",
            "",
        ]
        for i, h in enumerate(obj.get("hits", []), 1):
            md += [
                f"## 问题 {i} — {h.get('character', '?')}",
                "",
                f"**偏移**：{h.get('deviation', '')}",
                "",
                f"**基线依据**：{h.get('prior_baseline', '')}",
                "",
                f"**建议修复**：{h.get('suggested_fix', '')}",
                "",
            ]
        bb.write_text(f"fixes/ch{chapter:03d}.char-patch.md", "\n".join(md))

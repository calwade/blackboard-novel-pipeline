"""Fixer — surgically patches the chapter based on Evaluator's top_3_fixes.

Reads:
  - state/chapters/ch{N:03d}.md
  - state/chapters/ch{N:03d}.verdict.json (top_3_fixes + hit landmines)
  - rules/writing-iron-laws.md   (19 writing iron laws — same red lines as Generator)
  - rules/writing-style-core.md  (句段词描写技法手册) + state/writing-style-extra.md

Writes (overwrites):
  - state/chapters/ch{N:03d}.md

Temperature 0.5 — conservative rewriting, preserves voice.
"""
from __future__ import annotations

import json

from ._base import BaseAgent
from ..blackboard import Blackboard


class Fixer(BaseAgent):
    name = "fixer"
    temperature = 0.5
    response_format = "text"
    max_tokens = 8000

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        chapter_path = f"chapters/ch{chapter:03d}.md"
        verdict_path = f"chapters/ch{chapter:03d}.verdict.json"

        chapter_text = bb.read_text(chapter_path)
        verdict = bb.read_json(verdict_path)
        style_core = self._read_rule("writing-style-core.md")
        style_extra = bb.read_text("writing-style-extra.md")
        writing_iron_laws = self._read_rule("writing-iron-laws.md")

        try:
            setting = bb.read_yaml("setting.yaml")
        except Exception:
            setting = {}
        prohibited_styles = setting.get("prohibited_styles", []) or []
        if prohibited_styles:
            prohibited_block = "\n".join(f"- {s}" for s in prohibited_styles)
        else:
            prohibited_block = "- （本 setting 未声明风格禁止清单）"

        inputs_read = [
            f"state/{chapter_path}",
            f"state/{verdict_path}",
            "state/writing-style-extra.md",
            "state/setting.yaml",
            "rules/writing-iron-laws.md",
            "rules/writing-style-core.md",
        ]

        # Gather hit landmines for surgical reference
        hit_issues = [
            {"landmine": k, **v}
            for k, v in verdict.get("landmines", {}).items()
            if v.get("hit")
        ]
        top_fixes = verdict.get("top_3_fixes", [])

        system = (
            "你是业内顶级改稿高手。\n"
            "\n"
            "# 风格锁定（不可逾越的基调下限）\n"
            "修改过程中**严禁跨题材串味**，以下风格任何一条都视为基调崩坏：\n"
            f"{prohibited_block}\n"
            "\n"
            "# 修改档分级（重要）\n"
            "\n"
            "修改幅度按严格分 4 档，你的默认档位是「**改写**」：\n"
            "- **润色**：只改表达、节奏、段落呼吸，不改事实与剧情结论。\n"
            "- **改写**（默认）：可改叙述顺序、画面、力度，但保留核心事实与人物动机。\n"
            "- **重写**：可重构场景推进和冲突组织；除非用户明确允许，否则不改主设定和大事件结果。\n"
            "- **续写**：只在现有文本之后向前推进，不反改前文。\n"
            "\n"
            "本次任务属于「改写」档。绝不升级到「重写」——不改大事件结果、不改主设定、不添新情节。\n"
            "\n"
            "# 另外必须遵守\n"
            "\n"
            "1. 保留原章节标题、段落结构、人物对白风格。\n"
            "2. 仅针对 top_3_fixes 列出的 where/what 以及 hit_issues 的 evidence 做精准修改。\n"
            "3. 不添加原章节没有的新情节、新人物、新场景。\n"
            "4. 修改后的章节字数与原章节相差不超过 ±15%。\n"
            "5. 输出完整的修改后章节正文（包括章节标题），不要输出任何解释、diff、总结。\n"
            "6. **定位 evidence 的根因修**，不要做纯语言润色把症状盖住。\n"
            "7. **冲突仲裁**：若 top_3_fixes 的修改方向与 `state/current_status_card.md` 冲突——\n"
            "   不改正文，向上反馈让 StatusCardUpdater 下轮更新卡（遵守 `rules/00-information-priority.md` R1）。\n"
            "   正文是 ground truth，不得反向回修过去章节。\n"
            "\n"
            "# 写作风格（你的基准，回答时别写成 AI 味）\n\n"
            "## 创作铁律（修正时不能违反——这是 Evaluator 同款红线）\n\n"
            + writing_iron_laws
            + "\n\n## 通用规范\n\n"
            + style_core
            + "\n\n## 题材特有风格（setting 注入）\n\n"
            + style_extra
        )

        user = (
            f"# 原章节全文\n\n{chapter_text}\n\n"
            f"# 必须修复的 top_3_fixes\n\n```json\n"
            f"{json.dumps(top_fixes, ensure_ascii=False, indent=2)}\n```\n\n"
            f"# 命中的雷点与证据（作为参考）\n\n```json\n"
            f"{json.dumps(hit_issues, ensure_ascii=False, indent=2)}\n```\n\n"
            f"# 任务\n\n请输出完整修订版章节正文。"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        bb.write_text(f"chapters/ch{chapter:03d}.md", raw.strip() + "\n")

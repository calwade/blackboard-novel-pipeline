"""Fixer — surgically patches the chapter based on Evaluator's top_3_fixes.

Reads:
  - state/chapters/ch{N:03d}.md
  - state/chapters/ch{N:03d}.verdict.json (top_3_fixes + hit landmines)
  - rules/writing-style.md

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
        style = self._read_rule("writing-style.md")

        inputs_read = [
            f"state/{chapter_path}",
            f"state/{verdict_path}",
            "rules/writing-style.md",
        ]

        # Gather hit landmines for surgical reference
        hit_issues = [
            {"landmine": k, **v}
            for k, v in verdict.get("landmines", {}).items()
            if v.get("hit")
        ]
        top_fixes = verdict.get("top_3_fixes", [])

        system = (
            "你是业内顶级改稿高手。你的任务：**只修，不重写**。\n"
            "你只解决传入的具体问题，其他地方一字不动。\n"
            "\n"
            "绝对铁律：\n"
            "1. 保留原章节标题、段落结构、人物对白风格。\n"
            "2. 仅针对 top_3_fixes 列出的 where/what 以及 hit_issues 的 evidence 做精准修改。\n"
            "3. 不添加原章节没有的新情节、新人物、新场景。\n"
            "4. 修改后的章节字数与原章节相差不超过 ±15%。\n"
            "5. 输出完整的修改后章节正文（包括章节标题），不要输出任何解释、diff、总结。\n"
            "\n"
            "# 写作风格（你的基准，回答时别写成 AI 味）\n\n"
            + style
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

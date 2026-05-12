"""GenreStyleGuard — writing-style & AI-slop auditor.

Responsibility (narrow):
    - writing-style-extra.md 内部矛盾
    - writing-style-extra.md 与 rules/writing-style-core.md 冲突
    - era.md / writing-style-extra.md 里的 AI 味 / 模糊词 / 批评家套话
    - 占位内容未填充（（占位 / TODO / TBD）

NOT responsible for era factual errors / iron-law consistency — those go to
GenreFactChecker / GenreConsistencyGuard.

Reads:
    - genres/<id>/writing-style-extra.md
    - rules/writing-style-core.md
    - genres/<id>/era.md (for scanning AI-slop phrases)

Writes:
    - genre_issues.jsonl (each issue tagged source="style_guard")
"""
from __future__ import annotations

import json
import re

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


SYSTEM_PROMPT = """输出语言：简体中文（JSON 键英文，值中文）。

你是题材包的**风格审稿员**（style guard）。**唯一职责**：
1. writing-style-extra.md 内部条目互相矛盾
2. writing-style-extra.md 与 rules/writing-style-core.md 通用风格冲突
3. era.md / writing-style-extra.md 里的 AI 味 / 批评家套话 / 模糊词
4. 占位未填充残留（"（占位"、"TODO"、"TBD"）

不看 era.md 的史实正确性（那是 fact_checker 的活）。
不看 iron-laws 的互相冲突（那是 consistency_guard 的活）。

审稿流程（Quote-then-claim）：
- 每条 issue 先引用原文（quote），再断言问题（message），再给建议（suggestion）。

严格输出 JSON（只输出 JSON 本体，不要围栏，不要解释）：
{
  "issues": [
    {
      "severity": "error" | "warning" | "info",
      "file": "writing-style-extra.md | era.md",
      "quote": "<原文片段，原样>",
      "message": "<问题描述，一句话>",
      "suggestion": "<可执行的修复建议>"
    }
  ]
}

AI 味典型信号（命中即报）：
- 总而言之 / 综上所述 / 不言而喻 / 毋庸置疑
- 似乎 / 大致 / 某种程度上
- 翻江倒海 / 涌起万千思绪 / 心如刀绞（陈词）
- in today's fast-paced world / at the end of the day / needless to say

硬约束：
- severity=error：必须修（如占位未填充）。
- severity=warning：AI 味 / 模糊词 / 套话。
- 若无问题：issues=[]。
- 你自己不要用这些模糊词。
"""


class GenreStyleGuard(BaseAgent):
    name = "genre_style_guard"
    temperature = 0.2
    response_format = "json"
    max_tokens = 2500

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def _build_prompts(self, bb: Blackboard, *, genre_id: str, **_):
        from src import config

        genre_dir = config.GENRES_DIR / genre_id
        blocks: list[str] = []
        inputs_read: list[str] = []

        for fname in ("writing-style-extra.md", "era.md"):
            fp = genre_dir / fname
            if fp.exists():
                text = fp.read_text(encoding="utf-8")
                blocks.append(f"<file name=\"{fname}\">\n{text[:4000]}\n</file>")
                inputs_read.append(f"genres/{genre_id}/{fname}")

        # Include rules/writing-style-core.md for cross-rule check
        core_path = config.RULES_DIR / "writing-style-core.md"
        if core_path.exists():
            core_text = core_path.read_text(encoding="utf-8")
            blocks.append(
                f"<file name=\"writing-style-core.md\">\n{core_text[:4000]}\n</file>"
            )
            inputs_read.append("rules/writing-style-core.md")

        user = (
            f"<genre id=\"{genre_id}\">\n"
            + "\n\n".join(blocks)
            + "\n</genre>\n\n"
            "<your_task>\n"
            "按系统指令只审查风格（内部 / 与 core / AI 味 / 占位残留）。\n"
            "Quote-then-claim。只输出 JSON 本体。\n"
            "</your_task>"
        )
        return SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, genre_id: str, **_):
        obj = _parse_json(raw)
        for issue in obj.get("issues", []):
            issue["genre_id"] = genre_id
            issue["source"] = "style_guard"
            bb.append_jsonl("genre_issues.jsonl", issue)


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {"issues": []}

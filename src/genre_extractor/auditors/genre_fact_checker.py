"""GenreFactChecker — focused fact-checking auditor for the genre pack.

Responsibility (narrow, Lesson-3 boundary):
    Only checks era.md for factual / historical / geographic errors.
    NOT responsible for style, iron-law conflicts, or AI-slop.

Reads:
    - genres/<id>/era.md

Writes (via blackboard):
    - genre_issues.jsonl (appended, each issue tagged source="fact_checker")

Lives in auditors/ rather than agents/ because it's one of three parallel
Validator fan-out auditors — same pattern as AISlopGuard / CharacterGuard
in src/auditors/ for the novel pipeline.
"""
from __future__ import annotations

import json
import re

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


SYSTEM_PROMPT = """输出语言：简体中文（JSON 键英文，值中文）。

你是题材包的事实核查审稿员（fact-checker）。**唯一职责**：扫描 era.md 中
的事实错误 / 时代错位 / 地名人名谬误。不评价风格，不评价 iron-laws 冲突，
不评价 AI 味——那些由其他审稿员负责。

审稿流程：
1. **Quote-then-claim**：每条 issue 先引用 era.md 的原文片段，再断言错误，
   再给出修复建议。无原文引用的 issue 无效。
2. 只看 era.md。重点关注：
   - 历史事件时间错乱（例：1983 年把香港交还事件放在 1985）
   - 地名 / 人名 / 机构名不符（例：把"油麻地"写成"油麻区"）
   - 技术 / 物件时代错位（例：1983 年描述用智能手机）
   - 文化习俗不符当时当地

严格输出 JSON（只输出 JSON 本体，不要围栏，不要解释）：
{
  "issues": [
    {
      "severity": "error" | "warning" | "info",
      "file": "era.md",
      "quote": "<原文片段，原样>",
      "message": "<事实错误描述，一句话>",
      "suggestion": "<具体可执行的修复建议>"
    }
  ]
}

硬约束：
- severity=error：明显史实错误，必须修。
- severity=warning：可疑但需人工确认。
- severity=info：提示性线索。
- 若无问题：issues=[]（不要凑数）。
- 不使用模糊词：似乎 / 大致 / 某种程度上 / 总而言之。
"""


class GenreFactChecker(BaseAgent):
    name = "genre_fact_checker"
    temperature = 0.0
    response_format = "json"
    max_tokens = 2000

    SYSTEM_PROMPT = SYSTEM_PROMPT  # exposed for import-time inspection

    def _build_prompts(self, bb: Blackboard, *, genre_id: str, **_):
        from src import config

        genre_dir = config.GENRES_DIR / genre_id
        era_path = genre_dir / "era.md"
        inputs_read: list[str] = []
        if era_path.exists():
            era_text = era_path.read_text(encoding="utf-8")
            inputs_read.append(f"genres/{genre_id}/era.md")
        else:
            era_text = "(era.md 缺失)"

        user = (
            f"<genre id=\"{genre_id}\">\n"
            f"<file name=\"era.md\">\n{era_text[:6000]}\n</file>\n"
            f"</genre>\n\n"
            "<your_task>\n"
            "按系统指令只审查 era.md 的事实正确性。Quote-then-claim。\n"
            "只输出 JSON 本体。\n"
            "</your_task>"
        )
        return SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, genre_id: str, **_):
        obj = _parse_json(raw)
        for issue in obj.get("issues", []):
            issue["genre_id"] = genre_id
            issue["source"] = "fact_checker"
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

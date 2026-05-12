"""GenreConsistencyGuard — iron-laws consistency auditor.

Responsibility (narrow):
    - iron-laws-extra.md 内部条目互相矛盾？
    - iron-laws 与 era.md 事实层面冲突？
    - resource_schema.yaml（若存在）的 baseline_scale 能否从 iron-laws + era
      推得？不可追溯即为问题。

NOT responsible for style / AI-slop / era-only factual errors — those go to
GenreStyleGuard / GenreFactChecker respectively.

Reads:
    - genres/<id>/iron-laws-extra.md
    - genres/<id>/era.md
    - genres/<id>/resource_schema.yaml (optional)

Writes (via blackboard):
    - genre_issues.jsonl (each issue tagged source="consistency_guard")
"""
from __future__ import annotations

import json
import re

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


SYSTEM_PROMPT = """输出语言：简体中文（JSON 键英文，值中文）。

你是题材包的**一致性审稿员**（consistency guard）。**唯一职责**：
1. iron-laws-extra.md 内部条目互相矛盾
2. iron-laws 与 era.md 事实冲突
3. resource_schema.yaml 的 baseline_scale 与 iron-laws + era 推不通

不看 era.md 的事实正确性（那是 fact_checker 的活）。
不看 writing-style 的风格 / AI 味（那是 style_guard 的活）。

审稿流程（Quote-then-claim）：
- 每条 issue 必须引用触发它的原文（quote），指明来自哪个文件（file）。
- 跨文件矛盾：quote 选其中一边，message 里提另一边。

严格输出 JSON（只输出 JSON 本体，不要围栏，不要解释）：
{
  "issues": [
    {
      "severity": "error" | "warning" | "info",
      "file": "iron-laws-extra.md | era.md | resource_schema.yaml",
      "quote": "<原文片段，原样>",
      "message": "<冲突描述，一句话>",
      "suggestion": "<可执行的修复建议>"
    }
  ]
}

硬约束：
- severity=error：硬冲突，必须修。
- severity=warning：潜在不一致。
- 若无问题：issues=[]。
- 不使用模糊词：似乎 / 大致 / 总而言之。
"""


class GenreConsistencyGuard(BaseAgent):
    name = "genre_consistency_guard"
    temperature = 0.0
    response_format = "json"
    max_tokens = 2500

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def _build_prompts(self, bb: Blackboard, *, genre_id: str, **_):
        from src import config

        genre_dir = config.GENRES_DIR / genre_id
        blocks: list[str] = []
        inputs_read: list[str] = []

        for fname in ("iron-laws-extra.md", "era.md"):
            fp = genre_dir / fname
            if fp.exists():
                text = fp.read_text(encoding="utf-8")
                blocks.append(f"<file name=\"{fname}\">\n{text[:4000]}\n</file>")
                inputs_read.append(f"genres/{genre_id}/{fname}")

        # resource_schema.yaml is OPTIONAL — only include if present
        rs_path = genre_dir / "resource_schema.yaml"
        if rs_path.exists():
            rs_text = rs_path.read_text(encoding="utf-8")
            blocks.append(
                f"<file name=\"resource_schema.yaml\">\n{rs_text[:3000]}\n</file>"
            )
            inputs_read.append(f"genres/{genre_id}/resource_schema.yaml")
            rs_reminder = (
                "\n注意：resource_schema.yaml 的 baseline_scale 必须能从 "
                "iron-laws-extra.md + era.md 的描述推出。若推不出，报 warning。\n"
            )
        else:
            rs_reminder = ""

        user = (
            f"<genre id=\"{genre_id}\">\n"
            + "\n\n".join(blocks)
            + "\n</genre>\n"
            + rs_reminder
            + "\n<your_task>\n"
            + "按系统指令只审查一致性（iron-laws 内部 / 与 era / 与 resource_schema）。\n"
            + "Quote-then-claim。只输出 JSON 本体。\n"
            + "</your_task>"
        )
        return SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, genre_id: str, **_):
        obj = _parse_json(raw)
        for issue in obj.get("issues", []):
            issue["genre_id"] = genre_id
            issue["source"] = "consistency_guard"
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

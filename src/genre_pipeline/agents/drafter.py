"""GenreDrafter - two-step: blueprint synthesis + file rendering.

Step A (this class): reads merged notes, writes genre_blueprint.yaml.
Step B is a deterministic renderer (src/genre_pipeline/pipeline.py) that
reads blueprint and writes the 5 final files. Step B does NOT call LLM.
"""
from __future__ import annotations

import json
import re

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


class GenreDrafter(BaseAgent):
    name = "genre_drafter_blueprint"
    temperature = 0.4
    response_format = "json"
    max_tokens = 6000

    SYSTEM_PROMPT = (
        "你是一位题材架构师。任务：把一堆零散的拆解笔记（extraction notes）合成一份题材蓝图（blueprint）。\n"
        "\n"
        "Blueprint 的 schema 和 extraction note 一致，但：\n"
        "- 去重同类候选（同一 iron_law 被多次观察到的合并）\n"
        "- 保留 recurrence_count 总和\n"
        "- 丢弃 confidence=low 且 recurrence_count=1 的孤证\n"
        "- open_questions 原样保留\n"
        "\n"
        "禁止引入笔记里没有的新事实。禁止模糊词。\n"
    )

    def _build_prompts(self, bb: Blackboard, **_):
        inputs_read: list[str] = []
        blueprint = {}
        if bb.exists("genre_blueprint.yaml"):
            blueprint = bb.read_yaml("genre_blueprint.yaml")
            inputs_read.append("genre_blueprint.yaml")

        merged = ""
        if bb.exists("extraction_notes/latest_merged.yaml"):
            merged = bb.read_text("extraction_notes/latest_merged.yaml")
            inputs_read.append("extraction_notes/latest_merged.yaml")

        user = (
            f"# 当前 blueprint（可能为空）\n\n"
            f"{json.dumps(blueprint, ensure_ascii=False, indent=2)}\n\n"
            f"# 已合并笔记\n\n"
            f"{merged or '(无)'}\n\n"
            f"# 任务\n\n"
            f"输出一份合成后的 blueprint YAML（严格 JSON，字段同 extraction note）。"
        )
        return self.SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, **_):
        obj = _parse_json(raw)
        bb.write_yaml("genre_blueprint.yaml", obj)


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)

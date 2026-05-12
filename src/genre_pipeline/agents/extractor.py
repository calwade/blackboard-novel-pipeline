"""GenreExtractor - slide-window extractor for reverse-engineering a genre.

Reads one batch of chapters from a source novel + previous merged notes +
few-shot headers from existing genre packs, writes one extraction note YAML.

Placeholder prompt in v1: structure demonstrates the schema; production-grade
prompt tuning deferred.
"""
from __future__ import annotations

import json
import re

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


class GenreExtractor(BaseAgent):
    name = "genre_extractor"
    temperature = 0.3
    response_format = "json"
    max_tokens = 4000

    SYSTEM_PROMPT = (
        "你是一位题材规律拆解专家，任务是从一批小说章节中提炼 4 个维度的题材规律：\n"
        "1. 时代/世界观事实 (era_observations)\n"
        "2. 反复出现的铁律模式 (iron_law_candidates)\n"
        "3. 语言 / 节奏 / 风格特征 (style_markers)\n"
        "4. 可追踪资源候选 (resource_candidates)\n"
        "\n"
        "严格按照给定 JSON schema 输出。每条发现必须带 evidence_chapters 字段。\n"
        "禁止使用模糊词：暴涨 / 海量 / 似乎 / 大致 / 整体而言 / 某种程度上。\n"
        "不确定的放到 open_questions，不要硬编。\n"
    )

    def _build_prompts(self, bb: Blackboard, *, batch_id: int, batch_text: str, **_):
        inputs_read: list[str] = []

        # Optional: merged notes from prior batches (Lesson 3 Context Reset)
        merged_snippet = ""
        if bb.exists("extraction_notes/latest_merged.yaml"):
            merged_snippet = bb.read_text("extraction_notes/latest_merged.yaml")[:2000]
            inputs_read.append("extraction_notes/latest_merged.yaml")

        user = (
            f"# 本批章节（batch_id={batch_id}）\n\n"
            f"{batch_text}\n\n"
            f"# 上一版已合并笔记（参考，可增量）\n\n"
            f"{merged_snippet or '(首批，无前置笔记)'}\n\n"
            f"# 输出要求\n\n"
            f"输出严格 JSON，key 顺序与 schema 一致："
            f"batch_id, chapters_covered, novel_source, extracted_at, "
            f"era_observations, iron_law_candidates, style_markers, "
            f"resource_candidates, open_questions。"
        )
        return self.SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, batch_id: int, **_):
        obj = _parse_json(raw)
        bb.write_yaml(f"extraction_notes/batch-{batch_id:03d}.yaml", obj)


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)

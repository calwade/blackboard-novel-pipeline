"""GenreBookDistiller —— 第三级合并（arc → book-level latest_merged）。

Problem: 当小说特别长（>600 章）导致 arc 数量 >= 4 时，用一次 LLM 把所有
arc 合起来可能依然吃满上下文 + 合成质量下降。此层是最外一级压缩，把
所有 arc 蒸馏成最终的 latest_merged.yaml（供 Drafter 读取的单一合并产物）。

流程：读所有 extraction_notes/arcs/arc-*.yaml → 1 个 latest_merged.yaml：
  - 最严格的同类项合并 + 去重
  - 同一条 iron_law 跨 arc 出现 → recurrence_count 相加
  - 丢弃低置信度孤证
  - 保留原样 open_questions

输出 schema 同 extraction note，额外字段：
  - distilled_from_arcs: [arc_id, ...]

Lesson 3 边界：只读 arc 产物，不读原始 batch 或正文。
"""
from __future__ import annotations

import json
import re

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


SYSTEM_PROMPT = """输出语言：简体中文（JSON 键英文，值中文）。

你是一位题材规律蒸馏员（第三级：arc → book-level 最终合并）。输入是若干
arc 级笔记；你的唯一任务是把它们蒸馏为 **一份最终的 latest_merged 笔记**，
供 Drafter 生成题材蓝图。

蒸馏硬规则（违反即拒稿）：
1. **只合并、不创造**：输出里每一条都必须能回溯到某个 arc 笔记里的同类条目；
   arcs 里没出现的规律，绝对不新增。
2. **跨 arc 合并同类**：一条铁律若在多个 arc 里反复出现（summary 语义相近），
   合成一条：
   - summary 取最精炼版
   - evidence_chapters 并集
   - recurrence_count = 各 arc 的 recurrence_count 之和
   - confidence 取最高（high > medium > low）
3. **最严格的质量过滤**：
   - confidence=low 且 recurrence_count 总和 ≤ 2 → 移到 open_questions
   - confidence=medium 且只在 1 个 arc 出现 → 保留但标 confidence=low
4. **open_questions**：所有 arc 的问题取并集去重，不要自己新造问题。
5. 不使用模糊词：暴涨 / 海量 / 似乎 / 大致 / 整体而言 / 某种程度上。
6. 只输出 JSON 本体，不要 ```json 围栏，不要 preamble。

必填字段：
  distilled_from_arcs, batch_id ("book-distilled"), chapters_covered,
  novel_source ("merged"), extracted_at,
  era_observations, iron_law_candidates, style_markers,
  resource_candidates, open_questions

每条数组元素至少含：
  summary, evidence_chapters, evidence_quotes, confidence, recurrence_count
"""


class GenreBookDistiller(BaseAgent):
    """Third-level distiller: combine all arc notes into latest_merged.yaml."""

    name = "genre_book_distiller"
    temperature = 0.2
    response_format = "json"
    max_tokens = 8000

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def _build_prompts(
        self, bb: Blackboard, *, arc_ids: list[int] | None = None, **_
    ):
        inputs_read: list[str] = []
        arcs_content: list[str] = []

        # If arc_ids not specified, auto-discover from the arcs/ directory.
        if arc_ids is None:
            arc_files = bb.list_files("extraction_notes/arcs", "arc-*.yaml")
            arc_ids = []
            for p in arc_files:
                # arc-NNN.yaml → NNN
                m = re.match(r"arc-(\d+)\.yaml$", p.name)
                if m:
                    arc_ids.append(int(m.group(1)))

        for aid in sorted(arc_ids):
            path = f"extraction_notes/arcs/arc-{aid:03d}.yaml"
            if bb.exists(path):
                arcs_content.append(
                    f"### arc-{aid:03d}.yaml\n"
                    + bb.read_text(path)
                )
                inputs_read.append(path)

        joined_arcs = "\n\n".join(arcs_content) or "（无 arc 输入）"

        user = (
            f"<distilled_from_arcs>{arc_ids}</distilled_from_arcs>\n\n"
            f"<arcs>\n{joined_arcs}\n</arcs>\n\n"
            f"<your_task>\n"
            f"把 <arcs> 中的 {len(arc_ids)} 份 arc 笔记蒸馏为一份最终 latest_merged 笔记。\n"
            f"- distilled_from_arcs 必须为 {arc_ids}\n"
            f"- 按系统规则做跨 arc 同类项合并 + 严格质量过滤\n"
            f"- 任何新增事实都不允许（只能来自 arc 里已有条目）\n"
            f"只输出 JSON 本体。\n"
            f"</your_task>"
        )
        return SYSTEM_PROMPT, user, inputs_read

    def _handle_output(
        self, bb: Blackboard, raw: str, *, arc_ids: list[int] | None = None, **_
    ) -> None:
        obj = _parse_json(raw)
        # Enforce required field even if LLM forgot
        if arc_ids is not None:
            obj.setdefault("distilled_from_arcs", list(arc_ids))
        bb.write_yaml("extraction_notes/latest_merged.yaml", obj)


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)

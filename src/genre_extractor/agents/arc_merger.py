"""GenreArcMerger —— 第二级合并（batch → arc）。

Problem: 当小说超长（400-1000+ 章），一次把所有 batch-NNN.yaml 丢给 LLM
做 merge 会吃满上下文、质量下降。复用 `src/agents/multi_level_summarizer.py`
的三级思想（batch → arc → book），本文件是中间那层。

流程：每 ARC_BATCH_COUNT 个 batch 合并为 1 个 arc-NN.yaml：
  - 去重同类 iron_law_candidates（按 statement 语义），合并 recurrence_count
  - 保留 confidence ≥ medium；丢弃 low + recurrence=1
  - **不引入新规律**（只做合并）

输出 schema 同 extraction note，额外字段：
  - arc_id: int
  - covered_batches: [int, ...]

Lesson 3：这一层也只读它要合并的 batch + 上一版 arc（可选参考），
不读源章节正文、不读 validator/draft/issues，避免 framing 泄漏。
"""
from __future__ import annotations

import json
import re

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


# Each arc summarizes ARC_BATCH_COUNT consecutive batches.
# 4 is chosen so mid-length novels (16 batches) naturally fan out to 4 arcs,
# matching multi_level_summarizer's (VOLUME_SIZE // ARC_SIZE = 4) rhythm.
ARC_BATCH_COUNT = 4


SYSTEM_PROMPT = """输出语言：简体中文（JSON 键英文，值中文）。

你是一位题材规律合并员（第二级：batch → arc）。输入是若干连续 batch
的提取笔记；你的唯一任务是把它们合并为 **一个 arc 级别的笔记**。

合并硬规则（违反即拒稿）：
1. **只合并、不创造**：arc 里的每一条都必须能回溯到某个 batch 里的同类条目；
   batches 里没出现过的规律，绝对不新增。
2. **合并同类 iron_law**：若多个 batch 的 iron_law_candidates 指向同一条
   规律（summary 语义相近），合成一条：
   - summary 取更精炼的版本
   - evidence_chapters 并集
   - evidence_quotes 并集（去重）
   - recurrence_count = 各 batch 的 recurrence_count 之和
   - confidence 取最高（high > medium > low）
3. **质量过滤**：confidence=low 且 recurrence_count=1 的条目丢进 open_questions，
   不进 iron_law_candidates / era_observations 正表。
4. **era_observations / style_markers / resource_candidates 同样用规则 2 合并**。
5. **open_questions** 原样保留各 batch 的问题（去重），不要自己新造问题。
6. 不使用模糊词：暴涨 / 海量 / 似乎 / 大致 / 整体而言 / 某种程度上。
7. 只输出 JSON 本体，不要 ```json 围栏，不要 preamble。

必填字段：
  arc_id, covered_batches, batch_id ("arc-NNN"), chapters_covered,
  novel_source ("merged"), extracted_at,
  era_observations, iron_law_candidates, style_markers,
  resource_candidates, open_questions

每条数组元素至少含：
  summary, evidence_chapters, evidence_quotes, confidence, recurrence_count
"""


class GenreArcMerger(BaseAgent):
    """Second-level merger: combine ARC_BATCH_COUNT batches into one arc note."""

    name = "genre_arc_merger"
    temperature = 0.2
    response_format = "json"
    max_tokens = 6000

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def _build_prompts(
        self, bb: Blackboard, *, arc_id: int, batch_ids: list[int], **_
    ):
        inputs_read: list[str] = []
        batches_content: list[str] = []
        for bid in batch_ids:
            path = f"extraction_notes/batch-{bid:03d}.yaml"
            if bb.exists(path):
                batches_content.append(
                    f"### batch-{bid:03d}.yaml\n"
                    + bb.read_text(path)
                )
                inputs_read.append(path)

        # Optional: previous arc as context (dedup reference only, do not merge in)
        prev_arc_snippet = ""
        prev_arc_id = arc_id - 1
        if prev_arc_id >= 1:
            prev_path = f"extraction_notes/arcs/arc-{prev_arc_id:03d}.yaml"
            if bb.exists(prev_path):
                prev_arc_snippet = bb.read_text(prev_path)[:3000]
                inputs_read.append(prev_path)

        joined_batches = "\n\n".join(batches_content) or "（无 batch 输入）"

        user = (
            f"<arc_id>{arc_id}</arc_id>\n"
            f"<covered_batches>{batch_ids}</covered_batches>\n\n"
            f"<batches>\n{joined_batches}\n</batches>\n\n"
            f"<previous_arc>\n"
            f"{prev_arc_snippet or '（无前置 arc，不参考）'}\n"
            f"</previous_arc>\n\n"
            f"<your_task>\n"
            f"把 <batches> 中的 {len(batch_ids)} 份 batch 笔记合并为一份 arc-{arc_id:03d} 笔记。\n"
            f"- arc_id 必须为 {arc_id}\n"
            f"- covered_batches 必须为 {batch_ids}\n"
            f"- 按系统规则合并同类项；confidence=low + recurrence=1 移到 open_questions\n"
            f"- <previous_arc> 仅作为去重参考，不要把它的条目并进本 arc\n"
            f"只输出 JSON 本体。\n"
            f"</your_task>"
        )
        return SYSTEM_PROMPT, user, inputs_read

    def _handle_output(
        self, bb: Blackboard, raw: str, *, arc_id: int, batch_ids: list[int], **_
    ) -> None:
        obj = _parse_json(raw)
        # Enforce required fields even if LLM forgot
        obj.setdefault("arc_id", arc_id)
        obj.setdefault("covered_batches", list(batch_ids))
        bb.write_yaml(f"extraction_notes/arcs/arc-{arc_id:03d}.yaml", obj)


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)

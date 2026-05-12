"""GenreExtractor - slide-window extractor for reverse-engineering a genre.

Two-step extraction (inspired by DSPy TwoStepAdapter + Chain-of-Density):

  Step 1 (free-form notes, temp ~0.3, text): produce semi-structured
          Markdown-like notes inside <observations> / <evidence_excerpts> /
          <candidate_rules> tags. Encourages the model to think, quote
          evidence, and flag uncertainty.

  Step 2 (verbatim extraction, temp 0.0, JSON): the step-1 output is
          quoted back into the user prompt and the model is instructed
          to transcribe it into the strict extraction-note schema
          without inventing new facts.

This separates *discovery* (creative, slightly random) from *formatting*
(deterministic, schema-bound) — a pattern known to drastically reduce
both JSON-schema errors and hallucinated rules.

The 4 extraction dimensions:
  1. 时代/世界观事实 (era_observations)
  2. 反复出现的铁律模式 (iron_law_candidates)
  3. 语言 / 节奏 / 风格特征 (style_markers)
  4. 可追踪资源候选 (resource_candidates)
"""
from __future__ import annotations

import json
import re

from src import llm
from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


# -----------------------------------------------------------------------------
# Step 1 — Free-form observation notes
# -----------------------------------------------------------------------------
STEP1_SYSTEM_PROMPT = """输出语言：简体中文。

你是一位小说题材规律拆解的研究员（community analyst & linguistic ethnographer）。
你要从一小批连续章节（一个 batch）里产出「研究笔记」，供下游严格提取使用。

核心态度：
- 诚实胜过完整。宁可写「本批未见」，也不要凭想象补全。
- 引用胜过概括。每条规律候选必须能指回一句原文。
- 增量胜过重复。若上一版已合并笔记里已覆盖某条，不要重复写；本批只写新发现或强化证据。

输出格式（严格使用以下 XML 标签分区，不要加 markdown 围栏）：

<observations>
（每行一条对本批整体的中性观察：时代、场景、氛围、人物行为模式。不要评价。）
</observations>

<evidence_excerpts>
（逐条列出你想引用的原文片段，格式：
  - "原文 2-3 句" ← 章节X
 保持引号与章节序号。若某条候选无法找到原文证据，就不要写它。）
</evidence_excerpts>

<candidate_rules>
（每条一行，四个维度之一打头：
  [era] / [iron_law] / [style] / [resource]
 后跟一句当前批次抽出来的规律候选。
 置信度自评打尾：confidence=high|medium|low。）
</candidate_rules>

<open_questions>
（写下本批你没法确定的事——这些会留给人工审稿。诚实就有分。）
</open_questions>

硬约束：
- 每个候选必须有原文支撑；没证据就移到 open_questions。
- 不使用模糊词：暴涨 / 海量 / 似乎 / 大致 / 整体而言 / 某种程度上。
- 不编造未出现在本批文本里的人物、地名、数字。
- 主角姓名一律脱敏为「主角」二字，描述模式而非复述剧情。
"""


# -----------------------------------------------------------------------------
# Step 2 — Verbatim schema transcription
# -----------------------------------------------------------------------------
STEP2_SYSTEM_PROMPT = """输出语言：简体中文（JSON 键英文，值中文）。

你是一位严格的 schema 抄录员。输入是一份前一步产生的研究笔记（用 XML 标签分区）。
你的唯一任务：把笔记里已经明说的内容抄录为严格 JSON 格式，**不要新增任何笔记里没有的事实**。

输出键顺序必须是：
  batch_id, chapters_covered, novel_source, extracted_at,
  era_observations, iron_law_candidates, style_markers,
  resource_candidates, open_questions

四个候选数组里的每条元素至少包含：
  {
    "summary": "...",
    "evidence_chapters": [int, ...],
    "evidence_quotes": ["...", ...],
    "confidence": "high|medium|low",
    "recurrence_count": int
  }

硬约束（违反即拒稿重跑）：
1. 笔记里若某维度为空，对应数组输出 []，不要补内容。
2. evidence_quotes 必须从 <evidence_excerpts> 里摘录的原文，引号保留。
3. 如果笔记里某条规律没有证据行，把它挪到 open_questions。
4. 不使用模糊词：暴涨 / 海量 / 似乎 / 大致 / 整体而言 / 某种程度上。
5. 只输出 JSON 本体，不要 ```json 围栏，不要解释。

完成后自检：
- 输出是合法 JSON 吗？
- 每条 iron_law_candidates / era_observations 元素都带 evidence_chapters 吗？
- 有没有新增笔记里没提过的人物/事件？（若有，删掉。）
"""


class GenreExtractor(BaseAgent):
    name = "genre_extractor"
    temperature = 0.3  # nominal; actual temps are per-step in run()
    response_format = "json"
    max_tokens = 4000

    # Kept for backward-compat imports; the single-prompt version is no longer
    # used by run() but _build_prompts still returns a reasonable pair for
    # tests that exercise the method directly without invoking LLM.
    SYSTEM_PROMPT = STEP1_SYSTEM_PROMPT

    # -------------------------------------------------------------------------
    # Legacy _build_prompts — returns a *combined* prompt used only when
    # somebody calls run() via BaseAgent's default (which we override below).
    # Test `test_extractor_build_prompts` calls this method directly and only
    # checks that `batch_text` shows up in the user prompt.
    # -------------------------------------------------------------------------
    def _build_prompts(self, bb: Blackboard, *, batch_id: int, batch_text: str, **_):
        system, user, inputs_read = self._build_step1_prompts(
            bb, batch_id=batch_id, batch_text=batch_text
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, batch_id: int, **_):
        obj = _parse_json(raw)
        bb.write_yaml(f"extraction_notes/batch-{batch_id:03d}.yaml", obj)

    # -------------------------------------------------------------------------
    # Two-step run — overrides BaseAgent.run
    # -------------------------------------------------------------------------
    def run(self, bb: Blackboard, **kwargs) -> str:
        batch_id: int = kwargs["batch_id"]
        batch_text: str = kwargs["batch_text"]

        # ---- Step 1: free-form notes (text, temp ~0.3) ----
        s1_system, s1_user, s1_inputs = self._build_step1_prompts(
            bb, batch_id=batch_id, batch_text=batch_text
        )
        free_notes = llm.chat(
            system=s1_system,
            user=s1_user,
            agent_name=self.name,
            temperature=0.3,
            max_tokens=self.max_tokens,
            response_format="text",
            inputs_read=s1_inputs,
        )

        # ---- Step 2: verbatim JSON transcription (json, temp 0.0) ----
        s2_system, s2_user, s2_inputs = self._build_step2_prompts(
            bb, batch_id=batch_id, free_notes=free_notes
        )
        raw_json = llm.chat(
            system=s2_system,
            user=s2_user,
            agent_name=self.name,
            temperature=0.0,
            max_tokens=self.max_tokens,
            response_format="json",
            inputs_read=s2_inputs,
        )

        self._handle_output(bb, raw_json, batch_id=batch_id)
        return raw_json

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _build_step1_prompts(self, bb: Blackboard, *, batch_id: int, batch_text: str):
        inputs_read: list[str] = []

        merged_snippet = ""
        if bb.exists("extraction_notes/latest_merged.yaml"):
            merged_snippet = bb.read_text("extraction_notes/latest_merged.yaml")[:2000]
            inputs_read.append("extraction_notes/latest_merged.yaml")

        user = (
            f"<batch id=\"{batch_id}\">\n"
            f"{batch_text}\n"
            f"</batch>\n\n"
            f"<previous_merged_notes>\n"
            f"{merged_snippet or '（首批，无前置笔记）'}\n"
            f"</previous_merged_notes>\n\n"
            f"<your_task>\n"
            f"阅读上方 <batch> 中的本批 {batch_id} 号章节，按系统指令输出四段 XML："
            f"<observations> / <evidence_excerpts> / <candidate_rules> / <open_questions>。\n"
            f"如果 <previous_merged_notes> 已覆盖的结论本批没有新证据，不要重复写。\n"
            f"</your_task>"
        )
        return STEP1_SYSTEM_PROMPT, user, inputs_read

    def _build_step2_prompts(self, bb: Blackboard, *, batch_id: int, free_notes: str):
        inputs_read: list[str] = ["(step1-free-notes-inline)"]

        # Schema skeleton as both a contract and an anti-schema reference.
        schema_block = json.dumps(
            {
                "batch_id": batch_id,
                "chapters_covered": ["<int ...>"],
                "novel_source": "<string>",
                "extracted_at": "<ISO date>",
                "era_observations": [
                    {
                        "summary": "<string>",
                        "evidence_chapters": ["<int>"],
                        "evidence_quotes": ["<string>"],
                        "confidence": "high|medium|low",
                        "recurrence_count": 1,
                    }
                ],
                "iron_law_candidates": [],
                "style_markers": [],
                "resource_candidates": [],
                "open_questions": ["<string>"],
            },
            ensure_ascii=False,
            indent=2,
        )

        user = (
            f"<step1_free_notes>\n"
            f"{free_notes}\n"
            f"</step1_free_notes>\n\n"
            f"<schema>\n"
            f"{schema_block}\n"
            f"</schema>\n\n"
            f"<your_task>\n"
            f"把 <step1_free_notes> 里的内容 verbatim 抄录为 <schema> 规定的严格 JSON。\n"
            f"- batch_id 必须为 {batch_id}。\n"
            f"- 数组长度 = 笔记中 <candidate_rules> 的条数（按维度分类）。\n"
            f"- 只从 <evidence_excerpts> 获取 evidence_quotes，不要新造引文。\n"
            f"- 输出前自检：所有元素都含 evidence_chapters 吗？有没有笔记里没出现的内容？\n"
            f"只输出 JSON 本体，不要加任何解释或 markdown 围栏。\n"
            f"</your_task>"
        )
        return STEP2_SYSTEM_PROMPT, user, inputs_read


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)

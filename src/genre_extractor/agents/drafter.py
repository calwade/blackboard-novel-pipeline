"""GenreDrafter - two-step: blueprint synthesis + file rendering.

Step A (this class): reads merged extraction notes, writes genre_blueprint.yaml.
Step B is a deterministic renderer (src/genre_extractor/pipeline.py) that
reads blueprint and writes the 5 final files. Step B does NOT call LLM.

Optional Chain-of-Density (CoD) 3-pass mode (librarian ★★★ #3):
  pass 1 — entity-sparse (最显然的 6–8 条)
  pass 2 — 补 3–5 条 missing，不动已有
  pass 3 — 压缩去重

Default is a single pass for speed + test stability. Enable via
  GenreDrafter().run(bb, cod_passes=3)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src import llm
from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


# -----------------------------------------------------------------------------
# Load deny phrase list once (inlined into system prompt)
# -----------------------------------------------------------------------------
def _read_deny_phrases() -> list[str]:
    from src import config

    out: list[str] = []
    for fname in ("deny-phrases-zh.txt", "deny-phrases-en.txt"):
        p = Path(config.RULES_DIR) / fname
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
    return out


def _deny_block() -> str:
    phrases = _read_deny_phrases()
    if not phrases:
        return "（deny 清单文件缺失，跳过内联）"
    # Only inline up to 40 to keep prompt tight
    head = phrases[:40]
    return "\n".join(f"- {p}" for p in head)


# -----------------------------------------------------------------------------
# System prompts
# -----------------------------------------------------------------------------
def _system_prompt_base() -> str:
    deny = _deny_block()
    return f"""输出语言：简体中文（JSON 键英文，值中文）。

你是一位题材架构师。任务：把若干零散的拆解笔记（extraction notes）合成为一份
精炼、去重、可执行的题材蓝图（blueprint）。

合成原则：
1. **只做合并，不做创造**。Blueprint 里的每一条都必须能回溯到笔记里的某条
   证据；笔记里没有的事实，绝不新增。
2. **合并同类项**。若多条笔记都指向同一条 iron_law，合成一条，把
   recurrence_count 加总，evidence_chapters 取并集。
3. **丢弃孤证**：confidence=low 且 recurrence_count=1 的候选直接剔除，
   挪到 open_questions。
4. **原样保留** open_questions（人工审稿用）。
5. **不使用模糊词**（见下方禁用清单）。

Blueprint schema 和 extraction note 一致：
  batch_id (可设 "merged"), chapters_covered, novel_source ("merged"),
  extracted_at, era_observations, iron_law_candidates, style_markers,
  resource_candidates, open_questions

每条数组元素至少含：
  summary, evidence_chapters, evidence_quotes (可为 []),
  confidence, recurrence_count

禁用短语清单（命中即视为不合格，重写）：
{deny}

硬约束：
- 只输出 JSON 本体，不要 ```json 围栏，不要 preamble 或总结。
- 输出前自检：有没有"合成"出笔记里没出现的地名 / 人物 / 数字？若有，删掉。
"""


# Precomputed system prompt at import time. Safe because deny files are
# immutable at runtime. (If they ever need hot-reload, swap to property.)
_SYSTEM_PROMPT = _system_prompt_base()


# -----------------------------------------------------------------------------
# Pass-specific user tail templates (CoD three-pass)
# -----------------------------------------------------------------------------
_PASS1_TAIL = (
    "\n\n<your_task pass=\"1/3\">\n"
    "执行 Chain-of-Density 第 1 步：entity-sparse draft。\n"
    "只输出 6–8 条最显然、最被笔记反复引用的 iron_law / era_observation。\n"
    "style_markers 选 3–5 条最鲜明；resource_candidates 保留全部（如有）。\n"
    "置信度 high 的优先；low 的先入 open_questions。\n"
    "只输出 JSON 本体。\n"
    "</your_task>"
)

_PASS2_TAIL = (
    "\n\n<your_task pass=\"2/3\">\n"
    "执行 Chain-of-Density 第 2 步：entity-dense pass。\n"
    "保留 <previous_draft> 中所有已有条目（不要删，不要改写），\n"
    "只补入 3–5 条被第 1 步遗漏但在 <merged_notes> 有证据的新条目。\n"
    "新增条目也必须有 evidence_chapters + evidence_quotes。\n"
    "只输出 JSON 本体。\n"
    "</your_task>"
)

_PASS3_TAIL = (
    "\n\n<your_task pass=\"3/3\">\n"
    "执行 Chain-of-Density 第 3 步：压缩去重。\n"
    "在 <previous_draft> 基础上：\n"
    "- 合并描述雷同的 iron_law（summary 近似的）\n"
    "- 把 confidence=low + recurrence_count=1 的条目移到 open_questions\n"
    "- 不要新增任何条目\n"
    "只输出 JSON 本体。\n"
    "</your_task>"
)

_SINGLE_PASS_TAIL = (
    "\n\n<your_task>\n"
    "合并 <merged_notes> 中的笔记为一份 blueprint JSON。\n"
    "按系统指令的 5 条合成原则操作，只输出 JSON 本体。\n"
    "</your_task>"
)


class GenreDrafter(BaseAgent):
    name = "genre_drafter_blueprint"
    temperature = 0.4
    response_format = "json"
    max_tokens = 6000

    # Class-level system prompt (frozen at import time from deny-phrase files)
    SYSTEM_PROMPT = _SYSTEM_PROMPT

    # -------------------------------------------------------------------------
    # _build_prompts — single-pass default (backward-compat)
    # -------------------------------------------------------------------------
    def _build_prompts(self, bb: Blackboard, **_):
        system, user, inputs_read = self._build_single_pass_prompts(bb)
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, **_):
        obj = _parse_json(raw)
        bb.write_yaml("genre_blueprint.yaml", obj)

    # -------------------------------------------------------------------------
    # run() — optional CoD 3-pass via kwarg cod_passes
    # -------------------------------------------------------------------------
    def run(self, bb: Blackboard, **kwargs) -> str:
        cod_passes: int = int(kwargs.pop("cod_passes", 1))
        if cod_passes <= 1:
            return super().run(bb, **kwargs)

        # --- CoD 3-pass ---
        system = _SYSTEM_PROMPT
        base_user, inputs_read = self._user_body(bb)

        # Pass 1: entity-sparse
        draft1 = llm.chat(
            system=system,
            user=base_user + _PASS1_TAIL,
            agent_name=self.name,
            temperature=0.4,
            max_tokens=self.max_tokens,
            response_format="json",
            inputs_read=inputs_read,
        )

        # Pass 2: entity-dense (carries previous draft)
        pass2_user = (
            base_user
            + f"\n\n<previous_draft>\n{draft1}\n</previous_draft>"
            + _PASS2_TAIL
        )
        draft2 = llm.chat(
            system=system,
            user=pass2_user,
            agent_name=self.name,
            temperature=0.3,
            max_tokens=self.max_tokens,
            response_format="json",
            inputs_read=inputs_read + ["(cod-pass1-inline)"],
        )

        # Pass 3: compression
        pass3_user = (
            base_user
            + f"\n\n<previous_draft>\n{draft2}\n</previous_draft>"
            + _PASS3_TAIL
        )
        final = llm.chat(
            system=system,
            user=pass3_user,
            agent_name=self.name,
            temperature=0.1,
            max_tokens=self.max_tokens,
            response_format="json",
            inputs_read=inputs_read + ["(cod-pass2-inline)"],
        )

        self._handle_output(bb, final)
        return final

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _user_body(self, bb: Blackboard) -> tuple[str, list[str]]:
        """Build the shared XML-tagged user body (no task-tail)."""
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
            f"<current_blueprint>\n"
            f"{json.dumps(blueprint, ensure_ascii=False, indent=2)}\n"
            f"</current_blueprint>\n\n"
            f"<merged_notes>\n"
            f"{merged or '（无）'}\n"
            f"</merged_notes>"
        )
        return user, inputs_read

    def _build_single_pass_prompts(self, bb: Blackboard):
        base_user, inputs_read = self._user_body(bb)
        return _SYSTEM_PROMPT, base_user + _SINGLE_PASS_TAIL, inputs_read


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)

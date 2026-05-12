"""OutlineDrafter — turn a free-text synopsis into a structured outline.json.

Single LLM call. Returns a dict with schema:
  {
    "title": str,
    "chapters": [
      {"index": int, "title": str, "beats": [str, ...]},
      ...
    ]
  }

Fall back to a blank shell if the model misbehaves — the user can always
re-run later via POST /api/projects/<id>/draft-outline.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from src import llm

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一位资深中文小说责编。用户会给你一段"故事梗概"自由文本，请你输出严格的 JSON 章节大纲。

输出 JSON schema（必须严格遵守）：
{
  "title": "<小说标题>",
  "chapters": [
    {"index": 1, "title": "<章节标题>", "beats": ["<节拍 1>", "<节拍 2>"]},
    ...
  ]
}

规则：
1. 只输出 JSON，不要包含 markdown 代码块，不要额外注释。
2. chapters 数量 = 用户指定的 chapter_count_target。
3. 每章至少 2 个 beats，最多 5 个。
4. 若用户给的梗概信息太少，自行合理推演一个完整的章节弧。
"""


class OutlineDrafter:
    """Wraps a single LLM call."""

    def run(self, *, synopsis: str, chapter_count_target: int, display_name: str) -> dict:
        if not synopsis or not synopsis.strip():
            return {"title": display_name, "chapters": []}

        user = (
            f"小说标题：{display_name}\n"
            f"目标章数：{chapter_count_target}\n\n"
            f"故事梗概：\n{synopsis}\n"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        try:
            resp = llm.chat(messages, temperature=0.4)
            raw = resp.get("content") or ""
            # strip accidental markdown fences
            if raw.startswith("```"):
                raw = raw.strip("`").partition("\n")[2].rpartition("```")[0]
            data = json.loads(raw)
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("OutlineDrafter bad JSON, returning shell: %s", exc)
            return {"title": display_name, "chapters": []}

        if not isinstance(data, dict) or "chapters" not in data:
            return {"title": display_name, "chapters": []}

        # Truncate / pad to match target
        chapters = data.get("chapters", [])[:chapter_count_target]
        for i, ch in enumerate(chapters, start=1):
            ch["index"] = i
        return {"title": data.get("title") or display_name, "chapters": chapters}

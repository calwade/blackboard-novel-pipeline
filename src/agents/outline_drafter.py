"""OutlineDrafter — turn a free-text synopsis into a structured outline.json.

Single LLM call. Returns a dict with schema:
  {
    "title": str,
    "chapters": [
      {"ch": int, "title": str, "beats": [str, ...]},
      ...
    ]
  }

注意：字段名必须是 `ch`（不是 `index`），与 Planner/Packaging 消费契约保持一致
（Planner 用 `c["ch"] == chapter` 查找当前章节；Packaging 用 `c.get('ch','?')`）。
如果模型返回 `index`，这里会兼容转换并删掉 `index`。

Fall back to a blank shell if the model misbehaves — the user can always
re-run later via POST /api/projects/<id>/draft-outline.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from src import llm

log = logging.getLogger(__name__)


def _blank_chapters(n: int) -> list[dict]:
    """Return N empty chapter shells (mirrors src.bootstrap._blank_chapters).

    Planner 按 `ch` 字段查找当前章节条目；chapters=[] 会让第 1 章直接崩。
    drafter 输出不可用时（空 synopsis / JSON 解析失败 / 形状不对）用这个
    兜底，让流水线能继续跑，Planner 依赖 status_card + pending_hooks +
    前情摘要即兴写。
    """
    if n <= 0:
        return []
    return [
        {"ch": i, "title": f"第 {i} 章", "beats": []}
        for i in range(1, n + 1)
    ]


SYSTEM_PROMPT = """\
你是一位资深中文小说责编。用户会给你一段"故事梗概"自由文本，请你输出严格的 JSON 章节大纲。

输出 JSON schema（必须严格遵守）：
{
  "title": "<小说标题>",
  "chapters": [
    {"ch": 1, "title": "<章节标题>", "beats": ["<节拍 1>", "<节拍 2>"]},
    ...
  ]
}

规则：
1. 只输出 JSON，不要包含 markdown 代码块，不要额外注释。
2. 章节序号字段名必须是 `ch`（整数，从 1 开始递增），不要用 `index` / `number` / `id`。
3. chapters 数量 = 用户指定的 chapter_count_target。
4. 每章至少 2 个 beats，最多 5 个。
5. 若用户给的梗概信息太少，自行合理推演一个完整的章节弧。
"""


class OutlineDrafter:
    """Wraps a single LLM call."""

    def run(self, *, synopsis: str, chapter_count_target: int, display_name: str) -> dict:
        if not synopsis or not synopsis.strip():
            return {"title": display_name, "chapters": _blank_chapters(chapter_count_target)}

        user = (
            f"小说标题：{display_name}\n"
            f"目标章数：{chapter_count_target}\n\n"
            f"故事梗概：\n{synopsis}\n"
        )
        try:
            raw = llm.chat(
                system=SYSTEM_PROMPT,
                user=user,
                agent_name="outline_drafter",
                temperature=0.4,
                response_format="json",
            ) or ""
            # strip accidental markdown fences
            if raw.startswith("```"):
                raw = raw.strip("`").partition("\n")[2].rpartition("```")[0]
            data = json.loads(raw)
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("OutlineDrafter bad JSON, returning shell: %s", exc)
            return {"title": display_name, "chapters": _blank_chapters(chapter_count_target)}

        if not isinstance(data, dict) or "chapters" not in data:
            return {"title": display_name, "chapters": _blank_chapters(chapter_count_target)}

        # Truncate / pad to match target; 强制字段名为 `ch`（与 Planner/Packaging 契约一致）
        # 兼容模型返回的旧字段名 index/number/id，转换后清理掉
        chapters = data.get("chapters", [])[:chapter_count_target]
        for i, ch in enumerate(chapters, start=1):
            if not isinstance(ch, dict):
                continue
            # 优先 ch；否则尝试 index/number/id；都没有则用循环序号
            raw_idx = ch.get("ch") or ch.get("index") or ch.get("number") or ch.get("id") or i
            try:
                ch["ch"] = int(raw_idx)
            except (TypeError, ValueError):
                ch["ch"] = i
            # 清理旧字段，避免 Planner 看到同时存在 ch/index 造成混淆
            for legacy in ("index", "number", "id"):
                ch.pop(legacy, None)
        return {"title": data.get("title") or display_name, "chapters": chapters}

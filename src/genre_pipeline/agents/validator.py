"""GenreValidator - three-stage validation.

Stage 1 (structure): delegates to src/tools/setting_lint.py - no LLM.
Stage 2 (semantic): THIS CLASS - one LLM call, reads the 4-5 final files,
                    writes issues to genre_issues.jsonl.
Stage 3 (trial): delegates to src/genre_pipeline/trial.py (scratch bootstrap
                 + run Planner/Generator/Evaluator on 3 chapters) when
                 --with-trial is passed.
"""
from __future__ import annotations

import json
import re

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


class GenreValidator(BaseAgent):
    name = "genre_validator"
    temperature = 0.0
    response_format = "json"
    max_tokens = 3000

    SYSTEM_PROMPT = (
        "你是一位题材包审查员。任务：读完 4-5 份题材包文件，扫出以下问题：\n"
        "1. iron-laws 条目之间内部矛盾\n"
        "2. iron-laws 和 era.md 之间的事实冲突\n"
        "3. iron-laws 和 writing-style-extra.md 之间的语气冲突\n"
        "4. era.md 或 writing-style-extra.md 中的 AI 味/模糊词/废话\n"
        "5. resource_schema.yaml（如存在）中的 baseline_scale 不可追溯问题\n"
        "\n"
        "输出严格 JSON：\n"
        '{"issues": [{"severity": "error|warning|info", '
        '"file": "...", "message": "...", "suggestion": "..."}]}'
    )

    def _build_prompts(self, bb: Blackboard, *, genre_id: str, **_):
        from src import config

        genre_dir = config.GENRES_DIR / genre_id
        files_to_read = (
            "genre.yaml",
            "era.md",
            "writing-style-extra.md",
            "iron-laws-extra.md",
            "resource_schema.yaml",
        )
        blocks = []
        inputs_read: list[str] = []
        for fname in files_to_read:
            fp = genre_dir / fname
            if fp.exists():
                text = fp.read_text(encoding="utf-8")
                blocks.append(f"## {fname}\n\n{text[:4000]}")
                inputs_read.append(f"genres/{genre_id}/{fname}")

        user = (
            f"# 待审查的题材包: {genre_id}\n\n"
            + "\n\n".join(blocks)
            + "\n\n# 任务\n\n按系统指令输出 issues JSON。"
        )
        return self.SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, genre_id: str, **_):
        obj = _parse_json(raw)
        for issue in obj.get("issues", []):
            issue["genre_id"] = genre_id
            bb.append_jsonl("genre_issues.jsonl", issue)


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)

"""GenreFixer - reads genre_issues.jsonl, patches the offending files.

First version: simple full-file rewrite. A smarter diff-based approach is
deferred. Called with retry_count kwarg so caller can gate max retries.
"""
from __future__ import annotations

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


class GenreFixer(BaseAgent):
    name = "genre_fixer"
    temperature = 0.3
    response_format = "text"
    max_tokens = 4000

    SYSTEM_PROMPT = (
        "你是一位题材包修复员。任务：读指定的单个题材文件 + 针对它的 issues，\n"
        "输出修复后的完整文件内容，只修问题不要重写。\n"
        "不允许扩展、不允许添新段落，只改 issues 点名的地方。\n"
    )

    def _build_prompts(self, bb: Blackboard, *, genre_id: str, file_name: str, issues: list, **_):
        from src import config

        genre_dir = config.GENRES_DIR / genre_id
        current = (genre_dir / file_name).read_text(encoding="utf-8")
        issues_text = "\n".join(
            f"- [{i.get('severity', 'info')}] {i.get('message', '')}"
            for i in issues
        )
        inputs_read = [f"genres/{genre_id}/{file_name}", "genre_issues.jsonl"]
        user = (
            f"# 题材 {genre_id} · 文件 {file_name}\n\n"
            f"## 当前内容\n\n{current}\n\n"
            f"## 需修复的 issues\n\n{issues_text}\n\n"
            f"# 输出\n\n请输出完整修复后的文件内容（不要带任何解释或 markdown 围栏）。"
        )
        return self.SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, genre_id: str, file_name: str, **_):
        from src import config
        (config.GENRES_DIR / genre_id / file_name).write_text(raw.strip() + "\n", encoding="utf-8")

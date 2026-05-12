"""GenreFixer - reads genre_issues for one file + its current content,
outputs the fixed full content (minimal, local, no expansion).

Design constraints:
- **最小改动**：只修 issues 指明的行/段，其它文字保持原样字符。
- **禁止新增规律**：Fixer 是审查员的补丁机器人，不是创作员。新增 iron_law
  条目、新增 era 事实、新增资源类型都禁止。
- **禁止扩写**：不添加新段落、不补充"更生动"的描写。
- **Quote-driven**：如果 issue 带 quote 字段，只修那段；其它文字原字节保留。
"""
from __future__ import annotations

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


SYSTEM_PROMPT = """输出语言：与输入文件保持一致（通常是简体中文）。

你是一位题材包补丁机器人。职责：拿到单个题材文件 + 针对它的 issues 列表，
输出**已修复**的**完整文件**，要求尊严守三条铁律：

1. **最小改动原则**（Minimum Diff）：
   - 只修 issues 指明的文字。除此之外的每一个字、每一个换行、每一个标点，
     都必须与输入文件完全相同。
   - 如果 issue 带 "quote" 字段，就只改 quote 范围内的字。

2. **禁止新增规律 / 禁止扩写**：
   - 不新增 iron_law 条目。
   - 不新增 era 事实、地名、人物、数字。
   - 不把段落"改得更生动"。
   - 不补充模型自己想到的例子。
   - 不改章节标题 / 一级标题 / frontmatter 结构。

3. **只输出文件本体**：
   - 不要 markdown 围栏（```）。
   - 不要"以下是修复后的内容"之类 preamble。
   - 不要任何解释或总结。
   - 输出的第一个字符就是文件的第一个字符。
   - 文件末尾保留原有的换行符。

修复策略（按优先级）：
- severity=error 的 issue 必须处理。
- severity=warning 的尽量处理，若与 error 修复冲突则以 error 为先。
- 若某条 issue 的"修复建议"与铁律 1/2 冲突（例如建议你"扩写成 200 字"），
  按铁律办事，不要扩写——选择更保守的最小改法。

自检清单（输出前默念）：
- 我有没有改到 issue 没点名的段落？（若有，撤回。）
- 我有没有新增实体/数字/地名？（若有，删掉。）
- 文件字数和原文相差 > 20% 吗？（若是，你改得太多了，重来。）
"""


class GenreFixer(BaseAgent):
    name = "genre_fixer"
    temperature = 0.2  # 低温：Fixer 不是创作员
    response_format = "text"
    max_tokens = 4000

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def _build_prompts(
        self,
        bb: Blackboard,
        *,
        genre_id: str,
        file_name: str,
        issues: list,
        **_,
    ):
        from src import config

        genre_dir = config.GENRES_DIR / genre_id
        current = (genre_dir / file_name).read_text(encoding="utf-8")

        # Render issues with any 'quote' / 'suggestion' fields if present.
        def _fmt(i: dict) -> str:
            parts = [f"[{i.get('severity', 'info')}]"]
            if i.get("quote"):
                parts.append(f"quote=«{i['quote']}»")
            parts.append(f"message={i.get('message', '')}")
            if i.get("suggestion"):
                parts.append(f"suggestion={i['suggestion']}")
            return " | ".join(parts)

        issues_text = "\n".join(f"- {_fmt(i)}" for i in issues) or "（无）"

        inputs_read = [f"genres/{genre_id}/{file_name}", "genre_issues.jsonl"]
        user = (
            f"<target>\n"
            f"genre_id: {genre_id}\n"
            f"file: {file_name}\n"
            f"</target>\n\n"
            f"<current_content>\n"
            f"{current}"
            f"</current_content>\n\n"
            f"<issues_to_fix>\n"
            f"{issues_text}\n"
            f"</issues_to_fix>\n\n"
            f"<your_task>\n"
            f"按系统指令的三条铁律，输出修复后的完整 {file_name}。\n"
            f"最小改动 + 禁止新增规律 + 禁止扩写。只输出文件本体。\n"
            f"</your_task>"
        )
        return SYSTEM_PROMPT, user, inputs_read

    def _handle_output(
        self, bb: Blackboard, raw: str, *, genre_id: str, file_name: str, **_
    ):
        from src import config

        # Strip any accidentally-emitted markdown fences (defensive — prompt
        # forbids them but models sometimes leak).
        text = raw.strip()
        if text.startswith("```"):
            # drop first fence line
            text = text.split("\n", 1)[1] if "\n" in text else ""
            if text.endswith("```"):
                text = text[: -len("```")]
            text = text.strip()

        (config.GENRES_DIR / genre_id / file_name).write_text(
            text + "\n", encoding="utf-8"
        )

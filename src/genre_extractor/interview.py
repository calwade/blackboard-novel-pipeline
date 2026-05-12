"""Interactive questionnaire for --new-genre --interactive.

Produces a richer initial draft than the pure stub path, by filling the
4 genre files with answers the user provided interactively.

Public API:
    build_genre_from_answers(answers: dict) -> dict
        Programmatic entry — used by tests and by Web UI (future).
    run_interview() -> dict
        Interactive CLI — asks the user via input() and calls
        build_genre_from_answers.

This module never calls LLM; it's pure template filling. The richer genre
files produced here can later be fed to the prompt-based GenreDrafter or
hand-edited by the author.
"""
from __future__ import annotations

from typing import Any

import yaml

from src import config


# ---- templates (richer than the pure-stub ones in pipeline.py) ----

_GENRE_YAML_TPL = """# Genre: {id}
# Authored via --new-genre --interactive, {timestamp}

id: {id}
display_name: "{display_name}"
locale: zh-Hans
genre: "{genre}"
era: "{era}"
tone: "{tone}"

# 作者画像 —— Generator 的 system prompt 会读
author_persona_hints:
{author_persona_hints_yaml}

# 该题材"不要写成这样"
genre_avoid:
{genre_avoid_yaml}

# 风格锁定（所有 Agent 在生成前加载）
prohibited_styles:
{prohibited_styles_yaml}
"""

_ERA_TPL = """# Era · {display_name}

> 此文件描述 **{era}** 的时代事实，供 Generator 生成场景细节时查询。
> 由 `--new-genre --interactive` 生成初稿，作者需继续补充细节后再投入生产。

## 时代基调

{tone}

## 关键事实（占位）

1. （请填一条：该时代的标志性事件 / 技术水平 / 政治格局）
2. （请填一条：主流交通、通讯、住宿方式）
3. （请填一条：货币、物价、普通人月收入水平）
4. （请填一条：独特的文化符号 —— 音乐 / 服饰 / 口头禅 / 食物）
5. （请填一条：不可违背的历史节点 —— 某事必须在某年发生）

## 时代限制（铁律支撑）

- 不要让人物使用 {era} 不可能拥有的技术或知识
- 不要混入其他时代的特征符号

（至少写到 500 字再提交 setting_lint；当前为起步模板。）
"""

_WRITING_STYLE_TPL = """# Writing Style Extra · {display_name}

> 题材特有的风格规范，Generator + Fixer 会读这份文件。
> 由 `--new-genre --interactive` 生成初稿。

## 语言基调

{tone}

## 作者视角建议

{author_persona_hints_markdown}

## 叙事习惯（占位，待补）

- **句式长度**：（长短结合 / 以短句为主 / 以长句为主？）
- **对白密度**：（占全文约 X%？）
- **内心独白用法**：（大量 / 克制 / 禁止？）
- **场景切换信号**：（空行 / 标题行 / 时间地点标记？）

## 词汇偏好

- **鼓励使用**：（该题材的标志性词汇）
- **避免使用**：
{genre_avoid_markdown}

## 明确禁止的写法

{prohibited_styles_markdown}

（至少写到 300 字再提交 setting_lint；当前为起步模板。）
"""

_IRON_LAWS_TPL = """# Iron Laws Extra · {display_name}

> 该题材的硬禁令。Evaluator 用 iron_law_extra_N 标识符引用。
> 由 `--new-genre --interactive` 生成初稿，至少需要 3 条才能通过 setting_lint。

---

## iron_law_extra_1: 题材定位（占位）

（请具体描述：这个题材的核心矛盾是什么？主角的根本驱动力是什么？）

❌ 反例：（主角行为违反核心题材定位的典型例子）
✅ 正例：（主角行为符合核心题材定位的典型例子）

---

## iron_law_extra_2: 不可出现的桥段

以下桥段在 {display_name} 中应被避免：

{genre_avoid_markdown}

每条都应该具体到"为什么不能这样写 + 怎么写才对"。

---

## iron_law_extra_3: 风格锁定

禁止以下他题材风格污染：

{prohibited_styles_markdown}

一旦出现跨题材串味，Evaluator 会 hit iron_law_extra_3。

---

## iron_law_extra_4+: （请继续补充你这个题材特有的铁律）

一部好的题材包通常有 10-20 条 iron_law。继续补充：
- 主角的行为底线（什么情况下绝不做什么）
- 配角的规律（反派如何行动、盟友如何背叛）
- 世界观的物理规则（哪些事情在这个题材中不可能发生）
- 情感逻辑（爱恨的演进方式）
"""


def _yaml_list(items: list[str], indent: int = 2) -> str:
    """Render a list of strings as a YAML block list with given indent."""
    if not items:
        return "  []"
    pad = " " * indent
    return "\n".join(f"{pad}- {item}" for item in items)


def _md_bullets(items: list[str], indent: int = 0) -> str:
    """Render a list of strings as Markdown bullets."""
    if not items:
        return "（请补充）"
    pad = " " * indent
    return "\n".join(f"{pad}- {item}" for item in items)


def _require(answers: dict, key: str) -> str:
    if not answers.get(key):
        raise ValueError(f"answers missing required field: {key}")
    return str(answers[key])


def build_genre_from_answers(answers: dict) -> dict:
    """Create a genre pack from a dict of survey answers. No LLM.

    Required keys:
        id, display_name

    Optional (with reasonable defaults / fallbacks):
        genre, era, tone, author_persona_hints, genre_avoid, prohibited_styles
    """
    from datetime import datetime

    gid = _require(answers, "id")
    display_name = _require(answers, "display_name")

    genre_dir = config.GENRES_DIR / gid
    if genre_dir.exists():
        raise FileExistsError(f"Genre already exists: {genre_dir}")
    genre_dir.mkdir(parents=True)

    ctx: dict[str, Any] = {
        "id": gid,
        "display_name": display_name,
        "genre": answers.get("genre", "TBD"),
        "era": answers.get("era", "TBD"),
        "tone": answers.get("tone", "TBD"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "author_persona_hints_yaml": _yaml_list(
            answers.get("author_persona_hints", []) or []
        ),
        "genre_avoid_yaml": _yaml_list(answers.get("genre_avoid", []) or []),
        "prohibited_styles_yaml": _yaml_list(
            answers.get("prohibited_styles", []) or []
        ),
        "author_persona_hints_markdown": _md_bullets(
            answers.get("author_persona_hints", []) or []
        ),
        "genre_avoid_markdown": _md_bullets(answers.get("genre_avoid", []) or []),
        "prohibited_styles_markdown": _md_bullets(
            answers.get("prohibited_styles", []) or []
        ),
    }

    (genre_dir / "genre.yaml").write_text(_GENRE_YAML_TPL.format(**ctx), encoding="utf-8")
    (genre_dir / "era.md").write_text(_ERA_TPL.format(**ctx), encoding="utf-8")
    (genre_dir / "writing-style-extra.md").write_text(
        _WRITING_STYLE_TPL.format(**ctx), encoding="utf-8"
    )
    (genre_dir / "iron-laws-extra.md").write_text(
        _IRON_LAWS_TPL.format(**ctx), encoding="utf-8"
    )

    # Seed build_status in .build/
    from src.core.blackboard import Blackboard
    from src.genre_extractor import schemas

    build_dir = genre_dir / ".build"
    build_dir.mkdir(parents=True, exist_ok=True)
    bb = Blackboard(root=build_dir)
    bb.write_yaml(
        "build_status.yaml",
        schemas.make_initial_build_status(genre_id=gid, entry="new-genre-interview"),
    )

    return {"ok": True, "genre_id": gid, "path": str(genre_dir)}


# ---- interactive CLI ----

_QUESTIONS = [
    ("id", "题材 ID（小写+连字符，如 gangster-tw-1990）", True, None),
    ("display_name", "显示名（如 '港综 · 台湾 · 1990'）", True, None),
    ("genre", "类型描述（如 '黑帮 + 金融犯罪'）", False, "TBD"),
    ("era", "时代与地点（如 '1990-2000 台北高雄'）", False, "TBD"),
    ("tone", "基调关键词（如 '暴力美学 + 江湖算计 + 市井温度'）", False, "TBD"),
]

_LIST_QUESTIONS = [
    ("author_persona_hints", "作者画像提示（每行一条，空行结束；至少 2 条）"),
    ("genre_avoid", "题材回避清单（每行一条；这个题材'绝不能写成这样'）"),
    ("prohibited_styles", "风格锁定禁止（每行一条；禁止哪些别的题材腔调混入）"),
]


def _ask_one(prompt: str, required: bool, default: str | None) -> str:
    hint = f" [{default}]" if default and not required else ""
    required_mark = " *" if required else ""
    while True:
        ans = input(f"{prompt}{required_mark}{hint}\n> ").strip()
        if ans:
            return ans
        if required:
            print("  ⚠ 这是必填项，请输入。")
            continue
        return default or ""


def _ask_list(prompt: str) -> list[str]:
    print(f"{prompt}")
    items = []
    while True:
        line = input(f"  {len(items)+1}> ").strip()
        if not line:
            if items:
                return items
            print("  ⚠ 至少输入 1 条（再回车结束）。")
            continue
        items.append(line)


def run_interview() -> dict:
    """Interactive CLI entry. Asks questions via input(), returns answers dict."""
    print("\n=== Genre Pipeline · Interactive Scaffold ===\n")
    answers: dict[str, Any] = {}
    for key, prompt, required, default in _QUESTIONS:
        answers[key] = _ask_one(prompt, required, default)
    for key, prompt in _LIST_QUESTIONS:
        answers[key] = _ask_list(prompt)
    print("\n=== 问卷完成，生成初稿中…")
    return build_genre_from_answers(answers)

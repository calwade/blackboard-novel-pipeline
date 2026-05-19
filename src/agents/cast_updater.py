"""CastUpdater — maintain state/characters-cast.yaml.

> 注意：本模块定义了 ``_repair_yaml_chinese_quotes`` 用于自动修复 LLM 输出中
> 常见的"yaml 字符串里夹裸双引号"问题（中文标注词被裸 `"` 包裹会破坏 yaml 解析）。
> ``_handle_output`` 在第一次 ``yaml.safe_load`` 失败时会先尝试该修复，再失败
> 则记 warning 并 silently return（不抛错、不覆盖旧文件），让流水线继续。


Background
----------
`characters.yaml` 是**作者意图宪法**（不可变）：作品的初始 traits / redlines /
relations。但 LLM 在写作过程中会自然引入新角色（老刘、赵铁城、方洪……），
这些"先例人物"如果不被记录，CharacterGuard 就无法判断"本章某个出现在第 3
章的配角现在性格是否漂移"。

CastUpdater 解决这个问题：每章末尾覆盖式更新 `characters-cast.yaml`，
作为**运行时演员表**（已建立的先例库）。基线宪法仍以 characters.yaml 为准；
cast 文件只记录 LLM 自创角色 + 标注哪些条目镜像自基线（`in_baseline=true`）。

Reads
~~~~~
- state/chapters/ch{N:03d}.md            — 本章正文（ground truth）
- state/characters-cast.yaml             — 上一版（首次跑可不存在）
- state/characters.yaml                  — 基线宪法（用于打 in_baseline 标志）

Writes
~~~~~~
- state/characters-cast.yaml             — 完整 yaml，覆盖式

Boundary（Lesson 3）
~~~~~~~~~~~~~~~~~~~~
- 只读章节正文，不读 plan / verdict / issues：cast 是事实派生，不是策划意图。
- 永不删除条目；永不修改基线人物的 traits/redlines（如发现冲突，写进 _baseline_drift 等人审）。

Temperature 0.2 — bookkeeping，不创造。
"""
from __future__ import annotations

import sys

import yaml

from ._base import BaseAgent
from ..blackboard import Blackboard


def _repair_yaml_chinese_quotes(text: str) -> str:
    """Repair YAML lines that contain unescaped 中文标注 double quotes.

    LLM 经常输出形如 ``- "规矩"挂在嘴边`` 或 ``one_line: 系统炉底"挂着"，残留……``
    这类文本——它想用双引号做中文标注（"重点词"），但 YAML 会把 ``"规矩"`` 当成
    quoted scalar 边界，后续的 ``挂在嘴边`` 变成 syntax error。

    本函数对每一行做启发式修复：

    1. 识别行内 "value 起始位置"（list item 的 ``- `` 后面 / mapping 的 ``key: `` 后面）。
    2. 如果 value 是 *纯粹*由一对双引号包起来的字符串（``"..."``，且不含其他内容/换行），
       视为合法 quoted scalar，保留不动。
    3. 否则（裸双引号夹在 value 中间），把成对的 ``"`` 顺序替换为中文 ``「`` ``」``。

    只处理 ``- ...`` 起始的 list item 行和 ``key: ...`` 形式的 mapping 行；
    多行折叠 / block scalar / 锚点 / 注释等不动。
    """
    fixed_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line
        # 只剥掉行首空格用于判定起始位置，保留 indent。
        stripped = line.lstrip()
        if not stripped or '"' not in stripped:
            fixed_lines.append(line)
            continue
        indent = line[: len(line) - len(stripped)]

        value_start_in_line: int | None = None
        # list item: "- xxx"
        if stripped.startswith("- "):
            value_start_in_line = len(indent) + 2
        else:
            # mapping: "key: value" — find first ": "
            colon = stripped.find(": ")
            if colon != -1:
                value_start_in_line = len(indent) + colon + 2

        if value_start_in_line is None:
            fixed_lines.append(line)
            continue

        prefix = line[:value_start_in_line]
        value = line[value_start_in_line:]
        # strip trailing inline comment? — 保守起见不动注释；只处理 value 内引号。

        if value.count('"') < 2:
            fixed_lines.append(line)
            continue

        # 纯 "..." 包裹 + 内部不含其他双引号 → 合法 quoted scalar，保留
        v_stripped = value.rstrip()
        if (
            v_stripped.startswith('"')
            and v_stripped.endswith('"')
            and v_stripped.count('"') == 2
        ):
            fixed_lines.append(line)
            continue

        # 成对替换：奇数次出现 → 「，偶数次出现 → 」
        new_chars: list[str] = []
        opening = True
        for ch in value:
            if ch == '"':
                new_chars.append("「" if opening else "」")
                opening = not opening
            else:
                new_chars.append(ch)
        # 如果出现奇数次双引号（最后一个 "「" 没有匹配的 "」"），无法修复 → 原样返回
        if not opening:
            # opening flipped odd times → unmatched
            fixed_lines.append(line)
            continue
        fixed_lines.append(prefix + "".join(new_chars))
    return "\n".join(fixed_lines)


# 给 LLM 看的 schema 文档段（在 system prompt 内引用）。
CAST_SCHEMA_DOC = """\
schema_version: 1                # 固定 1（未来 schema 演进时递增）
last_updated_chapter: <int>      # 当前刚处理完的章节号
cast:
  - name: <str>                  # 角色姓名（人名，不写代称）
    role: <str>                  # 主角 / 配角 / 反派 / 路人
    first_appeared_ch: <int>     # 首次出现的章节
    last_appeared_ch: <int>      # 最近一次出现的章节
    status: <str>                # active / offstage / dead / unknown
    one_line: <str>              # 一句话定位（身份+核心动机）
    traits: [<str>, ...]         # 累积观察到的性格特征
    redlines: [<str>, ...]       # 角色"绝不会做"的事（来自正文行为反推）
    relations:
      - to: <str>                # 关系对象（另一个角色名）
        kind: <str>              # 盟友/敌人/上下级/亲属/暧昧/中立
        evolution: <str>         # 一句话描述关系当前阶段
    voice_tags: [<str>, ...]     # 说话风格标签（口头禅、句式特征）
    aliases: [<str>, ...]        # 别名 / 绰号
    in_baseline: <bool>          # 是否出现在 characters.yaml 中
    _baseline_drift: [<str>, ...]  # 仅 in_baseline=true 时可能出现：
                                   # 正文行为与基线 traits 冲突的描述（等人审）
notes:
  pruning_policy: <str>          # 关于"何时删条目"的当前策略备注（默认：永不删）
"""


class CastUpdater(BaseAgent):
    name = "cast_updater"
    temperature = 0.2
    response_format = "text"  # 自己 yaml.safe_load 校验
    max_tokens = 4000

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        chapter_path = f"chapters/ch{chapter:03d}.md"
        chapter_text = bb.read_text(chapter_path)

        baseline = bb.read_text("characters.yaml")

        if bb.exists("characters-cast.yaml"):
            prior_cast = bb.read_text("characters-cast.yaml")
            prior_note = "（下方是上一版演员表，请保留所有现有条目，只在必要处更新/新增）"
        else:
            prior_cast = "(首次运行，演员表为空 — 请基于本章正文 + 基线宪法构建)"
            prior_note = "（这是首次生成 cast 文件）"

        inputs_read = [
            f"state/{chapter_path}",
            "state/characters.yaml",
        ]
        if bb.exists("characters-cast.yaml"):
            inputs_read.append("state/characters-cast.yaml")

        system = (
            "你是 cast 维护员。每章末跑一次。读本章正文 + 上一版 cast + 基线 yaml，\n"
            "覆盖式输出**完整的** characters-cast.yaml。\n"
            "\n"
            "# 核心规则\n"
            "\n"
            "1. **新角色识别**：从本章正文里抽取『有名字、有台词或有具体行为』的角色。\n"
            "   - **不抽**：路人 A/B/C、群众、未命名的『那个男人』、街上的小贩。\n"
            "   - **抽**：林家耀、老刘、赵铁城、方洪、阿 Sir 等具名且有动作/对白的角色。\n"
            "\n"
            "2. **基线对照**：\n"
            "   - 出现在 characters.yaml（基线宪法）的角色 → `in_baseline: true`\n"
            "   - 不在基线、由 LLM 自创的角色 → `in_baseline: false`\n"
            "\n"
            "3. **更新策略**：\n"
            "   - 已存条目本章再次出现 → 更新 `last_appeared_ch`；按需补 traits / voice_tags / relations\n"
            "   - 本章首次出现 → 新增条目，`first_appeared_ch=N`，`last_appeared_ch=N`\n"
            "   - 本章死亡/退场 → `status: dead` 或 `offstage`，仍**保留条目**\n"
            "   - **永不删除条目**（哪怕 10 章未出场也保留）\n"
            "\n"
            "4. **基线保护（最关键）**：\n"
            "   - `in_baseline: true` 的角色，其 `traits` / `redlines` **只能添加，不能修改或删除**\n"
            "   - 如果本章正文行为与基线 traits 冲突 → 写进 `_baseline_drift` 数组等人审，\n"
            "     **不要悄悄改 yaml**\n"
            "\n"
            "5. **不创造正文里没出现的角色**。如果某个基线人物本章没登场，沿用上一版条目即可\n"
            "   （`last_appeared_ch` 保持原值）。\n"
            "\n"
            "6. 输出**完整 yaml**（覆盖式），不是 diff、不是 patch。\n"
            "\n"
            "# Schema\n"
            "\n"
            "```yaml\n"
            f"{CAST_SCHEMA_DOC}"
            "```\n"
            "\n"
            "# 输出要求\n"
            "\n"
            "- 严格 yaml 文档，从 `schema_version: 1` 开始。\n"
            "- **不写**散文、markdown 标题、解释性文字、```yaml ``` 代码围栏。\n"
            "- 中文使用简体；人名不加引号（YAML 字符串规范允许）。\n"
            "- 字段顺序按 schema；缺省字段写空数组 `[]` 或省略，不要写 `null`。\n"
            "\n"
            "# yaml 安全规则（必须遵守）\n"
            "\n"
            "- 字符串值里**绝对不要用裸双引号** `\"`——它会被 yaml 当作 quoted scalar 边界，\n"
            "  后续的中文/数字会被解析失败。中文标注词汇请用全角直角引号 `「」` 或 `『』`：\n"
            "    错误：`- \"规矩\"挂在嘴边`\n"
            "    正确：`- 「规矩」挂在嘴边`\n"
            "    错误：`one_line: 系统炉底\"挂着\"，残留……`\n"
            "    正确：`one_line: 系统炉底「挂着」，残留……`\n"
            "- 如果一定要在字符串内放双引号或冒号等特殊字符，把整个 value 用单引号包：\n"
            "    正确：`- '他说：\"规矩\"，挂在嘴边'`\n"
            "- 列表项前缀只用 yaml 的 `- `；不要用项目符号 `•` `·` `※`。\n"
        )

        user = (
            f"# 第 {chapter} 章正文（事实基准）\n\n"
            f"{chapter_text}\n\n"
            f"# 基线宪法 characters.yaml（不可变；用于决定 in_baseline 标志）\n\n"
            f"```yaml\n{baseline}\n```\n\n"
            f"# 上一版 characters-cast.yaml {prior_note}\n\n"
            f"```yaml\n{prior_cast}\n```\n\n"
            f"# 任务\n\n"
            f"输出更新后的完整 `characters-cast.yaml`。`last_updated_chapter: {chapter}`。"
            f"严格 yaml，无散文，无围栏。"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        text = raw.strip()
        # 兼容 LLM 偶尔加的 ```yaml ... ``` 围栏
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            obj = yaml.safe_load(text)
        except yaml.YAMLError as first_err:
            # 一次自动修复尝试：把行内裸双引号成对替换为「」
            repaired = _repair_yaml_chinese_quotes(text)
            try:
                obj = yaml.safe_load(repaired)
                print(
                    f"[cast_updater] auto-repaired Chinese quotes in YAML "
                    f"for ch{chapter:03d}",
                    file=sys.stderr,
                )
            except yaml.YAMLError as second_err:
                # 仍坏 → 容忍：警告 + 不写文件，让旧 cast（若有）保留，pipeline 继续
                print(
                    f"[cast_updater] WARN ch{chapter:03d}: YAML unrecoverable "
                    f"(first={first_err}; after_repair={second_err}); "
                    f"keeping prior cast and skipping this chapter's update",
                    file=sys.stderr,
                )
                return

        if not isinstance(obj, dict):
            print(
                f"[cast_updater] WARN ch{chapter:03d}: output is not a YAML mapping "
                f"(got {type(obj).__name__}); keeping prior cast",
                file=sys.stderr,
            )
            return

        # 必需字段校验：缺失也容忍（warning + skip），避免阻断主流水线。
        missing: list[str] = []
        if "schema_version" not in obj or not isinstance(obj.get("schema_version"), int):
            missing.append("schema_version")
        if "last_updated_chapter" not in obj or not isinstance(
            obj.get("last_updated_chapter"), int
        ):
            missing.append("last_updated_chapter")
        if "cast" not in obj or not isinstance(obj.get("cast"), list):
            missing.append("cast")
        if missing:
            print(
                f"[cast_updater] WARN ch{chapter:03d}: missing/invalid fields "
                f"{missing}; keeping prior cast",
                file=sys.stderr,
            )
            return

        bb.write_yaml("characters-cast.yaml", obj)


def read_characters_cast(bb: Blackboard) -> tuple[str, list[str]]:
    """Helper for downstream auditors (CharacterGuard).

    Returns (cast_text, inputs_read). When the file does not exist yet, returns
    ('(尚无演员表——本章是首章或 cast tracking 未启用)', [])。
    """
    if bb.exists("characters-cast.yaml"):
        return bb.read_text("characters-cast.yaml"), ["state/characters-cast.yaml"]
    return "（尚无演员表——本章是首章或 cast tracking 未启用）", []

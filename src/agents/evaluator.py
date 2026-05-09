"""Evaluator — default-reject critic with adversarial persona + JSON rubric.

This is the most important agent in the pipeline. It is what converts
"5 prompts in a for loop" into a real Planner/Generator/Evaluator triangle.

Key design (per Oracle review):
- Adversarial persona ("默认拒稿, 找不出 3 个硬伤就是失职") — inverts model bias.
- Structured JSON rubric with per-landmine hit/evidence/severity — removes
  room for hollow sycophancy.
- NEVER sees Generator's reasoning or plan — only the final chapter text.
- Cross-checks against characters.yaml + timeline.yaml.
- Loads setting-specific iron-laws-extra.md as additional criteria.

Reads (everything under state/ is setting-injected via bootstrap):
  - state/chapters/ch{N:03d}.md
  - state/characters.yaml
  - state/timeline.yaml
  - state/iron-laws-extra.md  — setting-specific iron laws
  - rules/18-landmines.md     — universal landmines
  - rules/24-iron-laws.md     — universal iron laws

Writes:
  - state/chapters/ch{N:03d}.verdict.json
  - appends issues to state/issues.jsonl
"""
from __future__ import annotations

import json
import re
import time

from ._base import BaseAgent
from ._verdict_schema import LANDMINE_IDS, validate_verdict
from ..blackboard import Blackboard


class Evaluator(BaseAgent):
    name = "evaluator"
    temperature = 0.0
    response_format = "json"
    max_tokens = 4000

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        chapter_path = f"chapters/ch{chapter:03d}.md"
        chapter_text = bb.read_text(chapter_path)

        characters = bb.read_text("characters.yaml")
        timeline = bb.read_text("timeline.yaml")
        iron_laws_extra = bb.read_text("iron-laws-extra.md")
        landmines = self._read_rule("18-landmines.md")
        iron_laws = self._read_rule("24-iron-laws.md")

        try:
            setting = bb.read_yaml("setting.yaml")
        except Exception:
            setting = {}
        genre = setting.get("genre", "通用小说")
        era_label = setting.get("era", "")

        inputs_read = [
            f"state/{chapter_path}",
            "state/characters.yaml",
            "state/timeline.yaml",
            "state/iron-laws-extra.md",
            "rules/18-landmines.md",
            "rules/24-iron-laws.md",
        ]

        system = (
            f"你是业内以刁钻著称的资深网文主编，在本题材（{genre} · {era_label}）做了 20 年。\n"
            "你的默认立场是『拒稿』。拿到任何稿件，你必须找出至少 3 处硬伤——\n"
            "如果找不出 3 处，那就是你失职，说明你走神了。\n"
            "\n"
            "你只信稿件本身，不听任何『作者本意』的辩解。\n"
            "你不关心作者花了多少功夫，你只关心读者看到的是什么。\n"
            "\n"
            "# 你的工作\n"
            "\n"
            "1. 对下方『18 个雷点』每一条独立打分：命中 / 未命中。\n"
            "2. 每一条命中都必须给出 evidence：**原文中的具体片段（原文引用，不是复述）**。\n"
            "3. 每一条命中都必须标 severity：high / medium / low。\n"
            "4. 然后基于命中情况给出 overall_pass 布尔值。判定规则：\n"
            "   - 任何 high 命中 → overall_pass = false\n"
            "   - 两个及以上 medium 命中 → overall_pass = false\n"
            "   - 其他情况 → overall_pass = true\n"
            "5. 最后给出 top_3_fixes：最该优先修的 3 处，包含 where（具体位置/段落引文）"
            "与 what（改写方向）。\n"
            "6. top_3_fixes 中的 where **必须是原文具体引文**，不能是 `…` / `...` / 空字符串。\n"
            "   如果你找不到 3 处真问题，可以少于 3 个，但不能用占位符填充。\n"
            "\n"
            "# 对人设和时间线的交叉验证\n"
            "\n"
            "- 如果稿件中主角的行为违背 characters.yaml 中的 redlines / traits，必须在\n"
            "  landmine_10（人设前后矛盾）或 landmine_11（人物形象单薄）命中。\n"
            "- 如果稿件中的年份、事件、物价与 timeline.yaml 不符，必须在\n"
            "  landmine_13（世界观模糊/脱离现实）命中。\n"
            "- 如果稿件违反题材特有铁律（iron-laws-extra.md），必须在\n"
            "  landmine_10 或 landmine_13 命中，evidence 中说明违反了哪条 iron_law_extra_N。\n"
            "\n"
            "# 绝对格式要求\n"
            "\n"
            "- 严格输出 JSON，不写任何散文、解释或 Markdown。\n"
            "- JSON 必须包含所有 18 个 landmine_N 键，一个都不能少。\n"
            "- evidence 若未命中则为 null。\n"
            "- top_3_fixes 的 where 字段绝不能是 `…` / `...`。\n"
            "\n"
            "# 参考：18 个雷点（完整列表）\n\n"
            + landmines
            + "\n\n# 参考：通用 24 条铁律\n\n"
            + iron_laws
            + "\n\n# 参考：题材特有铁律（由 setting 注入）\n\n"
            + iron_laws_extra
        )

        # NOTE: we intentionally do NOT embed a skeleton with "…" placeholders
        # in the user prompt schema — that was the root cause of the "Evaluator
        # returned skeleton" bug. Instead we describe the required keys.
        user = (
            f"# 本章节（第 {chapter} 章）全文\n\n"
            f"{chapter_text}\n\n"
            f"# 人物档案 (characters.yaml)\n\n```yaml\n{characters}\n```\n\n"
            f"# 时间线 (timeline.yaml)\n\n```yaml\n{timeline}\n```\n\n"
            f"# 输出 JSON 结构（严格遵守）\n\n"
            "必须包含以下字段：\n"
            "- `overall_pass` (boolean)\n"
            "- `landmines`：对象，包含 `landmine_1` 到 `landmine_18` 全部 18 键，\n"
            "  每个值是 `{hit: bool, evidence: string|null, severity: 'high'|'medium'|'low'|null}`\n"
            "- `top_3_fixes`：数组，0-3 个元素；每个元素是\n"
            "  `{where: <原文引文，至少 6 个字>, what: <改写方向，至少 10 个字>}`\n"
            "\n"
            "✋ 不要复用示例占位符 — 每一处 evidence / where 都必须是你从上方章节原文中找到的真实引文。\n"
            "如果你找不到任何问题，就输出 landmines 全部 hit=false、top_3_fixes=[]、overall_pass=true。\n"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        # Parse JSON defensively (strip markdown fences if any)
        try:
            parsed = _parse_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            # Malformed JSON at parse level — synthesize failing verdict
            parsed = {"_parse_error": f"JSON parse failed: {e}"}

        # Validate + normalize + detect skeleton (pure function, unit-tested)
        result = validate_verdict(parsed)
        verdict = result["clean_verdict"]
        warnings = result["validation_warnings"]
        skeleton = result["skeleton_detected"]

        # Surface warnings for observability. Stored in the verdict file so the
        # Inspector can show them alongside the rubric.
        if warnings:
            verdict["_validation_warnings"] = warnings

        bb.write_json(f"chapters/ch{chapter:03d}.verdict.json", verdict)

        # Log individual issues (skip synthetic skeleton hits — those aren't
        # about the chapter, they're about the evaluator output itself)
        if not skeleton:
            ts = time.time()
            for mine_id, entry in verdict["landmines"].items():
                if entry.get("hit"):
                    bb.append_jsonl(
                        "issues.jsonl",
                        {
                            "ts": ts,
                            "chapter": chapter,
                            "landmine_id": mine_id,
                            "severity": entry.get("severity"),
                            "evidence": entry.get("evidence"),
                        },
                    )


def _parse_json(raw: str):
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
    if m:
        s = m.group(1)
    return json.loads(s)

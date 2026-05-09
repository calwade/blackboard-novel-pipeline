"""Evaluator — default-reject critic with adversarial persona + JSON rubric.

This is the most important agent in the pipeline. It is what converts
"5 prompts in a for loop" into a real Planner/Generator/Evaluator triangle.

Key design (per Oracle review):
- Adversarial persona ("默认拒稿, 找不出 3 个硬伤就是失职") — inverts model bias.
- Structured JSON rubric with per-landmine hit/evidence/severity — removes
  room for hollow sycophancy.
- NEVER sees Generator's reasoning or plan — only the final chapter text.
- Cross-checks against characters.yaml + timeline.yaml.

Reads:
  - state/chapters/ch{N:03d}.md
  - state/characters.yaml
  - state/timeline.yaml
  - rules/18-landmines.md
  - rules/24-iron-laws.md

Writes:
  - state/chapters/ch{N:03d}.verdict.json
  - appends issues to state/issues.jsonl
"""
from __future__ import annotations

import json
import re
import time

from ._base import BaseAgent
from ..blackboard import Blackboard


# The 18 landmine IDs we expect the Evaluator to score. Keep this list in
# sync with rules/18-landmines.md section titles. The Evaluator prompt
# enforces that the output JSON contains every key.
LANDMINE_IDS = [f"landmine_{i}" for i in range(1, 19)]


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
        landmines = self._read_rule("18-landmines.md")
        iron_laws = self._read_rule("24-iron-laws.md")

        inputs_read = [
            f"state/{chapter_path}",
            "state/characters.yaml",
            "state/timeline.yaml",
            "rules/18-landmines.md",
            "rules/24-iron-laws.md",
        ]

        system = (
            "你是业内以刁钻著称的资深网文主编，在港综同人赛道做了 20 年。\n"
            "你的默认立场是『拒稿』。拿到任何稿件，你必须找出至少 3 处硬伤——\n"
            "如果找不出 3 处，那就是你失职，说明你走神了。\n"
            "\n"
            "你只信稿件本身，不听任何『作者本意』的辩解。\n"
            "你不关心作者花了多少功夫，你只关心读者看到的是什么。\n"
            "\n"
            "# 你的工作\n"
            "\n"
            "1. 对下方『18 个雷点』每一条独立打分：命中 / 未命中。\n"
            "2. 每一条命中都必须给出 evidence：原文中的具体片段（原文引用，不是复述）。\n"
            "3. 每一条命中都必须标 severity：high / medium / low。\n"
            "4. 然后基于命中情况给出 overall_pass 布尔值。判定规则：\n"
            "   - 任何 high 命中 → overall_pass = false\n"
            "   - 两个及以上 medium 命中 → overall_pass = false\n"
            "   - 其他情况 → overall_pass = true\n"
            "5. 最后给出 top_3_fixes：最该优先修的 3 处，包含 where（具体位置）与 what（改写方向）。\n"
            "\n"
            "# 对人设和时间线的交叉验证\n"
            "\n"
            "- 如果稿件中主角的行为违背 characters.yaml 中的 redlines / traits，必须在\n"
            "  landmine_10（人设前后矛盾）或 landmine_11（人物形象单薄）命中。\n"
            "- 如果稿件中的年份、事件、物价与 timeline.yaml 不符，必须在\n"
            "  landmine_13（世界观模糊/脱离现实）命中。\n"
            "\n"
            "# 绝对格式要求\n"
            "\n"
            "- 严格输出 JSON，不写任何散文、解释或 Markdown。\n"
            "- JSON 必须包含所有 18 个 landmine_N 键，一个都不能少。\n"
            "- evidence 若未命中则为 null。\n"
            "\n"
            "# 参考：18 个雷点（完整列表）\n\n"
            + landmines
            + "\n\n# 参考：24 条铁律（补充判据）\n\n"
            + iron_laws
        )

        user = (
            f"# 本章节（第 {chapter} 章）全文\n\n"
            f"{chapter_text}\n\n"
            f"# 人物档案 (characters.yaml)\n\n```yaml\n{characters}\n```\n\n"
            f"# 时间线 (timeline.yaml)\n\n```yaml\n{timeline}\n```\n\n"
            f"# 输出 JSON 结构（严格遵守）\n\n"
            + json.dumps(
                {
                    "overall_pass": False,
                    "landmines": {
                        f"landmine_{i}": {
                            "hit": False,
                            "evidence": None,
                            "severity": None,
                        }
                        for i in range(1, 19)
                    },
                    "top_3_fixes": [
                        {"where": "…", "what": "…"},
                        {"where": "…", "what": "…"},
                        {"where": "…", "what": "…"},
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        verdict = _parse_json(raw)
        # Defensive: ensure all landmine keys exist
        for mine in LANDMINE_IDS:
            if mine not in verdict.get("landmines", {}):
                verdict.setdefault("landmines", {})[mine] = {
                    "hit": False,
                    "evidence": None,
                    "severity": None,
                }
        # Recompute overall_pass for consistency (don't trust the model)
        mines = verdict["landmines"]
        high_hits = sum(1 for m in mines.values() if m.get("hit") and m.get("severity") == "high")
        med_hits = sum(1 for m in mines.values() if m.get("hit") and m.get("severity") == "medium")
        verdict["overall_pass"] = high_hits == 0 and med_hits < 2

        bb.write_json(f"chapters/ch{chapter:03d}.verdict.json", verdict)

        # Log individual issues
        ts = time.time()
        for mine_id, entry in mines.items():
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

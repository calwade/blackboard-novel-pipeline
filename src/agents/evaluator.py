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
        info_priority = self._read_rule("00-information-priority.md")

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
            "rules/00-information-priority.md",
        ]

        system = (
            f"你是业内以刁钻著称的资深网文主编，在本题材（{genre} · {era_label}）做了 20 年。\n"
            "你的工作方式：**刁钻但实事求是**。\n"
            "\n"
            "**核心原则**（按优先级）：\n"
            "1. **明显硬伤必须命中**：时间线错乱、人设崩塌、世界观矛盾、违反 setting 题材铁律——见一个抓一个，宁错杀不放过。\n"
            "2. **中等硬伤按定义判**：只在稿件确实违反 landmine 定义时命中；不要把『还能更好』当成硬伤。\n"
            "3. **干净稿件直接放行**：真正质量过硬的稿件可以 0 命中，你的工作不是为了找满 N 处。\n"
            "4. **每一条命中都必须附原文具体引文**作证据——没有证据 = 不能命中。\n"
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
            "# 叙事技术层专项自查（校准集数据表明 Evaluator 易漏此类）\n"
            "\n"
            "在给出 landmines 结论之前，必须就以下 4 条做一次**专项扫描**，"
            "哪怕其他层没问题，这些也可能独立命中：\n"
            "\n"
            "- **landmine_4 视角杂乱** — 同一场景中叙事视角是否至少跳换过一次？"
            "  典型模式：A 段写 主角 X 的内心活动 → B 段突然切到配角 Y 的心理 → "
            "  C 段又跳回 X。即使是短短一段配角视角插入，只要**中间无明确切换标记**"
            "  （空行、时间/地点提示、或显式的『与此同时，另一边』），就要命中。\n"
            "- **landmine_9 节奏失控与过渡生硬** — 同一章中场景之间是否有过渡？"
            "  典型模式：『林家耀喝完冻鸳鸯走出茶餐厅』下一段直接『当天夜里，大雨』"
            "  中间无一句过渡（如『接下来几个小时他在码头转了转』或『到了晚上』）"
            "  就是硬切，命中。\n"
            "- **landmine_8 冲突乏力** — 主角与对手的对抗是否"
            "  『敌人一出现就退场/认输/消失』？"
            "  对抗建立是否不到 100 字就结束？是否敌人不战而退？是则命中。\n"
            "- **landmine_15 爽点不足** — 高潮是否在 3 行之内解决？"
            "  是否赢得太轻松、敌人莫名其妙服软？胜利是否没有对应的代价或伤害？"
            "  是则命中。\n"
            "\n"
            "以上 4 条，如果文本有对应征兆但你在 landmines 打分时**忘了命中**，"
            "就是失职。确认完再给最终结论。\n"
            "\n"
            "# 命中稀疏化原则（防『见坏就扩散』）\n"
            "\n"
            "- 每一条命中**必须有独立于其他命中的证据**。不允许因为已经命中了 N 条，"
            "  就顺手把另一条也命中。\n"
            "- 如果你命中了 ≥6 个 landmine，请**回头逐条复核**：每一条的 evidence 是否\n"
            "  都是独立问题？如果多条的 evidence 指向**同一段文字的同一毛病**"
            "  （例如『内心独白太空泛』既命中 landmine_12 又命中 landmine_17 又命中 landmine_1），\n"
            "  只保留**最准确的那一条**，其余删掉。\n"
            "- AI 味重的稿件常见的错误是命中 8+ 条 landmine——这通常是**扩散**，\n"
            "  真实情况是 landmine_18 一条 high + 2-3 条相关 medium。不要凑数。\n"
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
            + "\n\n# 参考：信息源优先级（冲突仲裁协议）\n\n"
            + info_priority
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

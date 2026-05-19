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
  - state/current_status_card.md  — Lesson-3 authoritative "who knows what" snapshot (optional)
  - state/pending_hooks.md        — Lesson-3 active-hooks pool (optional)
  - rules/landmines.md        — universal landmines
  - rules/iron-laws.md        — universal iron laws

Writes:
  - state/chapters/ch{N:03d}.verdict.json
  - appends issues to state/issues.jsonl
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

from ._base import BaseAgent
from ._verdict_schema import LANDMINE_IDS, validate_verdict
from ..auditors.ai_slop_guard import static_scan_ai_rhythm
from ..blackboard import Blackboard


def _get_current_milestone(bb: Blackboard, chapter: int):
    """Return the PlotMilestone for `chapter` if plot_arc.yaml exists and
    a milestone is configured for that chapter, else None.

    Used by the Evaluator's iron_law_30 milestone check.
    """
    if not bb.exists("plot_arc.yaml"):
        return None
    try:
        from src.tools.plot_arc import read_plot_arc, derive_planner_context

        arc = read_plot_arc(bb.root)
    except Exception:
        return None
    if arc is None:
        return None
    try:
        ctx = derive_planner_context(arc, chapter)
    except ValueError:
        return None
    return ctx.get("current_milestone")


def _collect_recent_plans(bb: Blackboard, chapter: int, lookback: int = 5) -> tuple[list[dict], list[str]]:
    """Return ([plan summaries], [inputs_read paths]) for the last `lookback`
    plans before `chapter`. Each summary has chapter_type / locations / advances.

    Used by Evaluator's iron_law_29 (进度律) cross-check: if recent chapters
    keep recycling the same locations + advances, the chapter is "原地打转".
    """
    summaries: list[dict] = []
    inputs: list[str] = []
    if chapter <= 1:
        return summaries, inputs
    start = max(1, chapter - lookback)
    for n in range(start, chapter):
        rel = f"chapters/ch{n:03d}.plan.json"
        if not bb.exists(rel):
            continue
        try:
            p = bb.read_json(rel)
        except Exception:
            continue
        scenes = p.get("scenes") or []
        if not isinstance(scenes, list):
            scenes = []
        locs: list[str] = []
        advs: list[str] = []
        for s in scenes:
            if not isinstance(s, dict):
                continue
            loc = s.get("location")
            if isinstance(loc, str) and loc:
                locs.append(loc)
            for a in (s.get("advances") or []):
                if isinstance(a, str) and a:
                    advs.append(a)
        summaries.append(
            {
                "ch": n,
                "chapter_type": p.get("chapter_type", "?"),
                "locations": sorted(set(locs)),
                "advances": sorted(set(advs)),
            }
        )
        inputs.append(f"state/{rel}")
    return summaries, inputs


# ---------- iron_law_31 题材一致性律的机械预扫 helper ----------

# 中文人名候选范围：常见汉字（不含数字/标点/英文）。
# 限制在 2-4 字（覆盖 99% 中文姓名），避免吃下"主角设定/姓名背景"等长 token。
_NAME_CHARS = r"[\u4e00-\u9fa5]"
_PROTAGONIST_PATTERNS = [
    # "主角苏烬"、"姓名: 苏烬"、"姓名：苏烬"、"主角名：苏烬"、"主角姓名"等
    re.compile(rf"主角(?:姓名|名|名字)?[：:\s]*({_NAME_CHARS}{{2,4}})"),
    re.compile(rf"姓名[：:\s]+({_NAME_CHARS}{{2,4}})"),
    re.compile(rf"^[-*]?\s*\*?\*?姓名\*?\*?[：:\s]+({_NAME_CHARS}{{2,4}})", re.M),
]
# 时代锚点候选：覆盖末世/纪年/朝代年号/公元年份等。
# 注意：中文数字（一二三四五…十百千）必须显式匹配——\d 只覆盖 ASCII。
_CHINESE_DIGIT = "[一二三四五六七八九十百千零〇两]"
_ERA_ANCHOR_PATTERNS = [
    re.compile(rf"末世第(?:\d+|{_CHINESE_DIGIT}+)年"),
    re.compile(r"灰烬纪年"),
    re.compile(rf"(?:\d+|{_CHINESE_DIGIT}+)年(?:冬|春|夏|秋)"),
    re.compile(rf"(?:嘉靖|万历|崇祯|康熙|乾隆|光绪)(?:{_CHINESE_DIGIT}|\d){{1,4}}年"),
    re.compile(rf"公元(?:\d+|{_CHINESE_DIGIT}+)年"),
]


def _extract_era_keywords(era_text: str) -> dict:
    """Extract canonical genre anchors from era.md.

    Returns dict with 4 keys:
      - protagonist:  str (单个主角名) 或 ""（抽不到）
      - era_anchors:  list[str] (时代锚点字面量)
      - core_objects: list[str] (加粗 **X** 标记的短词，作为核心道具)
      - landmarks:    list[str] (## 标题里的地名)

    保守优先 — 抽不到就返回空 (后续 _check_genre_consistency 会跳过该维度)。
    宁可漏抽也不能误抽。
    """
    out: dict = {
        "protagonist": "",
        "era_anchors": [],
        "core_objects": [],
        "landmarks": [],
    }
    if not era_text:
        return out

    # protagonist：扫前 2000 字（开头段落）找首个匹配
    head = era_text[:2000]
    for pat in _PROTAGONIST_PATTERNS:
        m = pat.search(head)
        if m:
            out["protagonist"] = m.group(1)
            break

    # era_anchors：全文搜，去重保序
    seen_anchors: set[str] = set()
    for pat in _ERA_ANCHOR_PATTERNS:
        for m in pat.finditer(era_text):
            tok = m.group(0)
            if tok not in seen_anchors:
                seen_anchors.add(tok)
                out["era_anchors"].append(tok)

    # core_objects：抽 **X** 加粗标记。限制 1-5 字 + 仅中文（避免吃 **iron_law_31**
    # 这种英文标记或太长的 **整段说明** 文本）。
    bold_pat = re.compile(rf"\*\*({_NAME_CHARS}{{1,5}})\*\*")
    seen_obj: set[str] = set()
    for m in bold_pat.finditer(era_text):
        tok = m.group(1)
        if tok and tok not in seen_obj:
            seen_obj.add(tok)
            out["core_objects"].append(tok)

    # landmarks：扫 `## <标题>` 行里冒号后的词或裸地名
    # 形如 "## G22 服务区" / "## 港岛湾仔" / "## 主要场景：码头/茶餐厅"
    seen_lm: set[str] = set()
    for line in era_text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if not m:
            continue
        title = m.group(1)
        # 形如 "主要场景：码头 / 茶餐厅"
        if "：" in title or ":" in title:
            _, _, rhs = re.split(r"[：:]", title, maxsplit=1)[0], ":", title.split("：" if "：" in title else ":", 1)[1]
            for tok in re.split(r"[,，/、\s]+", rhs):
                tok = tok.strip()
                if 2 <= len(tok) <= 8 and tok not in seen_lm:
                    seen_lm.add(tok)
                    out["landmarks"].append(tok)
        else:
            # 裸标题地名（短词，不含分隔符）
            tok = title.strip()
            if 2 <= len(tok) <= 10 and tok not in seen_lm:
                seen_lm.add(tok)
                out["landmarks"].append(tok)

    return out


def _check_genre_consistency(chapter_text: str, kws: dict) -> dict:
    """Compare chapter_text against era keywords; return mechanical hit report.

    Returns:
      {
        "hit":      bool,           # any axis missed
        "severity": "high"|"medium"|None,
        "evidence": str|None,       # 若 hit=True 必有 evidence；否则 None
        "axes":     dict[str, ...], # 每个轴的 raw 命中情况（调试用）
      }

    severity 分级（per iron_law_31 spec）：
      - 主角名 mismatch        → high（致命）
      - 时代锚点全部 mismatch  → high
      - 核心道具命中率 < 50%   → high (≥3 处不符) / medium (1-2 处不符)
      - 仅地标 mismatch        → medium
    """
    axes: dict = {}

    # 主角
    has_protagonist = bool(kws.get("protagonist")) and (kws["protagonist"] in chapter_text)
    axes["protagonist"] = {
        "expected": kws.get("protagonist", ""),
        "hit": has_protagonist,
        "applicable": bool(kws.get("protagonist")),
    }

    # 时代锚点：全部不出现 = 命中
    era_anchors = kws.get("era_anchors") or []
    era_hits = [a for a in era_anchors if a in chapter_text]
    axes["era_anchors"] = {
        "expected": era_anchors,
        "hits": era_hits,
        "applicable": bool(era_anchors),
    }
    era_missed = bool(era_anchors) and len(era_hits) == 0

    # 核心道具：命中率
    core_objects = kws.get("core_objects") or []
    obj_hits = [o for o in core_objects if o in chapter_text]
    obj_total = len(core_objects)
    obj_ratio = (len(obj_hits) / obj_total) if obj_total > 0 else 1.0
    axes["core_objects"] = {
        "expected": core_objects,
        "hits": obj_hits,
        "ratio": obj_ratio,
        "applicable": obj_total > 0,
    }
    obj_underperform = obj_total > 0 and obj_ratio < 0.5
    obj_missed_count = obj_total - len(obj_hits)

    # 地标：任一未命中即 mismatch（弱信号）
    landmarks = kws.get("landmarks") or []
    lm_hits = [l for l in landmarks if l in chapter_text]
    axes["landmarks"] = {
        "expected": landmarks,
        "hits": lm_hits,
        "applicable": bool(landmarks),
    }
    lm_missed = bool(landmarks) and len(lm_hits) == 0

    # 判定 severity（按优先级取最重）
    severity: str | None = None
    evidence_parts: list[str] = []

    if axes["protagonist"]["applicable"] and not has_protagonist:
        severity = "high"
        evidence_parts.append(f"主角名'{kws['protagonist']}'未在正文出现")
    if era_missed:
        severity = "high"
        evidence_parts.append(f"时代锚点{era_anchors}全部未出现")
    if obj_underperform:
        # ≥3 处不符 → high；否则 medium
        if obj_missed_count >= 3:
            severity = "high"
        else:
            severity = severity or "medium"
        evidence_parts.append(
            f"核心道具命中率 {len(obj_hits)}/{obj_total} (<50%)"
        )
    if lm_missed and severity is None:
        severity = "medium"
        evidence_parts.append(f"全部地标{landmarks}未出现")

    hit = severity is not None
    return {
        "hit": hit,
        "severity": severity,
        "evidence": " / ".join(evidence_parts) if evidence_parts else None,
        "axes": axes,
    }


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
        # era.md：iron_law_31 题材一致性律的对照源。Evaluator 在 _handle_output
        # 中做机械预扫（_extract_era_keywords + _check_genre_consistency），
        # LLM 在 prompt 中也被提示复核。era.md 不存在时跳过本律（向后兼容）。
        era_md = bb.read_text("era.md") if bb.exists("era.md") else ""
        # Read Lesson-3 bookkeeping — these are the authoritative "who knows what"
        # snapshots. Critical for landmine_10 (反派信息越界 / 人设前后矛盾)
        # and landmine_13 (世界观矛盾). Absent/empty files are tolerated (chapter 1).
        status_card = bb.read_text("current_status_card.md") if bb.exists("current_status_card.md") else ""
        pending_hooks = bb.read_text("pending_hooks.md") if bb.exists("pending_hooks.md") else ""
        landmines = self._read_rule("landmines.md")
        iron_laws = self._read_rule("iron-laws.md")
        info_priority = self._read_rule("00-information-priority.md")

        try:
            setting = bb.read_yaml("setting.yaml")
        except Exception:
            setting = {}
        genre = setting.get("genre", "通用小说")
        era_label = setting.get("era", "")

        # iron_law_29 进度律：读最近 5 章 plan 做"原地打转"对比。
        # chapter==1 时返回空（无前 plan），向后兼容。
        recent_plans, recent_plans_inputs = _collect_recent_plans(bb, chapter, lookback=5)

        # plot_arc.yaml 是可选的全书坐标系（Oracle P0+P1 修复）。Evaluator 借
        # 它判断"本章是否 act_finale，必须收束所有 must_close 项"。不存在
        # 时 silently 跳过——iron_law_29 的核心仍是 recent_plans 对比。
        plot_arc_input: list[str] = []
        if bb.exists("plot_arc.yaml"):
            plot_arc_input.append("state/plot_arc.yaml")

        inputs_read = [
            f"state/{chapter_path}",
            "state/characters.yaml",
            "state/timeline.yaml",
            "state/iron-laws-extra.md",
            "rules/landmines.md",
            "rules/iron-laws.md",
            "rules/00-information-priority.md",
        ] + recent_plans_inputs + plot_arc_input
        # Only log the Lesson-3 bookkeeping files when they actually carry content.
        # Listing empty/absent files in inputs_read would falsely suggest to the
        # Inspector (and to future debuggers) that the Evaluator had a "who knows
        # what" snapshot to cross-check against — they'd then mis-attribute any
        # missed landmine_10 hit to a reading failure rather than to a genuinely
        # absent card (e.g. chapter 1 before StatusCardUpdater has ever run).
        if status_card.strip():
            inputs_read.append("state/current_status_card.md")
        if pending_hooks.strip():
            inputs_read.append("state/pending_hooks.md")
        # era.md drives iron_law_31 (题材一致性律). List it only when present
        # so the Inspector accurately reflects what the Evaluator actually had.
        if era_md.strip():
            inputs_read.append("state/era.md")

        system = (
            f"你是网文质检员，本题材（{genre} · {era_label}）方向。\n"
            "默认立场=**拒稿**。任务=机械核对 19 条 landmine + 4 项静态指标。\n"
            "找不到 ≥3 个硬伤就是失职。漏报远比扩散危险。\n"
            "你与 Generator 共享训练偏好——你读起来『流畅有节奏』≈ AI 节奏病。\n"
            "你只信稿件本身，不听『作者本意』的辩解。\n"
            "\n"
            "# 4 步规程（按顺序执行）\n"
            "\n"
            "**步骤 1**：读 user prompt 末尾的机械扫描数字（Python 已经数完了，"
            "阈值见该表）。任一指标超 moderate → landmine_18 必命中；超 severe "
            "→ severity=high；2+ 项 moderate → severity≥medium。evidence 写"
            "『指标 X = N，超过健康上限 M』+ 原文最典型片段。\n"
            "\n"
            "**步骤 2**：核对其他 18 条 landmine。每条独立打分：hit / evidence"
            "（必须原文引文 ≥10 字）/ severity。专项重点扫描（校准集证明易漏）：\n"
            "- **landmine_4 视角杂乱** — 同场景视角是否至少跳换一次？"
            "  A 段主角内心 → B 段配角心理 → C 段跳回主角，"
            "  中间无空行/时间地点提示/『与此同时，另一边』即命中。\n"
            "- **landmine_9 过渡生硬** — 场景间是否有过渡？"
            "  『主角喝完冻鸳鸯走出茶餐厅』下一段直接『当天夜里』，"
            "  中间无『接下来几个小时…』或『到了晚上』即硬切命中。\n"
            "- **landmine_8 冲突乏力** — 对抗是否『敌人一出现就退场/认输/消失』？"
            "  对抗建立 <100 字结束、敌人不战而退即命中。\n"
            "- **landmine_15 爽点不足** — 高潮是否 3 行内解决？"
            "  赢得太轻松、敌人莫名服软、胜利无代价即命中。\n"
            "\n"
            "**步骤 3**：交叉验证 characters / timeline / iron-laws / 状态卡 / 伏笔池：\n"
            "- 主角行为违背 characters.yaml redlines/traits → landmine_10 或 11。\n"
            "- 年份/事件/物价与 timeline.yaml 不符 → landmine_13。\n"
            "- 违反 iron-laws-extra → landmine_10 或 13，evidence 注明 iron_law_extra_N。\n"
            "- 若 `current_status_card.md` 的「已知真相」表明某信息**反派不应知道**，"
            "  而章节中反派表现出知情（或反向：只有反派知道的信息，主角在无合理推理链下"
            "  突然知晓），必须在 landmine_10 命中。evidence 同时引章节原文和"
            "  状态卡对应条目（如 `状态卡·已知真相·『X 情报』反派知否=否`）。\n"
            "- 若 `pending_hooks.md` 的活跃伏笔与本章矛盾——回收方式与伏笔类型/状态不符，"
            "  或推进方向与伏笔表既定走向相反——必须 landmine_10 或 13 命中，"
            "  evidence 同时引原文和对应 hook_id 行。\n"
            "- 状态卡/伏笔池**未提供**（首章或尚未产出）时不适用本两条。\n"
            "- 题材一致性（iron_law_31）：检查主角名 / 时代锚点 / 核心道具是否与 era.md 一致。"
            "  LLM 训练直觉常让现代末世跑偏成古风/玄幻，机械预扫已在 verdict 标记，"
            "  你需要复核并在 evidence 里给出原文引文（例如 era.md 主角名是『苏烬』但本章"
            "  始终称『无名』即必须命中）。\n"
            "\n"
            "**步骤 4**：决定 overall_pass + top_3_fixes：\n"
            "- 任何 high 命中 → false；2+ medium 命中 → false；其他 → true。\n"
            "- 不确定某条算不算 medium，按 medium 算（默认偏向 false）。\n"
            "- top_3_fixes 的 where ≥6 字原文引文，what ≥10 字具体改写方向，"
            "  不足 3 个就少于 3 个，绝不能用 `…` / `...` / 空字符串占位。\n"
            "\n"
            "# 反偷懒条款\n"
            "\n"
            "- 『全 false + pass=true』是有效输出，但你必须举证：4 项静态指标都"
            "  低于阈值，且 18 条 landmine 都无原文证据。\n"
            "- 4 项静态指标超标但你让 landmine_18 hit=false 是失职。\n"
            "- 不要害怕命中数量；AI 味灾难章节确实可能 4-6 个 landmine 同时命中。\n"
            "\n"
            "# 输出格式（user prompt 末尾还会再给一次 JSON 结构）\n"
            "严格 JSON。必须包含所有 19 个 landmine_N 键。evidence 未命中为 null。\n"
            "\n"
            "# 参考：通用 24 条铁律\n\n"
            + iron_laws
            + "\n\n# 参考：题材特有铁律（由 setting 注入）\n\n"
            + iron_laws_extra
            + "\n\n# 参考：信息源优先级（冲突仲裁协议）\n\n"
            + info_priority
        )

        # NOTE: we intentionally do NOT embed a skeleton with "…" placeholders
        # in the user prompt schema — that was the root cause of the "Evaluator
        # returned skeleton" bug. Instead we describe the required keys.
        # Build an optional "authoritative current-state" block. We only include
        # these sections when the files carry content — an empty block would
        # dilute the prompt and risk the LLM fabricating violations against a
        # non-existent snapshot.
        bookkeeping_block = ""
        if status_card.strip():
            bookkeeping_block += (
                "\n# 当前时间点权威状态卡 (current_status_card.md)\n"
                "> 以下是章节结束时的『谁知道什么 / 当前敌我 / 活跃伏笔』权威快照。\n"
                "> 用于交叉验证『反派信息越界』『伏笔回收不符』等问题。\n\n"
                f"```markdown\n{status_card}\n```\n"
            )
        if pending_hooks.strip():
            bookkeeping_block += (
                "\n# 活跃伏笔池 (pending_hooks.md)\n"
                "> 以下是进入本章前尚未回收的伏笔池。本章对任一 hook_id 的推进/回收\n"
                "> 必须与其既定类型和当前状态自洽。\n\n"
                f"```markdown\n{pending_hooks}\n```\n"
            )

        # Run the static AI-rhythm scanner so the LLM sees the deterministic
        # numbers Python already counted. Reused later in _handle_output for
        # the override post-process; running once here keeps _build_prompts
        # honest about what the LLM was shown.
        scan = static_scan_ai_rhythm(chapter_text)
        m = scan["metrics"]
        scan_block = (
            "\n\n# 机械扫描结果（这是 Python 数出来的真实数字）\n\n"
            f"- 否定对比 '不是X，是Y'：**{m['neg_contrast']}** 次"
            "（健康 ≤2 / moderate ≥5 / severe ≥10）\n"
            f"- 破折号 '——'：**{m['emdash']}** 次"
            "（健康 ≤8 / moderate ≥20 / severe ≥30）\n"
            f"- 短段 <30 字占比：**{m['short_para_ratio']*100:.1f}%**"
            "（健康 ≤20% / moderate ≥35% / severe ≥50%）\n"
            f"- 明喻 '像X'：**{m['simile']}** 次"
            "（健康 ≤15 / moderate ≥25 / severe ≥40）\n"
            "\n（静态扫描的 severe 命中会被流水线后处理强制写入 verdict，"
            "但你的 LLM 判断仍要据此决定 landmine_18 在 evidence 里写什么细节。）\n"
        )

        # iron_law_29 进度律对照表：把最近 5 章 plan 摘要喂给 LLM 让它
        # 机械判断"原地打转"。chapter<=1 或全部 plan 缺失时不发射这一段。
        progress_law_block = ""
        if recent_plans:
            lines = [
                "\n\n# 最近 5 章 plan 对照表（用于 iron_law_29 进度律检测）",
                "",
                "| ch | chapter_type | locations | advances |",
                "|---|---|---|---|",
            ]
            for r in recent_plans:
                locs_str = ",".join(r["locations"])[:80] or "（无）"
                advs_str = ",".join(r["advances"]) or "（无）"
                lines.append(f"| {r['ch']} | {r['chapter_type']} | {locs_str} | {advs_str} |")
            lines.append("")
            lines.append(
                "判断本章是否触发 iron_law_29（进度律）：\n"
                "- 本章 scenes[].location 是否与上一章完全重叠？\n"
                "- 本章 advances 集合是否与上一章完全相同？\n"
                "- 是否连续 3+ 章相同 chapter_type（无『战斗』『回收』穿插）？\n"
                "- 距离最近一次 chapter_type ∈ {战斗, 回收} 是否已超过 4 章？\n"
                "若任一命中，必须在最匹配的现有 landmine（通常是 landmine_15 节奏崩溃 / "
                "landmine_8 冲突乏力 / landmine_4 视角杂乱 之一）hit=true，"
                "evidence 必须**显式标注 `iron_law_29 进度律`**并引用本表中相邻两章的 "
                "location/advances 字段说明重叠。"
            )
            progress_law_block = "\n".join(lines) + "\n"

        # iron_law_30 全局节奏律：最近 5 章 dna anchor 分布 + milestone 兑现检查。
        # Oracle P3 修复"长跑被动症"——每 5 章必须命中 1 次 dna value_anchor。
        # 推断逻辑复用 Planner 的 _infer_anchor_from_plan（保守规则映射）。
        global_rhythm_block = ""
        try:
            from .planner import _infer_anchor_from_plan
        except Exception:
            _infer_anchor_from_plan = None  # type: ignore

        if _infer_anchor_from_plan is not None and recent_plans:
            inferred: list[tuple[int, Optional[str]]] = []
            anchor_counts: dict[str, int] = {
                "爽感": 0, "掌控感": 0, "黑色幽默": 0, "生存智慧": 0
            }
            none_chapters: list[int] = []
            # recent_plans 由 _collect_recent_plans 产生，含 ch/chapter_type/scenes 摘要
            # 但不带原始 advances 列表的形态——用 plan.json 重新读
            for r in recent_plans:
                n = r["ch"]
                rel = f"chapters/ch{n:03d}.plan.json"
                if not bb.exists(rel):
                    continue
                try:
                    plan = bb.read_json(rel)
                except Exception:
                    continue
                a = _infer_anchor_from_plan(plan)
                inferred.append((n, a))
                if a:
                    anchor_counts[a] = anchor_counts.get(a, 0) + 1
                else:
                    none_chapters.append(n)

            has_payoff = anchor_counts.get("爽感", 0) > 0 or anchor_counts.get("掌控感", 0) > 0
            payoff_status = "是" if has_payoff else "否（命中 iron_law_30·全局节奏律）"

            anchor_dist_lines = []
            for ch_n, a in inferred:
                anchor_dist_lines.append(f"  - ch{ch_n}: {a or '无（保守判定为 None）'}")

            block_lines = [
                "\n# 全局节奏检测（iron_law_30 用）",
                "",
                f"- 最近 {len(inferred)} 章 anchor 推断：",
                *anchor_dist_lines,
                f"- anchor 计数：爽感×{anchor_counts.get('爽感',0)} / "
                f"掌控感×{anchor_counts.get('掌控感',0)} / "
                f"黑色幽默×{anchor_counts.get('黑色幽默',0)} / "
                f"生存智慧×{anchor_counts.get('生存智慧',0)}（None×{len(none_chapters)}）",
                f"- 是否含爽感 / 掌控感（最近窗口）：{payoff_status}",
                "",
                "判定规则（按 iron_law_30）：",
                "- 最近 5 章 0 次爽感 + 0 次掌控感 → severity=medium",
                "- 最近 8+ 章无任一 dna anchor → severity=high",
                "- evidence 必须**显式标注 `iron_law_30 全局节奏律`**并引用上面的计数表说明缺口。",
            ]

            # milestone 兑现检测：本章是否是 milestone？若是，必须检查正文是否含 ≥150 字奇观时刻
            milestone_for_this_chapter = _get_current_milestone(bb, chapter)
            if milestone_for_this_chapter is not None:
                ms = milestone_for_this_chapter
                block_lines.extend([
                    "",
                    "⚠ **本章是 plot_arc.yaml 配置的 milestone 章节**",
                    f"- milestone.type：{ms.type}",
                    f"- milestone.anchor：{ms.anchor}",
                    f"- milestone.beat（必须兑现）：{ms.beat.strip()[:300]}",
                    "- **必须检查正文是否兑现 milestone.beat**：",
                    f"  - 是否有 ≥150 字直接对应『{ms.type}』的奇观段落？",
                    f"  - 是否真的体现了『{ms.anchor}』anchor（而非走过场）？",
                    "- 未兑现 = severity=high（直接判 fail），evidence 引正文最相关段落 + 标注 "
                    "`iron_law_30 milestone 未兑现`。",
                ])

            global_rhythm_block = "\n".join(block_lines) + "\n"

        user = (
            f"# 本章节（第 {chapter} 章）全文\n\n"
            f"{chapter_text}\n\n"
            f"# 人物档案 (characters.yaml)\n\n```yaml\n{characters}\n```\n\n"
            f"# 时间线 (timeline.yaml)\n\n```yaml\n{timeline}\n```\n"
            f"{bookkeeping_block}"
            f"{progress_law_block}"
            f"{global_rhythm_block}"
            f"\n# 19 个雷点完整定义 (rules/landmines.md)\n\n"
            f"{landmines}\n\n"
            f"# 输出 JSON 结构（严格遵守）\n\n"
            "必须包含以下字段：\n"
            "- `overall_pass` (boolean)\n"
            "- `landmines`：对象，包含 `landmine_1` 到 `landmine_19` 全部 19 键，\n"
            "  每个值是 `{hit: bool, evidence: string|null, severity: 'high'|'medium'|'low'|null}`\n"
            "- `top_3_fixes`：数组，0-3 个元素；每个元素是\n"
            "  `{where: <原文引文，至少 6 个字>, what: <改写方向，至少 10 个字>}`\n"
            "\n"
            "✋ 不要复用示例占位符 — 每一处 evidence / where 都必须是你从上方章节原文中找到的真实引文。\n"
            + scan_block
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

        # Patch 1：静态扫描命中直接覆盖 LLM 主观判断
        # 原理：LLM 数不清楚 42 个破折号但 Python 能。机械事实归 Python，
        # 价值判断归 LLM。任何静态扫描的 severe 命中都强制 landmine_18=high
        # + overall_pass=false。这是 Oracle 诊断的「静态扫描成果不流通」修复。
        chapter_text = bb.read_text(f"chapters/ch{chapter:03d}.md")
        scan = static_scan_ai_rhythm(chapter_text)
        # Guard against trivially-short fixture chapters (test seeds, sanity stubs).
        # Real chapters are 2000+ chars / dozens of paragraphs. With <5 paragraphs
        # the short_para_ratio metric is meaningless (1 paragraph = 100% short).
        # Skip the override entirely for such inputs so unit-test fixtures
        # ("# t\n\n正文") aren't force-failed.
        meaningful_scan = scan["metrics"]["total_paras"] >= 5
        severe_hits = (
            [h for h in scan["hits"] if h["severity"] == "severe"]
            if meaningful_scan
            else []
        )
        moderate_hits = (
            [h for h in scan["hits"] if h["severity"] == "moderate"]
            if meaningful_scan
            else []
        )

        if severe_hits or len(moderate_hits) >= 2:
            # severe 命中 → high（强制 overall_pass=false）
            # 仅 moderate 累积（≥2）→ medium（不强制翻车，与已有 LLM medium 合并计数）
            severity = "high" if severe_hits else "medium"
            evidence_parts = []
            for h in severe_hits + moderate_hits:
                evidence_parts.append(
                    f"{h['criterion']}={h['count']} (健康上限 {h['threshold']})"
                )
            verdict["landmines"]["landmine_18"] = {
                "hit": True,
                "evidence": "静态扫描机械命中：" + " / ".join(evidence_parts),
                "severity": severity,
                "_source": "static_scan",
            }
            # high 命中按规则就是 fail
            if severity == "high":
                verdict["overall_pass"] = False
            elif severity == "medium":
                # medium：与现有 LLM 命中合并；如果已经有 ≥1 个 medium，达到 2+ 翻 false
                med_count = sum(
                    1
                    for mid, m in verdict["landmines"].items()
                    if m.get("hit") and m.get("severity") == "medium"
                )
                if med_count >= 2:
                    verdict["overall_pass"] = False
            # 把静态命中追加到 top_3_fixes（如果还有空位）
            if "top_3_fixes" not in verdict or verdict["top_3_fixes"] is None:
                verdict["top_3_fixes"] = []
            slots_left = 3 - len(verdict["top_3_fixes"])
            for h in (severe_hits + moderate_hits)[:max(0, slots_left)]:
                where = (h.get("snippet") or h["criterion"])[:60]
                if len(where) < 6:
                    where = f"{h['criterion']} 命中（count={h['count']}）"
                verdict["top_3_fixes"].append(
                    {
                        "where": where,
                        "what": h.get("suggested_direction", "节奏修复（删冗余/合并短段/降密度）"),
                        "_source": "static_scan",
                    }
                )

        # Patch 2 (iron_law_31)：题材一致性机械预扫
        # 与 Patch 1 同源思路：LLM 训练直觉容易忽略"主角名/时代锚点"这类宏观偏移
        # （读起来很流畅但已经写成另一个题材了）。Python 直接用关键词命中数说话。
        # era.md 缺失时跳过（首次跑 / 旧 preset 兼容）。
        try:
            era_text = bb.read_text("era.md") if bb.exists("era.md") else ""
        except Exception:
            era_text = ""
        if era_text.strip():
            kws = _extract_era_keywords(era_text)
            # 只有抽到任一关键词才检查（保守：抽不到就当无信号，不误报）
            has_signal = (
                bool(kws.get("protagonist"))
                or bool(kws.get("era_anchors"))
                or bool(kws.get("core_objects"))
            )
            if has_signal:
                consistency = _check_genre_consistency(chapter_text, kws)
                if consistency["hit"]:
                    # 写入 verdict.iron_law_violations 数组（不挤占 19 个 landmine 槽位）
                    iron_law_violations = verdict.get("iron_law_violations") or []
                    if not isinstance(iron_law_violations, list):
                        iron_law_violations = []
                    iron_law_violations.append({
                        "iron_law": "iron_law_31",
                        "severity": consistency["severity"],
                        "evidence": consistency["evidence"],
                        "_source": "mechanical_scan",
                        "axes": consistency["axes"],
                    })
                    verdict["iron_law_violations"] = iron_law_violations
                    # high 严重度直接判 fail
                    if consistency["severity"] == "high":
                        verdict["overall_pass"] = False
                    # 也追加到 top_3_fixes（若仍有空位），让 Fixer 看到这条
                    if "top_3_fixes" not in verdict or verdict["top_3_fixes"] is None:
                        verdict["top_3_fixes"] = []
                    if len(verdict["top_3_fixes"]) < 3:
                        verdict["top_3_fixes"].append({
                            "where": (consistency["evidence"] or "iron_law_31")[:60],
                            "what": (
                                "题材一致性修复：把主角名/时代锚点/核心道具改回 era.md "
                                "约定（如主角应为『苏烬』/时代为『末世第三年』）"
                            ),
                            "_source": "iron_law_31_scan",
                        })

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

"""AISlopGuard — background auditor for AI-flavored writing.

Scans finalized chapter for AI-slop patterns only (not the full landmine list).
Fresh window, runs independently of the main plan/gen/eval/fix cycle.

Reads:
  - state/chapters/ch{N:03d}.md

Writes:
  - state/fixes/ch{N:03d}.slop-patch.md  (human-readable patch proposal)

This is the Lesson-4 artifact: a separate file users can inspect / apply
as if it were a PR from a background agent.
"""
from __future__ import annotations

import json
import re

from ..agents._base import BaseAgent
from ..blackboard import Blackboard

# ---------------------------------------------------------------------------
# Static AI-rhythm scanner (non-LLM)
# ---------------------------------------------------------------------------
#
# 2026 LLM 节奏痕迹专项扫描。因为 Generator / Evaluator / AISlopGuard 三个
# agent 共享同一套训练偏好（对"优美"的定义），对于这四类确定性痕迹会集体
# 灯下黑。用纯正则 + 段落统计做兜底审计，结果拼在 LLM patch 前面，确保
# 可被人看到、被下游 Fixer 修。
#
# 阈值基于「健康网文密度」（每章 ~5000 字）手工标定，后续可用
# scripts/calibrate_slop_thresholds.py 在全量章节上校准。
SLOP_THRESHOLDS = {
    "neg_contrast": {"moderate": 5, "severe": 10},   # 不是X，是Y
    "emdash":       {"moderate": 20, "severe": 30},  # ——
    "short_para":   {"moderate": 0.35, "severe": 0.50},  # <30 字成段占比
    "simile":       {"moderate": 25, "severe": 40},  # 像X
}


def static_scan_ai_rhythm(text: str) -> dict:
    """
    非 LLM 静态扫描 4 类确定性 AI 节奏痕迹。

    返回 dict:
      - hits: list of {criterion, severity, count, threshold, suggested_direction, ...}
      - metrics: 原始测量值（neg_contrast / emdash / short_para_ratio / simile / total_paras）

    criterion 命名用 rhythm_neg_contrast / rhythm_emdash / rhythm_short_para /
    rhythm_simile，避免与 landmine_N 冲突。
    """
    # 1. 段落切分（去掉标题行 # 开头）
    paras = [p.strip() for p in text.split("\n\n") if p.strip() and not p.lstrip().startswith("#")]
    total_paras = max(len(paras), 1)

    # 2. 剥离对话引号内容（避免对话里被打断的破折号 "你——" 误报为描写节奏切分）
    text_no_dialogue = re.sub(r'"[^"]*"', "", text)
    text_no_dialogue = re.sub(r'「[^」]*」', "", text_no_dialogue)
    text_no_dialogue = re.sub(r'"[^"]*"', "", text_no_dialogue)

    # 3. 四项计数
    #    - neg_contrast: "不是 X，[而]是 Y" 句式
    neg_contrast = re.findall(
        r"不是[^，。,\n]{1,20}[，,][^。\n]{0,3}?是[^。\n]{1,40}",
        text,
    )
    emdash = text_no_dialogue.count("——")
    short_paras = [p for p in paras if len(p) < 30]
    short_ratio = len(short_paras) / total_paras
    similes = re.findall(r"像[^，。\n]{1,30}", text)

    metrics = {
        "neg_contrast": len(neg_contrast),
        "emdash": emdash,
        "short_para_ratio": round(short_ratio, 3),
        "simile": len(similes),
        "total_paras": total_paras,
    }

    hits: list[dict] = []

    def _grade(value, thresholds):
        if value >= thresholds["severe"]:
            return "severe"
        if value >= thresholds["moderate"]:
            return "moderate"
        return None

    # neg_contrast
    sev = _grade(len(neg_contrast), SLOP_THRESHOLDS["neg_contrast"])
    if sev:
        hits.append({
            "criterion": "rhythm_neg_contrast",
            "severity": sev,
            "count": len(neg_contrast),
            "threshold": SLOP_THRESHOLDS["neg_contrast"]["moderate"],
            "snippet": (neg_contrast[0] if neg_contrast else "")[:60],
            "suggested_direction": "合并'不是X，是Y'为单句陈述；全章保留至多 2 处作点睛",
        })
    # emdash
    sev = _grade(emdash, SLOP_THRESHOLDS["emdash"])
    if sev:
        hits.append({
            "criterion": "rhythm_emdash",
            "severity": sev,
            "count": emdash,
            "threshold": SLOP_THRESHOLDS["emdash"]["moderate"],
            "suggested_direction": "删除 70% 破折号；用逗号/句号重构节奏；破折号仅保留对话被打断",
        })
    # short_para
    sev = _grade(short_ratio, SLOP_THRESHOLDS["short_para"])
    if sev:
        hits.append({
            "criterion": "rhythm_short_para",
            "severity": sev,
            "count": f"{short_ratio*100:.1f}%",
            "threshold": f"{SLOP_THRESHOLDS['short_para']['moderate']*100:.0f}%",
            "suggested_direction": "合并相邻短段为完整叙述段（3-5 行）；单独成段留给转折/悬念/对话",
        })
    # simile
    sev = _grade(len(similes), SLOP_THRESHOLDS["simile"])
    if sev:
        hits.append({
            "criterion": "rhythm_simile",
            "severity": sev,
            "count": len(similes),
            "threshold": SLOP_THRESHOLDS["simile"]["moderate"],
            "suggested_direction": "删除 40% 明喻；优先保留有画面感的点睛，删掉装饰性的",
        })

    return {"hits": hits, "metrics": metrics}


# Subset of landmines relevant to AI-slop only. Kept as inline text so
# the auditor's prompt stays small & focused.
AI_SLOP_CRITERIA = """
1. 「了」字泛滥 — 每段 ≥5 个「了」或整段都是「VV 了」式的机械时态；单个「了」不算
2. 固定句式连续 — 同一结构（主谓宾、动宾式）连续 3 句以上完全相同
3. 形容词堆砌 — 单个名词前挂 2 个以上修饰词（❌「那道温柔的、悠长的、宛如微风的叹息」）
4. 四字成语串烧 — 连续 3 个或更多的四字词组（❌「气势汹汹、杀气腾腾、怒不可遏」）
5. 机械排比 — 「一VO，一VO，一VO」三连、「不X，不Y，不Z」三连
6. 转折词滥用 — 虽然/但是/然而 在一段内出现 2 次以上
7. 空泛抒情 — 「内心如同翻江倒海」「心头涌起万千思绪」等套话
8. 模板化开篇 — 「夜深了」「阳光洒在」「时光流逝」等
9. AI 式说教 — 段末或章末的「这个故事告诉我们...」/「每个人都...」
10. 过度完美逻辑 — 段内每句之间都用「因为...所以...」链接，没有呼吸
11. 高疲劳词过度 — 同一「高识别疲劳词」在单章中出现 ≥2 次（刻意回环除外）。
    黑名单（每词单章 ≤1 次）：
    - 表情：冷笑、嗤笑、勾起嘴角、眉头一皱、瞳孔骤缩、倒吸一口凉气
    - 群像：满场死寂、全场震惊、众人哗然、众人瞠目结舌、齐齐后退
    - 比喻：蝼蚁、砧板上的鱼肉、如丧考妣、面如死灰
    - 动作：轰然炸裂、轰然倒塌、拔地而起、凭空消失
    - 心理：内心翻江倒海、心头涌起、心如刀绞、不寒而栗、毛骨悚然
    - 气势：气势如虹、杀气腾腾、霸气外露、睥睨天下、王霸之气
    群像反应必须改写成 1-2 个具体角色的身体反应/判断偏差/利益震荡，不允许笼统。
"""


class AISlopGuard(BaseAgent):
    name = "ai_slop_guard"
    temperature = 0.2
    response_format = "json"
    max_tokens = 8192

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        chapter_path = f"chapters/ch{chapter:03d}.md"
        text = bb.read_text(chapter_path)
        inputs_read = [f"state/{chapter_path}"]

        # Static pre-scan: tell the LLM the 4 deterministic rhythm metrics
        # have already been measured mechanically, so it shouldn't waste
        # hits on them and can focus on other AI-slop categories.
        static_scan = static_scan_ai_rhythm(text)
        metrics = static_scan["metrics"]
        prescan_note = (
            "\n\n# 已机械扫描的 4 项节奏指标（你不用重复报）\n"
            f"- 否定对比 '不是X，是Y': {metrics['neg_contrast']} 次\n"
            f"- 破折号 '——': {metrics['emdash']} 次\n"
            f"- 短段（<30 字）占比: {metrics['short_para_ratio']*100:.1f}%（共 {metrics['total_paras']} 段）\n"
            f"- 明喻 '像X': {metrics['simile']} 次\n"
            "这四类静态扫描器已经会生成补丁条目。你的职责是补充**其他 AI 味问题**"
            "（了字堆砌、固定句式、形容词堆砌、高疲劳词、空泛抒情、AI 式说教等），"
            "不要重复报上述四类。\n"
        )

        system = (
            "你是专门扫描 AI 味的独立审计员。\n"
            "你的职责范围只有 AI 味——人设、时间线、剧情主线等问题不归你管。\n"
            "\n"
            "# AI 味判据（你只看这些）\n"
            + AI_SLOP_CRITERIA
            + prescan_note
            + "\n\n"
            "# 输出要求\n"
            "严格 JSON。包含：slop_score（0 无 AI 味 — 10 满屏 AI 味）、\n"
            "hits（每条：criterion_id、severity、snippet、suggested_rewrite）。\n"
            "\n"
            "**约束**：\n"
            "1. hits 数组最多 8 条，只报 severity=moderate 或 severe 的；minor 不报\n"
            "2. suggested_rewrite 必须严格 ≤ snippet 字节长度，绝对不允许变长\n"
            "3. suggested_rewrite 必须保留 snippet 中的所有名词、人名、地名、核心意象\n"
            "4. snippet ≤ 60 字\n"
            '5. severity 取值为 "moderate" 或 "severe"（minor 直接删掉不输出）\n'
            "\n"
            "**自拒条款**：如果你想不到明显更好的改写——改完只是换个说法、长度相当、\n"
            "可改可不改——就不要输出该条 hit。每条 hit 都必须有质变。\n"
            "如果某类未命中，不要强行编造。\n"
            "\n"
            "✋ 输出前逐条自查:\n"
            "A. suggested_rewrite 长度是否 ≤ snippet 长度？若否，重写或删除本条。\n"
            "B. 是否保留了所有人名、地名、核心名词？若否，重写。\n"
            "C. 是否确实显著优于原文？若只是换个写法，删除本条 hit。\n"
        )

        user = (
            f"# 待审章节（第 {chapter} 章）\n\n{text}\n\n"
            f"# 输出 JSON 结构示例\n"
            + json.dumps(
                {
                    "slop_score": 3,
                    "hits": [
                        {
                            "criterion_id": 1,
                            "severity": "moderate",
                            "snippet": "……",
                            "suggested_rewrite": "……",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        s = raw.strip()
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
        if m:
            s = m.group(1)
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            # Likely truncated JSON — record the failure transparently rather
            # than silently returning 0 hits. User sees a patch file with a
            # note to re-run the auditor.
            obj = {
                "slop_score": -1,
                "hits": [],
                "_parse_error": str(e),
                "_raw_excerpt": raw[-500:],
            }

        # Re-run static scan here (cheap pure regex) so the patch file can
        # render the mechanical hits in front of the LLM hits. This keeps
        # _build_prompts and _handle_output both stateless.
        chapter_path = f"chapters/ch{chapter:03d}.md"
        text = bb.read_text(chapter_path)
        static_scan = static_scan_ai_rhythm(text)
        static_hits = static_scan["hits"]
        metrics = static_scan["metrics"]

        # Render as a human-readable patch file (Lesson 4: visible artifact)
        md_lines = [
            f"# AISlopGuard 补丁 · 第 {chapter} 章",
            "",
            f"**AI 味分数**：{obj.get('slop_score', 'N/A')} / 10",
            "",
            f"**命中数**：{len(obj.get('hits', []))}",
            "",
        ]

        # 静态优先：先渲染机械扫描命中的 4 类节奏痕迹（Generator/Evaluator/AISlopGuard
        # 三个 LLM 的灯下黑兜底），再接 LLM 的判断。
        if static_hits:
            md_lines.extend([
                "## 机械扫描命中（静态阈值）",
                "",
                "> 以下 4 类为 2026 LLM 节奏痕迹，由 `static_scan_ai_rhythm` 纯正则识别。",
                "> 指标来自全文统计，绕过 LLM 主观判断。",
                "",
                f"- neg_contrast={metrics['neg_contrast']} · "
                f"emdash={metrics['emdash']} · "
                f"short_para={metrics['short_para_ratio']*100:.1f}% · "
                f"simile={metrics['simile']} · "
                f"total_paras={metrics['total_paras']}",
                "",
            ])
            for i, h in enumerate(static_hits, 1):
                md_lines.append(
                    f"### 静态 {i} — {h['criterion']} · {h['severity']} "
                    f"(count={h['count']}, threshold={h['threshold']})"
                )
                md_lines.append("")
                if h.get("snippet"):
                    md_lines.append(f"**样本**：{h['snippet']}")
                    md_lines.append("")
                md_lines.append(f"**修复方向**：{h['suggested_direction']}")
                md_lines.append("")
            md_lines.append("---")
            md_lines.append("")
            md_lines.append("## LLM 补充命中")
            md_lines.append("")

        for i, h in enumerate(obj.get("hits", []), 1):
            sev = h.get("severity", "moderate")
            md_lines.append(f"## 问题 {i} — 规则 {h.get('criterion_id', '?')} · 严重度 {sev}")
            md_lines.append("")
            md_lines.append(f"**原文**：{h.get('snippet', '')}")
            md_lines.append("")
            md_lines.append(f"**建议改写**：{h.get('suggested_rewrite', '')}")
            md_lines.append("")

        bb.write_text(f"fixes/ch{chapter:03d}.slop-patch.md", "\n".join(md_lines))

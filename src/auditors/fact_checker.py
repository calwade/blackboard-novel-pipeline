"""FactChecker — on-demand fact-verification auditor (A-1).

Lesson-3 boundary & design decision:
  The creative pipeline (Planner / Generator / Summarizer / Evaluator /
  Fixer) has ZERO internet access. Worldbuilding facts are pre-loaded
  in setting pack era.md / timeline.yaml, which keeps plan→prose
  deterministic and reproducible. Evaluator in particular MUST NOT
  change its verdict based on external search — that would make the
  0-temperature rubric dependent on live network state.

  FactChecker sits OUTSIDE that loop. It runs as an optional auditor
  (alongside AISlopGuard / CharacterGuard) AFTER Evaluator finishes,
  and ONLY when the verdict flagged landmine_13 (world/era drift) with
  moderate-or-higher severity. Its output is a patch file — human
  readable, advisory, NOT a pass/fail gate.

  Single-shot per chapter: skill #20 warned against per-sentence search
  loops ("Context anxiety"). The auditor extracts 1-3 concrete factual
  claims from the landmine_13 evidence, fires ONE Perplexity query per
  claim (max 3), compares each claim against the search result, and
  writes a consolidated fact-patch.md.

Reads:
  - state/chapters/ch{N:03d}.md              — the prose under audit
  - state/chapters/ch{N:03d}.verdict.json    — for landmine_13 evidence
  - state/era.md (if present)                — context for Perplexity

Writes:
  - state/fixes/ch{N:03d}.fact-patch.md      — human-readable report

Graceful degradation:
  - PERPLEXITY_API_KEY absent        → write a stub patch explaining why
  - Evaluator didn't hit landmine_13 → write a "no fact-check needed" stub
  - WebSearchUnavailable at runtime  → record the error in the patch
"""
from __future__ import annotations

import json
from typing import Any

from ..agents._base import BaseAgent
from ..blackboard import Blackboard
from ..tools import websearch


class FactChecker(BaseAgent):
    name = "fact_checker"
    temperature = 0.0
    response_format = "json"
    max_tokens = 1200

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        chapter_path = f"chapters/ch{chapter:03d}.md"
        verdict_path = f"chapters/ch{chapter:03d}.verdict.json"
        chapter_text = bb.read_text(chapter_path)
        verdict = bb.read_json(verdict_path)

        # era.md is optional context so the LLM frames queries in the right timeframe
        era = bb.read_text("era.md") if bb.exists("era.md") else ""

        inputs_read: list[str] = [f"state/{chapter_path}", f"state/{verdict_path}"]
        if era:
            inputs_read.append("state/era.md")

        landmines = verdict.get("landmines") or {}
        l13 = landmines.get("landmine_13") or {}
        l13_evidence = (l13.get("evidence") or "").strip()
        l13_hit = bool(l13.get("hit"))
        l13_severity = (l13.get("severity") or "").strip().lower()

        system = (
            "你是独立的事实核查员。你的输入是一段章节正文 + Evaluator 给出的\n"
            "landmine_13（世界观模糊/脱离现实）命中原文片段。\n"
            "\n"
            "# 你的任务\n"
            "从 evidence 片段中提取**可外部查证**的具体事实断言——\n"
            "要求：（1）包含明确的年份/事件/数字/真实地点/真实人物；\n"
            "      （2）可以用一句自然语言查询搜索引擎确认/否定。\n"
            "\n"
            "# 输出要求（严格 JSON）\n"
            "\n"
            "{\n"
            '  "claims": [\n'
            "    {\n"
            '      "snippet": "<原文引文 ≤80 字>",\n'
            '      "assertion": "<该引文在陈述的具体事实 ≤40 字>",\n'
            '      "query": "<用于 Perplexity 搜索的一句话查询 ≤40 字>"\n'
            "    }, ...\n"
            "  ]\n"
            "}\n"
            "\n"
            "# 硬规则\n"
            "1. `claims` 数组 0-3 条。宁缺毋滥——没有可查证断言就输出空数组。\n"
            "2. 抽取范围仅限 Evaluator 的 landmine_13 evidence，不扩展到整章。\n"
            "3. 只抽**真实世界**可查证的断言（年份/物价/地名/真实事件/公众人物）。\n"
            "   纯虚构情节、人物心理、对白措辞都不算可查证。\n"
            "4. `query` 必须是自然语言，不要带引号或 markdown。\n"
            "5. 如果 Evaluator 没有命中 landmine_13 或 evidence 过于笼统，输出 `claims: []`。\n"
            "\n"
            "# 时代背景（仅供定位，不作查询依据）\n\n"
            + (era[:600] if era else "(无 era.md)")
            + "\n"
        )

        user = (
            f"# 第 {chapter} 章正文（供上下文）\n\n{chapter_text[:2500]}\n"
            + (
                f"\n...（以下省略 {max(0, len(chapter_text) - 2500)} 字）\n"
                if len(chapter_text) > 2500 else "\n"
            )
            + "\n# Evaluator 的 landmine_13 判定\n"
            + f"- hit: {l13_hit}\n"
            + f"- severity: {l13_severity or 'null'}\n"
            + f"- evidence: {l13_evidence or '(无)'}\n"
            + "\n# 输出\n\n请抽取 0-3 个可查证断言。"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        """Parse LLM claims, run Perplexity queries, write fact-patch.md.

        The raw LLM response is just the claims extraction. The actual
        fact-check happens here via websearch.search() per claim.
        """
        import re

        patch_path = f"fixes/ch{chapter:03d}.fact-patch.md"
        s = raw.strip()
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
        if m:
            s = m.group(1)

        try:
            parsed = json.loads(s)
        except json.JSONDecodeError as e:
            bb.write_text(
                patch_path,
                _render_parse_error(chapter, raw, str(e)),
            )
            return

        claims = parsed.get("claims") or []
        if not isinstance(claims, list):
            claims = []

        # Clip to 3 claims — the hard per-chapter cap. Skill #20: single-shot
        # per chapter, not per sentence.
        claims = claims[:3]

        if not claims:
            bb.write_text(patch_path, _render_no_claims(chapter))
            return

        # Run one websearch per claim (or none if API unavailable).
        if not websearch.is_available():
            bb.write_text(
                patch_path,
                _render_unavailable(chapter, claims),
            )
            return

        checked: list[dict[str, Any]] = []
        for c in claims:
            query = str(c.get("query", "")).strip()
            if not query:
                continue
            try:
                result = websearch.search(
                    query=query,
                    agent_name=self.name,
                    max_tokens=1200,
                )
                checked.append(
                    {
                        "snippet": c.get("snippet", ""),
                        "assertion": c.get("assertion", ""),
                        "query": query,
                        "search_content": result.content,
                        "citations": result.citations,
                        "cached": result.cached,
                        "latency_ms": result.latency_ms,
                        "error": None,
                    }
                )
            except (websearch.WebSearchUnavailable, RuntimeError) as e:
                checked.append(
                    {
                        "snippet": c.get("snippet", ""),
                        "assertion": c.get("assertion", ""),
                        "query": query,
                        "search_content": "",
                        "citations": [],
                        "cached": False,
                        "latency_ms": 0,
                        "error": f"{type(e).__name__}: {e}",
                    }
                )

        bb.write_text(patch_path, _render_patch(chapter, checked))


# =========================================================================
# Renderers — kept at module scope for unit-testability.
# =========================================================================

def _render_no_claims(chapter: int) -> str:
    return (
        f"# FactChecker 补丁 · 第 {chapter} 章\n\n"
        "**结论**：无需外部事实核查。\n\n"
        "Evaluator 未命中 landmine_13，或 evidence 中没有可外部查证的真实世界断言。\n"
        "本章纯虚构或世界观已由 setting pack 的 era.md / timeline.yaml 覆盖。\n"
    )


def _render_unavailable(chapter: int, claims: list[dict[str, Any]]) -> str:
    lines = [
        f"# FactChecker 补丁 · 第 {chapter} 章",
        "",
        "**状态**：⚠️ 联网核查不可用（未配置 `PERPLEXITY_API_KEY`）",
        "",
        "以下断言**未被核查**，建议人工复核：",
        "",
    ]
    for i, c in enumerate(claims, 1):
        lines.append(f"## 待核查 {i}")
        lines.append("")
        lines.append(f"**原文**：{c.get('snippet', '')}")
        lines.append("")
        lines.append(f"**断言**：{c.get('assertion', '')}")
        lines.append("")
        lines.append(f"**建议查询**：{c.get('query', '')}")
        lines.append("")
    return "\n".join(lines)


def _render_parse_error(chapter: int, raw: str, err: str) -> str:
    return (
        f"# FactChecker 补丁 · 第 {chapter} 章\n\n"
        "**状态**：⚠️ Claims 抽取失败（LLM 返回非预期 JSON）\n\n"
        f"**错误**：`{err}`\n\n"
        "**原始输出（尾 500 字）**：\n\n```\n"
        + raw[-500:]
        + "\n```\n\n"
        "建议：重跑该阶段，或人工核查该章的世界观/时代细节。\n"
    )


def _render_patch(chapter: int, checked: list[dict[str, Any]]) -> str:
    lines = [
        f"# FactChecker 补丁 · 第 {chapter} 章",
        "",
        f"**核查断言数**：{len(checked)}",
        "",
        "> 本文件是独立事实核查器的报告，基于 Evaluator 的 landmine_13 evidence\n"
        "> 抽取可查证断言并通过 Perplexity Sonar 查实。\n"
        "> **非 pass/fail 门**，是建议性补丁：Fixer 下一轮 retry 时可参考，\n"
        "> 也可由编辑手工对照。原文是 ground truth；本报告是外部佐证。",
        "",
    ]
    for i, c in enumerate(checked, 1):
        lines.append(f"## 断言 {i}")
        lines.append("")
        lines.append(f"**原文引文**：{c.get('snippet', '')}")
        lines.append("")
        lines.append(f"**断言**：{c.get('assertion', '')}")
        lines.append("")
        lines.append(f"**查询**：`{c.get('query', '')}`")
        if c.get("error"):
            lines.append("")
            lines.append(f"**❌ 核查失败**：{c['error']}")
            lines.append("")
            continue
        lat_tag = ""
        if c.get("cached"):
            lat_tag = " · cached"
        elif c.get("latency_ms"):
            lat_tag = f" · {c['latency_ms']}ms"
        lines.append("")
        lines.append(f"**Perplexity 回答**{lat_tag}：")
        lines.append("")
        lines.append((c.get("search_content") or "").strip())
        cites = c.get("citations") or []
        if cites:
            lines.append("")
            lines.append("**来源**：")
            for j, u in enumerate(cites[:5], 1):
                lines.append(f"{j}. {u}")
        lines.append("")
    return "\n".join(lines)


# =========================================================================
# Gating helper — used by pipeline.py to decide whether to run FactChecker.
# =========================================================================

def should_run(bb: Blackboard, chapter: int) -> bool:
    """True iff Evaluator hit landmine_13 with moderate/high severity.

    Encapsulates the triggering rule in one place so both pipeline.py
    and any audit-only CLI can share the decision.
    """
    verdict_path = f"chapters/ch{chapter:03d}.verdict.json"
    if not bb.exists(verdict_path):
        return False
    try:
        verdict = bb.read_json(verdict_path)
    except (OSError, json.JSONDecodeError):
        return False
    landmines = verdict.get("landmines") or {}
    l13 = landmines.get("landmine_13") or {}
    if not l13.get("hit"):
        return False
    sev = (l13.get("severity") or "").strip().lower()
    # skill #20: only fire on meaningful hits, skip low-severity noise.
    # Evaluator uses the high/medium/low taxonomy (see _verdict_schema.py);
    # we also accept 'moderate' as a synonym for medium so LLM quirks don't
    # silently disable the fact-checker.
    return sev in ("medium", "moderate", "high")

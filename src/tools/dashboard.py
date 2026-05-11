"""Quality dashboard — aggregate per-chapter metrics from a state/ or snapshot dir.

Usage:
    python -m src.tools.dashboard                    # use current state/
    python -m src.tools.dashboard --dir docs/demo_snapshot
    python -m src.tools.dashboard --dir docs/demo_snapshot_xianxia --out docs/dashboards/xianxia.md

Reads:
    <dir>/outline.json
    <dir>/progress.json
    <dir>/chapters/chNNN.{md,plan.json,verdict.json}
    <dir>/summaries/chNNN.md
    <dir>/fixes/chNNN.{slop,char}-patch.md
    <dir>/issues.jsonl
    <dir>/debt.jsonl
    <dir>/prompts_log.jsonl

Produces:
    A Markdown report (stdout or --out file) containing:
    - Header: novel title, setting id, chapter count, total LLM calls, wall-time
    - Chapter Progression Table: one row per produced chapter
    - Landmine Frequency Table: which landmines fire most often
    - Agent Call Statistics: per-agent count / avg latency / avg tokens / total cost proxy
    - Debt Table: outstanding unresolved issues
    - Validation Warnings (from _validation_warnings in verdicts)
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .. import config


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def count_cjk(text: str) -> int:
    """Count chars that aren't whitespace or markdown markers."""
    return sum(1 for c in text if not c.isspace() and c not in "#*`-[](){}>")


def extract_slop_score(patch_md: str) -> int | None:
    # Patch format: "**AI 味分数**：2 / 10" or "AI 味分数 : 2/10"
    m = re.search(r"AI\s*味分数[^-\d]*?(-?\d+)\s*/\s*10", patch_md)
    return int(m.group(1)) if m else None


def extract_slop_hits(patch_md: str) -> int | None:
    m = re.search(r"命中数[^0-9]*?(\d+)", patch_md)
    return int(m.group(1)) if m else None


def extract_char_score(patch_md: str) -> int | None:
    m = re.search(r"OOC\s*偏移分数[^-\d]*?(-?\d+)\s*/\s*10", patch_md)
    return int(m.group(1)) if m else None


def render_md(dir_: Path) -> str:
    """Main rendering function."""
    lines: list[str] = []

    # ---- Load everything ----
    progress = load_json(dir_ / "progress.json") or {}
    outline = load_json(dir_ / "outline.json") or {}
    setting_meta = load_yaml(dir_ / "setting.yaml") or {}
    issues = load_jsonl(dir_ / "issues.jsonl")
    debt = load_jsonl(dir_ / "debt.jsonl")
    prompts = load_jsonl(dir_ / "prompts_log.jsonl")

    # Build per-chapter data
    completed = progress.get("completed_chapters", []) or []
    outline_chapters = outline.get("chapters", []) or []
    max_ch = max(completed) if completed else 0

    # ---- Header ----
    lines.append(f"# 质量仪表盘 · {outline.get('title', '(无标题)')}")
    lines.append("")
    lines.append(f"- **Setting**：`{setting_meta.get('id', '?')}` · {setting_meta.get('genre', '?')}")
    lines.append(f"- **数据来源**：`{dir_}`")
    lines.append(f"- **生成时间**：{datetime.now().isoformat(timespec='seconds')}")
    lines.append("")

    # ---- Totals ----
    total_calls = len(prompts)
    total_tokens = sum(
        (p.get("usage") or {}).get("total_tokens", 0) or 0 for p in prompts
    )
    total_latency = sum(p.get("latency_ms", 0) or 0 for p in prompts)
    wall_time_min = total_latency / 1000 / 60
    lines.append("## 总览")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 大纲总章数 | {len(outline_chapters)} |")
    lines.append(f"| 已产出章节 | {len(completed)} → 最高到 ch{max_ch:03d} |")
    lines.append(f"| LLM 总调用数 | {total_calls} |")
    lines.append(f"| 总 token 消耗 | {total_tokens:,} |")
    lines.append(f"| LLM 总耗时 | {wall_time_min:.1f} 分钟 |")
    lines.append(f"| 累计 issues | {len(issues)} |")
    lines.append(f"| 待偿技术债 | {len(debt)} |")
    lines.append("")

    # ---- Per-chapter progression ----
    lines.append("## 各章节指标")
    lines.append("")
    lines.append("| 章 | 字数 | 耗时(s) | retries | Eval.hits | AI味 | OOC | 结果 |")
    lines.append("|---|---|---|---|---|---|---|---|")

    per_chapter: list[dict] = []
    for ch in sorted(completed):
        nnn = f"{ch:03d}"
        chapter_text = ""
        ch_md_path = dir_ / "chapters" / f"ch{nnn}.md"
        if ch_md_path.exists():
            chapter_text = ch_md_path.read_text(encoding="utf-8")
        verdict = load_json(dir_ / "chapters" / f"ch{nnn}.verdict.json") or {}
        slop_patch_md = ""
        char_patch_md = ""
        sp = dir_ / "fixes" / f"ch{nnn}.slop-patch.md"
        cp = dir_ / "fixes" / f"ch{nnn}.char-patch.md"
        if sp.exists():
            slop_patch_md = sp.read_text(encoding="utf-8")
        if cp.exists():
            char_patch_md = cp.read_text(encoding="utf-8")

        # Gather metrics
        chapter_chars = count_cjk(chapter_text)
        chapter_calls = [
            p for p in prompts
            if f"ch{nnn}" in json.dumps(p.get("inputs_read") or [], ensure_ascii=False)
            or f"第 {ch} 章" in (p.get("user") or "")
            or f"第{ch}章" in (p.get("user") or "")
        ]
        ch_latency = sum(p.get("latency_ms", 0) for p in chapter_calls) / 1000
        retries = sum(
            1 for p in chapter_calls
            if p.get("agent_name") in ("fixer", "evaluator")
        )
        # Eval hits (from verdict)
        hits = sum(
            1 for e in (verdict.get("landmines") or {}).values()
            if isinstance(e, dict) and e.get("hit")
        )
        slop_score = extract_slop_score(slop_patch_md)
        char_score = extract_char_score(char_patch_md)
        passed = verdict.get("overall_pass", None)
        skeleton = verdict.get("_skeleton_detected", False)
        if passed is True:
            status = "✅ pass"
        elif skeleton:
            status = "⚠️ skeleton"
        elif any(d.get("chapter") == ch for d in debt):
            status = "🔴 带债"
        elif passed is False:
            status = "❌ fail"
        else:
            status = "?"
        per_chapter.append(
            {
                "ch": ch,
                "chars": chapter_chars,
                "latency_s": ch_latency,
                "retries": retries,
                "hits": hits,
                "slop": slop_score,
                "ooc": char_score,
                "status": status,
            }
        )
        slop_display = f"{slop_score}" if slop_score is not None else "—"
        ooc_display = f"{char_score}" if char_score is not None else "—"
        lines.append(
            f"| {ch} | {chapter_chars} | {ch_latency:.0f} | {retries} | "
            f"{hits} | {slop_display}/10 | {ooc_display}/10 | {status} |"
        )
    lines.append("")

    # ---- Landmine frequency ----
    if issues:
        lines.append("## Landmine 命中频率")
        lines.append("")
        lines.append("| Landmine | 命中次数 | 占比 |")
        lines.append("|---|---|---|")
        freq: dict[str, int] = {}
        for iss in issues:
            lid = iss.get("landmine_id", "?")
            freq[lid] = freq.get(lid, 0) + 1
        sorted_freq = sorted(freq.items(), key=lambda kv: -kv[1])
        for lid, n in sorted_freq:
            pct = n / len(issues) * 100
            lines.append(f"| `{lid}` | {n} | {pct:.1f}% |")
        lines.append("")

    # ---- Per-agent stats ----
    if prompts:
        lines.append("## Agent 调用统计")
        lines.append("")
        lines.append("| Agent | 次数 | 平均耗时(s) | 平均 tokens | 总 tokens | 错误数 |")
        lines.append("|---|---|---|---|---|---|")
        agents: dict[str, list[dict]] = {}
        for p in prompts:
            agents.setdefault(p.get("agent_name", "?"), []).append(p)
        for name in sorted(agents.keys()):
            calls = agents[name]
            latencies = [c.get("latency_ms", 0) / 1000 for c in calls]
            tokens = [
                (c.get("usage") or {}).get("total_tokens", 0) or 0 for c in calls
            ]
            errors = sum(1 for c in calls if c.get("error"))
            avg_lat = statistics.mean(latencies) if latencies else 0
            avg_tok = statistics.mean(tokens) if tokens else 0
            total_tok = sum(tokens)
            lines.append(
                f"| `{name}` | {len(calls)} | {avg_lat:.1f} | {avg_tok:,.0f} | "
                f"{total_tok:,} | {errors} |"
            )
        lines.append("")

    # ---- Bookkeeping ledger presence (Lesson-3 layer) ----
    # These files are overwrite-style (not per-chapter), so we report
    # their presence + size + last-modified as a sanity check that the
    # bookkeeping layer is actually running and producing artifacts.
    bk_files = [
        ("current_status_card.md", "StatusCardUpdater (C-23)", "当前时间点权威快照"),
        ("pending_hooks.md",       "HookKeeper (C-25)",        "待回收伏笔池"),
        ("resource_schema.yaml",   "setting.yaml (optional)",  "可追踪资源定义 (仅特定题材)"),
        ("resource_ledger.md",     "ResourceLedger (C-24)",    "资源账本 (需 schema)"),
    ]
    present = [f for f, _, _ in bk_files if (dir_ / f).exists()]
    lines.append("## Bookkeeping 账本（Lesson-3 层）")
    lines.append("")
    if present:
        lines.append("| 文件 | 产出 Agent | 含义 | 存在 | 字节数 |")
        lines.append("|---|---|---|---|---|")
        for fname, producer, desc in bk_files:
            p = dir_ / fname
            if p.exists():
                lines.append(f"| `{fname}` | {producer} | {desc} | ✅ | {p.stat().st_size:,} |")
            else:
                # only report as missing if it's the ledger whose schema is present
                # (resource_ledger.md legitimately missing when schema is absent)
                is_optional_ledger = (fname == "resource_ledger.md" and
                                      not (dir_ / "resource_schema.yaml").exists())
                if is_optional_ledger:
                    continue
                lines.append(f"| `{fname}` | {producer} | {desc} | ❌ | — |")
        lines.append("")
    else:
        lines.append("*当前无 bookkeeping 账本产出（可能是 pre-C-23 的旧快照，或尚未运行过完整 pipeline）*")
        lines.append("")

    # ---- Debt ----
    if debt:
        lines.append("## 待偿技术债")
        lines.append("")
        lines.append("| 章 | retries 用尽 | 未解决 hits | top 未决 landmines |")
        lines.append("|---|---|---|---|")
        for d in debt:
            unresolved = d.get("unresolved", []) or []
            top_ids = [u.get("landmine_id", "?") for u in unresolved[:3]]
            lines.append(
                f"| {d.get('chapter', '?')} | "
                f"{d.get('retries_used', '?')} | "
                f"{len(unresolved)} | "
                f"{', '.join(top_ids) or '—'} |"
            )
        lines.append("")
    else:
        lines.append("## 待偿技术债")
        lines.append("")
        lines.append("*当前无未偿技术债。*")
        lines.append("")

    # ---- Validation warnings (from _validation_warnings in verdicts) ----
    val_warnings: list[tuple[int, list[str]]] = []
    for ch in sorted(completed):
        nnn = f"{ch:03d}"
        v = load_json(dir_ / "chapters" / f"ch{nnn}.verdict.json") or {}
        ws = v.get("_validation_warnings") or []
        if ws:
            val_warnings.append((ch, ws))
    if val_warnings:
        lines.append("## Evaluator 校验警告")
        lines.append("")
        for ch, ws in val_warnings:
            lines.append(f"- **ch{ch:03d}**：")
            for w in ws:
                lines.append(f"    - {w}")
        lines.append("")

    # ---- Quick interpretation ----
    lines.append("## 简短判读")
    lines.append("")
    if per_chapter:
        avg_retries = statistics.mean(x["retries"] for x in per_chapter)
        slop_scores = [x["slop"] for x in per_chapter if x["slop"] is not None]
        avg_slop = statistics.mean(slop_scores) if slop_scores else None
        ooc_scores = [x["ooc"] for x in per_chapter if x["ooc"] is not None]
        avg_ooc = statistics.mean(ooc_scores) if ooc_scores else None

        lines.append(f"- 平均每章 Fixer+Evaluator 调用数：{avg_retries:.1f}")
        if avg_slop is not None:
            lines.append(f"- 平均 AI 味分数：{avg_slop:.1f}/10")
        if avg_ooc is not None:
            lines.append(f"- 平均 OOC 偏移分数：{avg_ooc:.1f}/10")

        # Drift signal: later chapters vs earlier
        if len(per_chapter) >= 6:
            early = per_chapter[: len(per_chapter) // 2]
            late = per_chapter[len(per_chapter) // 2 :]
            early_hits = statistics.mean(x["hits"] for x in early)
            late_hits = statistics.mean(x["hits"] for x in late)
            drift = late_hits - early_hits
            lines.append(
                f"- 前半段 vs 后半段 Eval hits 均值：{early_hits:.1f} → {late_hits:.1f} "
                f"（drift Δ={drift:+.1f}）"
            )
            if drift > 1.0:
                lines.append(
                    "    - ⚠️ 后半段 hits 显著上升，疑似长链路 drift（Lesson 3）"
                )

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Quality dashboard for a run")
    parser.add_argument(
        "--dir",
        default=str(config.STATE_DIR),
        help="State or snapshot directory (default: state/)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path for markdown (default: stdout)",
    )
    args = parser.parse_args()

    dir_ = Path(args.dir)
    if not dir_.exists():
        print(f"ERROR: directory not found: {dir_}", file=sys.stderr)
        sys.exit(2)

    md = render_md(dir_)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"Dashboard written to {out_path}")
    else:
        print(md)


if __name__ == "__main__":
    main()

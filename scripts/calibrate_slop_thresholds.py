#!/usr/bin/env python3
"""
Calibrate AI-rhythm static scanner thresholds.

Reads every chapter under projects/*/state/chapters/*.md, runs
`static_scan_ai_rhythm` on each, and prints:

  - Per-metric distribution (min / p25 / p50 / p75 / p95 / max)
  - Chapters that trigger `severe` on any criterion
  - Chapters that trigger `moderate` (but not severe) on any criterion

Usage:

    .venv/bin/python3 scripts/calibrate_slop_thresholds.py

Zero LLM calls. Pure stdlib + the scanner from src.auditors.ai_slop_guard.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script (no installed package context).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.auditors.ai_slop_guard import (  # noqa: E402
    SLOP_THRESHOLDS,
    static_scan_ai_rhythm,
)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    k = (len(sv) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sv) - 1)
    frac = k - lo
    return sv[lo] * (1 - frac) + sv[hi] * frac


def fmt(v: float, ratio: bool = False) -> str:
    if ratio:
        return f"{v*100:.1f}%"
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v))}"
    return f"{v:.2f}"


def main() -> int:
    projects_dir = _REPO_ROOT / "projects"
    if not projects_dir.exists():
        print(f"!! projects/ not found at {projects_dir}")
        return 1

    chapter_files = sorted(projects_dir.glob("*/state/chapters/ch*.md"))
    if not chapter_files:
        print("!! no chapters found under projects/*/state/chapters/")
        return 1

    scans: list[tuple[str, dict]] = []  # (book/chapter label, scan result)
    for cf in chapter_files:
        # label = <book_id>/<chNNN>
        book_id = cf.parents[2].name
        chap = cf.stem  # e.g. ch026
        label = f"{book_id}/{chap}"
        try:
            text = cf.read_text(encoding="utf-8")
        except Exception as e:
            print(f"!! failed to read {cf}: {e}")
            continue
        scans.append((label, static_scan_ai_rhythm(text)))

    print(f"章节总数: {len(scans)}")
    print()

    # Per-metric distribution
    metric_keys = ("neg_contrast", "emdash", "short_para_ratio", "simile")
    print("指标分布:")
    for mk in metric_keys:
        vals = [s["metrics"][mk] for _, s in scans]
        ratio = mk.endswith("_ratio")
        print(
            f"  {mk:<18} "
            f"min={fmt(min(vals), ratio)} "
            f"p25={fmt(percentile(vals, 0.25), ratio)} "
            f"p50={fmt(percentile(vals, 0.50), ratio)} "
            f"p75={fmt(percentile(vals, 0.75), ratio)} "
            f"p95={fmt(percentile(vals, 0.95), ratio)} "
            f"max={fmt(max(vals), ratio)}"
        )
    print()

    # Classify chapters
    severe_chapters: list[tuple[str, list[dict]]] = []
    moderate_chapters: list[tuple[str, list[dict]]] = []
    for label, scan in scans:
        hits = scan["hits"]
        if not hits:
            continue
        has_severe = any(h["severity"] == "severe" for h in hits)
        if has_severe:
            severe_chapters.append((label, hits))
        else:
            moderate_chapters.append((label, hits))

    print(f"触发 severe 的章节: {len(severe_chapters)}")
    for label, hits in severe_chapters:
        sev_hits = [h for h in hits if h["severity"] == "severe"]
        mod_hits = [h for h in hits if h["severity"] == "moderate"]
        parts = []
        for h in sev_hits:
            parts.append(f"{h['criterion']}={h['count']} (severe)")
        for h in mod_hits:
            parts.append(f"{h['criterion']}={h['count']} (moderate)")
        print(f"  - {label}: " + ", ".join(parts))
    print()

    print(f"触发 moderate (非 severe) 的章节: {len(moderate_chapters)}")
    for label, hits in moderate_chapters:
        parts = [f"{h['criterion']}={h['count']} (moderate)" for h in hits]
        print(f"  - {label}: " + ", ".join(parts))
    print()

    print("当前阈值:")
    for k, v in SLOP_THRESHOLDS.items():
        print(f"  {k:<14} moderate={v['moderate']}  severe={v['severe']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

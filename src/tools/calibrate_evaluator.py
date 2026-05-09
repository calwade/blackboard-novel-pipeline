"""Evaluator calibration runner.

Usage:
    python -m src.tools.calibrate_evaluator
    python -m src.tools.calibrate_evaluator --case case-04-character-ooc
    python -m src.tools.calibrate_evaluator --verbose

For each YAML case under evaluator_calibration/cases/:
  1. Bootstrap the specified setting to a scratch state dir
  2. Write chapter_md to state/chapters/ch001.md
  3. Run Evaluator.run(chapter=1)
  4. Compare actual verdict to expected_verdict, compute per-case metrics
  5. Aggregate across all cases: recall / precision / overall_pass agreement

Produces:
  evaluator_calibration/reports/<timestamp>.json     — machine-readable
  evaluator_calibration/reports/<timestamp>.md       — human-readable summary
  evaluator_calibration/reports/latest.md            — symlink to newest

Invariants:
  - Does NOT touch the real state/ dir (uses a temp scratch dir per case)
  - Does NOT mutate anything in evaluator_calibration/cases/
  - Restores the user's active setting after running (best-effort)
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

from .. import config
from ..agents.evaluator import Evaluator
from ..blackboard import Blackboard


CASES_DIR = config.PROJECT_ROOT / "evaluator_calibration" / "cases"
REPORTS_DIR = config.PROJECT_ROOT / "evaluator_calibration" / "reports"


def load_cases(case_filter: str | None = None) -> list[dict]:
    """Load all YAML cases. If case_filter is given, only match files containing it."""
    files = sorted(CASES_DIR.glob("case-*.yaml"))
    cases = []
    for f in files:
        if case_filter and case_filter not in f.stem:
            continue
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        data["_source_file"] = f.name
        cases.append(data)
    return cases


def setup_scratch_state(setting_name: str, chapter_md: str) -> Path:
    """Create a fresh scratch state dir seeded from settings/<name>/ + the case's prose.

    Returns path to the scratch root (contains state/).
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="eval_calib_"))
    scratch_state = tmpdir / "state"
    scratch_state.mkdir()
    (scratch_state / "chapters").mkdir()
    (scratch_state / "summaries").mkdir()
    (scratch_state / "fixes").mkdir()

    # Copy the setting pack into state
    setting_dir = config.PROJECT_ROOT / "settings" / setting_name
    if not setting_dir.exists():
        raise FileNotFoundError(f"Unknown setting: {setting_name}")
    for f in [
        "setting.yaml",
        "outline.json",
        "timeline.yaml",
        "characters.yaml",
        "era.md",
        "writing-style-extra.md",
        "iron-laws-extra.md",
    ]:
        shutil.copy2(setting_dir / f, scratch_state / f)

    # Empty accumulating files
    (scratch_state / "issues.jsonl").touch()
    (scratch_state / "debt.jsonl").touch()
    (scratch_state / "progress.json").write_text(
        json.dumps({"current_chapter": 0, "active_setting": setting_name}),
        encoding="utf-8",
    )

    # Write the test chapter
    (scratch_state / "chapters" / "ch001.md").write_text(chapter_md, encoding="utf-8")

    return tmpdir


def run_one_case(case: dict, verbose: bool = False) -> dict:
    """Run Evaluator on one case, compare to expected, return metrics dict."""
    case_id = case["id"]
    setting = case["setting"]
    chapter_md = case["chapter_md"]
    expected = case["expected_verdict"]

    expected_hits = {h["landmine_id"]: h.get("severity") for h in expected.get("hits", [])}
    tolerated_extra = set(expected.get("tolerated_extra_hits", []))
    expected_pass = expected["overall_pass"]

    t0 = time.time()
    scratch = setup_scratch_state(setting, chapter_md)
    try:
        bb = Blackboard(root=scratch / "state")
        Evaluator().run(bb, chapter=1)
        verdict_path = scratch / "state" / "chapters" / "ch001.verdict.json"
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    finally:
        if not verbose:
            shutil.rmtree(scratch, ignore_errors=True)
        # If verbose, leave scratch for post-mortem

    duration_s = round(time.time() - t0, 1)

    # --- Compare ---
    actual_hits: dict[str, str] = {}
    for mid, entry in verdict.get("landmines", {}).items():
        if entry.get("hit"):
            actual_hits[mid] = entry.get("severity")

    actual_pass = verdict.get("overall_pass", False)
    skeleton = verdict.get("_skeleton_detected", False)

    # True positives: expected AND hit (severity ignored for recall counting)
    true_positives = set(expected_hits.keys()) & set(actual_hits.keys())
    # False negatives: expected but not hit
    false_negatives = set(expected_hits.keys()) - set(actual_hits.keys())
    # False positives: hit but not expected, and not tolerated
    false_positives = (set(actual_hits.keys()) - set(expected_hits.keys())) - tolerated_extra

    # Severity mismatches (landmines both expected and hit but with different severity)
    severity_mismatches = []
    for mid in true_positives:
        exp_sev = expected_hits[mid]
        act_sev = actual_hits[mid]
        if exp_sev and act_sev and exp_sev != act_sev:
            severity_mismatches.append(
                {"landmine": mid, "expected": exp_sev, "actual": act_sev}
            )

    # Metrics
    recall = (
        len(true_positives) / max(1, len(expected_hits)) if expected_hits else None
    )
    precision = (
        len(true_positives) / max(1, len(true_positives) + len(false_positives))
        if actual_hits
        else None
    )
    pass_agreement = actual_pass == expected_pass

    return {
        "case_id": case_id,
        "setting": setting,
        "source_file": case["_source_file"],
        "duration_s": duration_s,
        "actual_pass": actual_pass,
        "expected_pass": expected_pass,
        "pass_agreement": pass_agreement,
        "skeleton_detected": skeleton,
        "actual_hits": actual_hits,
        "expected_hits": expected_hits,
        "true_positives": sorted(true_positives),
        "false_negatives": sorted(false_negatives),
        "false_positives": sorted(false_positives),
        "severity_mismatches": severity_mismatches,
        "recall": recall,
        "precision": precision,
        "chapter_chars": len(chapter_md.replace("\n", "").replace(" ", "")),
    }


def render_markdown(results: list[dict], totals: dict) -> str:
    lines = []
    lines.append("# Evaluator 校准报告")
    lines.append("")
    lines.append(f"> 时间：{datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"> 模型：DeepSeek-V4-Pro  ·  cases：{len(results)}")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append(f"- **overall_pass 一致性**：{totals['pass_agreement_rate']:.1%}  "
                 f"（{totals['pass_agreement_count']} / {len(results)}）")
    if totals["recall_avg"] is not None:
        lines.append(f"- **平均召回**：{totals['recall_avg']:.1%}"
                     f"（多少应命中的 landmine 被抓到）")
    if totals["precision_avg"] is not None:
        lines.append(f"- **平均精度**：{totals['precision_avg']:.1%}"
                     f"（多少已命中的 landmine 是真的）")
    lines.append(f"- **总耗时**：{totals['total_duration_s']:.0f}s")
    lines.append(f"- **skeleton 触发次数**：{totals['skeleton_count']} / {len(results)}")
    lines.append("")

    lines.append("## 分 case 明细")
    lines.append("")
    lines.append("| # | case_id | setting | pass ✓? | 召回 | 精度 | FP | FN | 严重度错 | skeleton | 耗时 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        agr = "🟢" if r["pass_agreement"] else "🔴"
        rec = f"{r['recall']:.0%}" if r["recall"] is not None else "—"
        pre = f"{r['precision']:.0%}" if r["precision"] is not None else "—"
        fp = len(r["false_positives"])
        fn = len(r["false_negatives"])
        sm = len(r["severity_mismatches"])
        sk = "⚠️" if r["skeleton_detected"] else ""
        lines.append(
            f"| {r['case_id'].split('-')[1]} | {r['case_id']} | {r['setting']} | "
            f"{agr} | {rec} | {pre} | {fp} | {fn} | {sm} | {sk} | {r['duration_s']}s |"
        )
    lines.append("")

    # Failure details
    fails = [r for r in results if not r["pass_agreement"] or r["false_negatives"] or r["false_positives"]]
    if fails:
        lines.append("## 失败详情")
        lines.append("")
        for r in fails:
            lines.append(f"### {r['case_id']}")
            lines.append("")
            lines.append(f"- 期望 overall_pass = `{r['expected_pass']}`, 实际 = `{r['actual_pass']}`")
            if r["false_negatives"]:
                lines.append(f"- **漏判** (期望命中但未命中)：{r['false_negatives']}")
            if r["false_positives"]:
                lines.append(f"- **误判** (命中但不期望)：{r['false_positives']}")
            if r["severity_mismatches"]:
                lines.append(f"- 严重度错位：{r['severity_mismatches']}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 解读")
    lines.append("")
    lines.append("- **overall_pass 一致性** 低于 80% 意味着 Evaluator 对「过/不过」的判断没校准。")
    lines.append("- **召回** 低表示漏判硬伤，系统会放过问题稿件。")
    lines.append("- **精度** 低表示误判，Fixer 会被无意义地触发。")
    lines.append("- **skeleton 触发** 意味 Evaluator 返回占位符，需要修 prompt 或 retry。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="Run only cases whose stem contains this string")
    parser.add_argument("--verbose", action="store_true", help="Leave scratch dirs on disk")
    parser.add_argument("--no-report", action="store_true", help="Skip writing report files")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="How many cases to run in parallel (default 5, set 1 to serialize)",
    )
    args = parser.parse_args()

    config.assert_llm_configured()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    cases = load_cases(args.case)
    if not cases:
        print(f"No cases found matching filter: {args.case}", file=sys.stderr)
        sys.exit(2)

    workers = max(1, min(args.concurrency, len(cases)))
    print(
        f"Running {len(cases)} calibration case(s) with concurrency={workers}...",
        flush=True,
    )
    t0 = time.time()

    results: list[dict | None] = [None] * len(cases)
    print_lock = threading.Lock()
    done_counter = {"n": 0}

    def _task(i: int, case: dict) -> dict:
        try:
            r = run_one_case(case, verbose=args.verbose)
        except Exception as e:
            expected_ids = [
                h["landmine_id"] for h in case["expected_verdict"].get("hits", [])
            ]
            r = {
                "case_id": case["id"],
                "setting": case.get("setting"),
                "source_file": case["_source_file"],
                "error": f"{type(e).__name__}: {e}",
                "pass_agreement": False,
                "actual_pass": None,
                "expected_pass": case["expected_verdict"]["overall_pass"],
                "skeleton_detected": False,
                "actual_hits": {},
                "expected_hits": {
                    h["landmine_id"]: h.get("severity")
                    for h in case["expected_verdict"].get("hits", [])
                },
                "true_positives": [],
                "false_negatives": expected_ids,
                "false_positives": [],
                "severity_mismatches": [],
                "recall": 0.0,
                "precision": None,
                "duration_s": 0,
                "chapter_chars": len(case.get("chapter_md", "")),
            }

        # Progress line (serialized)
        with print_lock:
            done_counter["n"] += 1
            n = done_counter["n"]
            if "error" in r:
                print(
                    f"  [{n}/{len(cases)}] {case['id']} ... ERROR: {r['error']}",
                    flush=True,
                )
            else:
                status = (
                    "✓"
                    if r["pass_agreement"]
                    and not r["false_negatives"]
                    and not r["false_positives"]
                    else "✗"
                )
                skel = "[skeleton!]" if r["skeleton_detected"] else ""
                print(
                    f"  [{n}/{len(cases)}] {case['id']} ... {status} "
                    f"pass={r['actual_pass']} hits={len(r['actual_hits'])} {skel} "
                    f"({r['duration_s']}s)",
                    flush=True,
                )
        return r

    if workers == 1:
        # Serial path for debugging / deterministic runs
        for i, case in enumerate(cases):
            results[i] = _task(i, case)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_task, i, case): i for i, case in enumerate(cases)}
            for fut in concurrent.futures.as_completed(futures):
                i = futures[fut]
                results[i] = fut.result()

    # At this point all results are filled in (original order preserved).
    results = [r for r in results if r is not None]  # type: ignore[list-item]

    total_duration = round(time.time() - t0, 1)

    # Aggregate
    pass_agree = sum(1 for r in results if r.get("pass_agreement"))
    recalls = [r["recall"] for r in results if r.get("recall") is not None]
    precisions = [r["precision"] for r in results if r.get("precision") is not None]
    totals = {
        "pass_agreement_count": pass_agree,
        "pass_agreement_rate": pass_agree / len(results),
        "recall_avg": sum(recalls) / len(recalls) if recalls else None,
        "precision_avg": sum(precisions) / len(precisions) if precisions else None,
        "skeleton_count": sum(1 for r in results if r.get("skeleton_detected")),
        "total_duration_s": total_duration,
    }

    # Print summary to stdout
    print("\n=== Summary ===")
    print(f"  pass agreement: {totals['pass_agreement_count']}/{len(results)} ({totals['pass_agreement_rate']:.1%})")
    if totals["recall_avg"] is not None:
        print(f"  recall avg    : {totals['recall_avg']:.1%}")
    if totals["precision_avg"] is not None:
        print(f"  precision avg : {totals['precision_avg']:.1%}")
    print(f"  skeleton hits : {totals['skeleton_count']}/{len(results)}")
    print(f"  total time    : {total_duration}s")

    if args.no_report:
        return

    # Write reports
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORTS_DIR / f"{stamp}.json"
    md_path = REPORTS_DIR / f"{stamp}.md"
    latest_md = REPORTS_DIR / "latest.md"

    json_path.write_text(
        json.dumps({"results": results, "totals": totals}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(results, totals), encoding="utf-8")

    # Copy markdown to latest.md (symlinks can be lost in zip; just copy)
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"\nReport: {md_path}")
    print(f"JSON  : {json_path}")


if __name__ == "__main__":
    main()

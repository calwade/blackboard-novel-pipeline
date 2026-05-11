"""Pipeline main loop.

Orchestrates one chapter end-to-end through the multi-agent stack:

  1. Planner     — outline + prior summaries → chNNN.plan.json
  2. Generator   — plan + rules → chNNN.md (~3000 chars)
  3. Evaluator   — chapter → verdict.json + issues.jsonl
     (retry up to 2 times via Fixer)
     If still failing after 2 retries: ship_with_debt (Lesson 4)
  4. Summarizer  — chapter → summaries/chNNN.md  (isolated, Lesson 3)
  5. AISlopGuard + CharacterGuard in parallel (Fan-Out, Lesson 4)
     → fixes/chNNN.slop-patch.md and fixes/chNNN.char-patch.md

CLI:
  python -m src.pipeline --chapter N
  python -m src.pipeline --range 1-3
  python -m src.pipeline --audit-only N
  python -m src.pipeline --packaging
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import threading
import time
import traceback
from datetime import datetime

from .agents.evaluator import Evaluator
from .agents.fixer import Fixer
from .agents.generator import Generator
from .agents.packaging import PackagingAgent
from .agents.planner import Planner
from .agents.status_card_updater import StatusCardUpdater
from .agents.hook_keeper import HookKeeper
from .agents.resource_ledger import ResourceLedger, setting_has_resource_schema
from .agents.summarizer import Summarizer
from .agents.multi_level_summarizer import (
    ArcSummarizer,
    BookSummarizer,
    is_arc_boundary,
    is_volume_boundary,
)
from .auditors.ai_slop_guard import AISlopGuard
from .auditors.character_guard import CharacterGuard
from .auditors.fact_checker import FactChecker, should_run as fact_checker_should_run
from .blackboard import Blackboard

MAX_FIXER_RETRIES = 2

# Cooperative cancel signal. Web UI sets this via POST /api/abort; every
# pipeline stage checks before starting. Stale signals are the caller's
# responsibility to clear before starting a new run.
CANCEL_EVENT = threading.Event()


class PipelineAborted(RuntimeError):
    """Raised when CANCEL_EVENT is set between stages."""


def _check_cancel() -> None:
    if CANCEL_EVENT.is_set():
        raise PipelineAborted("pipeline aborted by cancel signal")


def _update_progress(bb: Blackboard, patch: dict) -> None:
    progress = bb.read_json("progress.json")
    progress.update(patch)
    progress["last_update"] = datetime.now().isoformat(timespec="seconds")
    bb.write_json("progress.json", progress)


def _update_in_flight(bb: Blackboard, chapter: int, stage: str, extra: dict | None = None) -> None:
    """Update progress.in_flight — used by Web UI to show live state."""
    info = {
        "chapter": chapter,
        "stage": stage,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        info.update(extra)
    _update_progress(bb, {"in_flight": info})


def _append_debt(bb: Blackboard, chapter: int, verdict: dict, retries_used: int) -> None:
    """Ship with debt: record unresolved issues so later Auditors can reopen."""
    unresolved = [
        {"landmine_id": k, **v}
        for k, v in verdict.get("landmines", {}).items()
        if v.get("hit")
    ]
    bb.append_jsonl(
        "debt.jsonl",
        {
            "ts": time.time(),
            "chapter": chapter,
            "retries_used": retries_used,
            "unresolved": unresolved,
            "top_3_fixes_unapplied": verdict.get("top_3_fixes", []),
        },
    )


def run_chapter(bb: Blackboard, chapter: int) -> dict:
    """Run the full pipeline for one chapter. Returns a status dict."""
    started_at = time.time()
    status: dict = {"chapter": chapter, "started_at": started_at, "stages": {}}

    def _stage(name: str, fn):
        """Run a stage and record its duration, surfacing exceptions."""
        _check_cancel()
        t0 = time.time()
        _update_in_flight(bb, chapter, name)
        try:
            fn()
            status["stages"][name] = {"ok": True, "duration_s": round(time.time() - t0, 1)}
        except Exception as e:
            status["stages"][name] = {
                "ok": False,
                "duration_s": round(time.time() - t0, 1),
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-800:],
            }
            raise

    # 1. Plan
    _stage("plan", lambda: Planner().run(bb, chapter=chapter))

    # 2. Generate
    _stage("generate", lambda: Generator().run(bb, chapter=chapter))

    # 3. Evaluate, then Fix, repeat up to MAX_FIXER_RETRIES
    passed = False
    for attempt in range(MAX_FIXER_RETRIES + 1):
        eval_stage = "evaluate" if attempt == 0 else f"evaluate_retry_{attempt}"
        _stage(eval_stage, lambda: Evaluator().run(bb, chapter=chapter))
        verdict = bb.read_json(f"chapters/ch{chapter:03d}.verdict.json")
        if verdict.get("overall_pass"):
            passed = True
            status["evaluation"] = {"passed": True, "after_retries": attempt}
            break
        if attempt < MAX_FIXER_RETRIES:
            _stage(f"fix_attempt_{attempt + 1}", lambda: Fixer().run(bb, chapter=chapter))

    if not passed:
        # Lesson 4: ship with debt rather than loop forever
        verdict = bb.read_json(f"chapters/ch{chapter:03d}.verdict.json")
        _append_debt(bb, chapter, verdict, retries_used=MAX_FIXER_RETRIES)
        status["evaluation"] = {
            "passed": False,
            "after_retries": MAX_FIXER_RETRIES,
            "shipped_with_debt": True,
        }

    # 4. Summarize (Lesson-3 isolation — reads only final chapter text)
    _stage("summarize", lambda: Summarizer().run(bb, chapter=chapter))

    # 4a. Status card update — the ONE authoritative "current time point"
    # snapshot (Lesson 3: Context Reset). Runs after Summarizer; reads ONLY
    # the chapter prose + previous card + characters + setting. Planner will
    # consume this at the start of ch{N+1}.
    _stage("update_status_card", lambda: StatusCardUpdater().run(bb, chapter=chapter))

    # 4a2. Hook ledger — maintain pending_hooks.md (unresolved hooks).
    # Independent bookkeeping agent; reads prose + prior ledger + status card.
    # Keeps hook tracking orthogonal to status-card updates so each can be
    # re-run in isolation if needed.
    _stage("update_hook_ledger", lambda: HookKeeper().run(bb, chapter=chapter))

    # 4a3. Resource ledger — only if the setting declared a resource schema.
    # Non-numeric settings (urban-romance) skip this stage entirely.
    if setting_has_resource_schema(bb):
        _stage("update_resource_ledger", lambda: ResourceLedger().run(bb, chapter=chapter))

    # 4b. Arc summary at arc boundaries (ch5, ch10, ch15, ...)
    if is_arc_boundary(chapter):
        _stage("arc_summarize", lambda: ArcSummarizer().run(bb, chapter=chapter))

    # 4c. Volume summary at volume boundaries (ch20, ch40, ...)
    if is_volume_boundary(chapter):
        _stage("book_summarize", lambda: BookSummarizer().run(bb, chapter=chapter))

    # 5. Fan-out Auditors in parallel threads.
    # AISlopGuard + CharacterGuard run every chapter.
    # FactChecker (A-1) runs ONLY when Evaluator hit landmine_13 with
    # moderate-or-high severity AND Perplexity is configured — see
    # src/auditors/fact_checker.py::should_run. Skips silently otherwise.
    def _run_auditor(AuditorClass):
        AuditorClass().run(bb, chapter=chapter)

    _check_cancel()
    _update_in_flight(bb, chapter, "audit_fanout")
    t0 = time.time()
    auditor_slots: dict[str, type] = {
        "ai_slop_guard": AISlopGuard,
        "character_guard": CharacterGuard,
    }
    if fact_checker_should_run(bb, chapter):
        auditor_slots["fact_checker"] = FactChecker

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(auditor_slots)) as ex:
        futures = {
            ex.submit(_run_auditor, cls): name for name, cls in auditor_slots.items()
        }
        results = {}
        for fut, nm in list(futures.items()):
            try:
                fut.result()
                results[nm] = "ok"
            except Exception as e:
                results[nm] = f"error: {type(e).__name__}: {e}"
    status["stages"]["audit_fanout"] = {
        "duration_s": round(time.time() - t0, 1),
        "results": results,
    }

    # Finalize progress
    progress = bb.read_json("progress.json")
    completed = progress.get("completed_chapters", [])
    if chapter not in completed:
        completed.append(chapter)
    _update_progress(
        bb,
        {
            "current_chapter": chapter,
            "completed_chapters": sorted(completed),
            "in_flight": None,
            "total_llm_calls": progress.get("total_llm_calls", 0),
        },
    )

    status["total_duration_s"] = round(time.time() - started_at, 1)
    status["shipped_with_debt"] = not passed
    return status


def run_audit_only(bb: Blackboard, chapter: int) -> dict:
    """Re-run the auditors on an existing chapter. Useful for demos.

    FactChecker fires only when the existing verdict.json has a
    landmine_13 hit at moderate+ severity AND Perplexity is configured.
    """
    t0 = time.time()
    auditor_tasks = [
        (AISlopGuard, "ai_slop_guard"),
        (CharacterGuard, "character_guard"),
    ]
    if fact_checker_should_run(bb, chapter):
        auditor_tasks.append((FactChecker, "fact_checker"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(auditor_tasks)) as ex:
        futs = [ex.submit(cls().run, bb, chapter=chapter) for cls, _ in auditor_tasks]
        for f in futs:
            f.result()
    return {
        "chapter": chapter,
        "audit_duration_s": round(time.time() - t0, 1),
        "auditors_run": [name for _, name in auditor_tasks],
    }


# -------------------------------------------------------------------------
# Intent Router (C-22) — lets users rerun individual stages without the
# full pipeline. Mirrors skill #1's "mixed-task orchestration" principle:
# the user declares intent (plan / write / evaluate / bookkeeping) and the
# pipeline dispatches only the relevant stages.
# -------------------------------------------------------------------------

def run_plan_only(bb: Blackboard, chapter: int) -> dict:
    """Regenerate plan.json for a chapter without touching prose."""
    t0 = time.time()
    Planner().run(bb, chapter=chapter)
    return {"chapter": chapter, "stage": "plan", "duration_s": round(time.time() - t0, 1)}


def run_write_only(bb: Blackboard, chapter: int) -> dict:
    """Regenerate chapter prose from existing plan.json (skip planning)."""
    t0 = time.time()
    Generator().run(bb, chapter=chapter)
    return {"chapter": chapter, "stage": "write", "duration_s": round(time.time() - t0, 1)}


def run_evaluate_only(bb: Blackboard, chapter: int) -> dict:
    """Re-evaluate an existing chapter; writes fresh verdict.json."""
    t0 = time.time()
    Evaluator().run(bb, chapter=chapter)
    verdict = bb.read_json(f"chapters/ch{chapter:03d}.verdict.json")
    return {
        "chapter": chapter,
        "stage": "evaluate",
        "overall_pass": verdict.get("overall_pass"),
        "duration_s": round(time.time() - t0, 1),
    }


def run_fix_only(bb: Blackboard, chapter: int) -> dict:
    """Run Fixer once using existing verdict.json's top_3_fixes."""
    t0 = time.time()
    Fixer().run(bb, chapter=chapter)
    return {"chapter": chapter, "stage": "fix", "duration_s": round(time.time() - t0, 1)}


def run_bookkeeping_only(bb: Blackboard, chapter: int) -> dict:
    """Refresh the derived ledgers (summary + status card + hooks + optional resources).

    Useful when the chapter prose was manually edited and we need the
    downstream bookkeeping agents to re-sync.
    """
    t0 = time.time()
    stages = {}

    t = time.time()
    Summarizer().run(bb, chapter=chapter)
    stages["summarize"] = round(time.time() - t, 1)

    t = time.time()
    StatusCardUpdater().run(bb, chapter=chapter)
    stages["update_status_card"] = round(time.time() - t, 1)

    t = time.time()
    HookKeeper().run(bb, chapter=chapter)
    stages["update_hook_ledger"] = round(time.time() - t, 1)

    if setting_has_resource_schema(bb):
        t = time.time()
        ResourceLedger().run(bb, chapter=chapter)
        stages["update_resource_ledger"] = round(time.time() - t, 1)

    if is_arc_boundary(chapter):
        t = time.time()
        ArcSummarizer().run(bb, chapter=chapter)
        stages["arc_summarize"] = round(time.time() - t, 1)

    if is_volume_boundary(chapter):
        t = time.time()
        BookSummarizer().run(bb, chapter=chapter)
        stages["book_summarize"] = round(time.time() - t, 1)

    return {
        "chapter": chapter,
        "stage": "bookkeeping",
        "stages": stages,
        "duration_s": round(time.time() - t0, 1),
    }


def run_packaging(bb: Blackboard) -> dict:
    """Run PackagingAgent once to produce state/packaging.json."""
    t0 = time.time()
    try:
        PackagingAgent().run(bb)
        result = bb.read_json("packaging.json")
        warnings = result.pop("_validation_warnings", [])
        return {
            "ok": True,
            "duration_s": round(time.time() - t0, 1),
            "recommended_title": result.get("recommended_title", ""),
            "tagline": result.get("tagline", ""),
            "validation_warnings": warnings,
        }
    except Exception as e:
        return {
            "ok": False,
            "duration_s": round(time.time() - t0, 1),
            "error": f"{type(e).__name__}: {e}",
        }


def main():
    parser = argparse.ArgumentParser(description="Novelforge runner")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--chapter", type=int, help="run one chapter (full pipeline)")
    grp.add_argument("--range", type=str, help="run chapters N-M (e.g. 1-3)")
    grp.add_argument("--audit-only", type=int, metavar="N", dest="audit_only",
                     help="rerun AISlopGuard + CharacterGuard on chapter N")
    grp.add_argument("--packaging", action="store_true", help="run PackagingAgent to produce state/packaging.json")
    # Intent Router (C-22): rerun individual stages without full pipeline
    grp.add_argument("--plan-only", type=int, metavar="N", dest="plan_only",
                     help="(Intent: plan) regenerate plan.json for chapter N only")
    grp.add_argument("--write-only", type=int, metavar="N", dest="write_only",
                     help="(Intent: write) regenerate prose from existing plan.json only")
    grp.add_argument("--evaluate-only", type=int, metavar="N", dest="evaluate_only",
                     help="(Intent: evaluate) re-run Evaluator on chapter N only")
    grp.add_argument("--fix-only", type=int, metavar="N", dest="fix_only",
                     help="(Intent: fix) run Fixer once from existing verdict.json")
    grp.add_argument("--bookkeeping-only", type=int, metavar="N", dest="bookkeeping_only",
                     help="(Intent: bookkeeping) refresh summary + status card + hooks + ledger from existing prose")
    args = parser.parse_args()

    bb = Blackboard()

    if args.packaging:
        result = run_packaging(bb)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.audit_only is not None:
        print(json.dumps(run_audit_only(bb, args.audit_only), ensure_ascii=False, indent=2))
        return

    # Intent-routed single-stage commands
    for flag, fn in (
        ("plan_only", run_plan_only),
        ("write_only", run_write_only),
        ("evaluate_only", run_evaluate_only),
        ("fix_only", run_fix_only),
        ("bookkeeping_only", run_bookkeeping_only),
    ):
        val = getattr(args, flag, None)
        if val is not None:
            print(json.dumps(fn(bb, val), ensure_ascii=False, indent=2))
            return

    chapters = (
        [args.chapter] if args.chapter else list(_range_to_list(args.range))
    )
    for n in chapters:
        print(f"\n===== Chapter {n} =====", flush=True)
        t0 = time.time()
        try:
            status = run_chapter(bb, n)
            print(json.dumps(status, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"FAILED at chapter {n}: {type(e).__name__}: {e}")
            print(traceback.format_exc())
            break
        print(f"Chapter {n} total: {int(time.time() - t0)}s", flush=True)


def _range_to_list(s: str):
    a, b = s.split("-")
    return range(int(a), int(b) + 1)


if __name__ == "__main__":
    main()

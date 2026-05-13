"""Pipeline run control + artifact inspection routes.

Covers:
  * /                 — main SPA view
  * /api/state        — compact progress snapshot
  * /api/file         — fetch sandboxed file (rules/ + state/ + AGENTS.md)
  * /api/prompts      — tail of prompts_log.jsonl
  * /api/debt, /api/issues
  * /api/run          — dispatch one-shot and range pipeline runs
  * /api/abort        — set pipeline.CANCEL_EVENT
  * /api/audit        — alias for audit-only
  * /api/status       — read pipeline_status.json
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request

from src import config, pipeline
from src.blackboard import Blackboard

from web._shared import _ALLOWED_FILES, READONLY_MODE, _run_lock

bp = Blueprint("runner", __name__)


def _bb() -> Blackboard:
    """Fresh Blackboard bound to the CURRENT state dir.

    Cheap (one Path resolve + mkdir). Must not be cached across requests
    because Web UI can switch projects mid-session.
    """
    return Blackboard(root=config.STATE_DIR)


def _status_path() -> Path:
    return config.STATE_DIR / "pipeline_status.json"


def _allowed_roots() -> tuple[Path, ...]:
    # Task: 题材视图把 presets/ 作为一等公民暴露给前端
    # （点题材库列表 → 中间 viewer 直接读 era.md / genre.yaml）。
    # presets/ 只含题材包，没有敏感文件；允许只读访问。
    return (
        config.STATE_DIR.resolve(),
        config.RULES_DIR.resolve(),
        config.PRESETS_DIR.resolve(),
    )


def _write_status(obj: dict) -> None:
    try:
        _status_path().write_text(
            json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _read_status() -> dict:
    sp = _status_path()
    if not sp.exists():
        return {"running": False}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"running": False}


def _resolve_safe(rel: str) -> Path:
    """Turn a user-supplied path into an absolute path iff it stays in-sandbox.

    Accepts:
      - "rules/..."          → RULES_DIR/...
      - "state/..."          → STATE_DIR/... (dynamic, rewrites to active project)
      - "AGENTS.md"          → the one whitelisted project-root file
      - absolute paths under any allowed roots (e.g. already-resolved by UI)
    Anything else → 403.
    """
    if not rel or ".." in Path(rel).parts:
        abort(403, "path traversal rejected")

    # Remap "state/..." to the current active STATE_DIR dynamically.
    # This keeps Web UI code simple (it can always say "state/chapters/...")
    # even after the project switches.
    if rel.startswith("state/"):
        candidate = (config.STATE_DIR / rel[len("state/"):]).resolve()
    else:
        candidate = (config.PROJECT_ROOT / rel).resolve()

    for root in _allowed_roots():
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    if candidate in _ALLOWED_FILES:
        return candidate
    abort(403, "path outside sandbox")


def _guess_mimetype(ext: str) -> str:
    return {
        ".md": "text/markdown",
        ".json": "application/json",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".jsonl": "application/x-ndjson",
        ".txt": "text/plain",
    }.get(ext.lower(), "text/plain")


# ---------- views ----------
@bp.get("/")
def index():
    return render_template("index.html", active_project_id=config.get_active_project_id())


@bp.get("/api/state")
def api_state():
    """Compact snapshot: progress + per-chapter artifact existence + counters."""
    try:
        progress = _bb().read_json("progress.json")
    except (OSError, json.JSONDecodeError):
        progress = {}
    try:
        outline = _bb().read_json("outline.json")
    except (OSError, json.JSONDecodeError):
        outline = {"chapters": []}

    chapters = []
    for ch_entry in outline.get("chapters", []):
        n = ch_entry["ch"]
        chapters.append(
            {
                "ch": n,
                "title": ch_entry.get("title", f"第 {n} 章"),
                "has_md": _bb().exists(f"chapters/ch{n:03d}.md"),
                "has_plan": _bb().exists(f"chapters/ch{n:03d}.plan.json"),
                "has_verdict": _bb().exists(f"chapters/ch{n:03d}.verdict.json"),
                "has_summary": _bb().exists(f"summaries/ch{n:03d}.md"),
                "has_slop_patch": _bb().exists(f"fixes/ch{n:03d}.slop-patch.md"),
                "has_char_patch": _bb().exists(f"fixes/ch{n:03d}.char-patch.md"),
            }
        )

    debt_count = len(_bb().read_jsonl("debt.jsonl"))
    issue_count = len(_bb().read_jsonl("issues.jsonl"))
    prompt_count = len(_bb().read_jsonl("prompts_log.jsonl"))

    # Bookkeeping artifacts (global, overwrite-style — not per-chapter).
    # Reflects C-23 / C-24 / C-25: StatusCardUpdater, HookKeeper, ResourceLedger.
    # The absence of resource_schema.yaml is a FEATURE (non-numeric settings
    # opt out of the resource ledger), so we surface that explicitly.
    bookkeeping = {
        "has_status_card": _bb().exists("current_status_card.md"),
        "has_pending_hooks": _bb().exists("pending_hooks.md"),
        "has_resource_schema": _bb().exists("resource_schema.yaml"),
        "has_resource_ledger": _bb().exists("resource_ledger.md"),
    }

    return jsonify(
        {
            "progress": progress,
            "chapters": chapters,
            "novel": {
                "title": outline.get("title"),
                "subtitle": outline.get("subtitle"),
                "protagonist": outline.get("protagonist"),
            },
            "bookkeeping": bookkeeping,
            "debt_count": debt_count,
            "issue_count": issue_count,
            "prompt_count": prompt_count,
            "readonly_mode": READONLY_MODE,
        }
    )


@bp.get("/api/file")
def api_file():
    rel = request.args.get("path", "").strip()
    abs_path = _resolve_safe(rel)
    if not abs_path.exists() or not abs_path.is_file():
        abort(404, "not found")
    try:
        content = abs_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        abort(415, "binary file")
    size = abs_path.stat().st_size
    return jsonify(
        {
            "path": rel,
            "content": content,
            "size": size,
            "mimetype": _guess_mimetype(abs_path.suffix),
        }
    )


@bp.get("/api/prompts")
def api_prompts():
    limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    rows = _bb().read_jsonl("prompts_log.jsonl")
    rows.reverse()  # newest first
    return jsonify(rows[:limit])


@bp.get("/api/debt")
def api_debt():
    return jsonify(_bb().read_jsonl("debt.jsonl"))


@bp.get("/api/issues")
def api_issues():
    return jsonify(_bb().read_jsonl("issues.jsonl"))


# ---------- pipeline run control ----------
_MODE_DISPATCH = {
    # mode key            status.kind     pipeline fn (unbound)       takes_chapter
    "chapter":            ("full",        "run_chapter",              True),
    "packaging":          ("packaging",   "run_packaging",            False),
    "plan-only":          ("plan",        "run_plan_only",            True),
    "write-only":         ("write",       "run_write_only",           True),
    "evaluate-only":      ("evaluate",    "run_evaluate_only",        True),
    "fix-only":           ("fix",         "run_fix_only",             True),
    "audit-only":         ("audit",       "run_audit_only",           True),
    "bookkeeping-only":   ("bookkeeping", "run_bookkeeping_only",     True),
}


def _parse_range(s: str) -> list[int]:
    """Parse 'N-M' → [N, N+1, ..., M]. Raises ValueError on bad shape."""
    if not isinstance(s, str) or "-" not in s:
        raise ValueError("range must be 'N-M'")
    try:
        a, b = s.split("-", 1)
        a, b = int(a.strip()), int(b.strip())
    except ValueError:
        raise ValueError("range must be 'N-M' with integers")
    if a < 1 or b < a:
        raise ValueError("range must satisfy 1 <= N <= M")
    return list(range(a, b + 1))


def _spawn_single(target_fn, kwargs: dict, kind: str):
    """Launch a single-shot pipeline call in a background thread."""
    if not _run_lock.acquire(blocking=False):
        return False
    pipeline.CANCEL_EVENT.clear()

    def _worker():
        started_at = time.time()
        _write_status({"running": True, "kind": kind, "started_at": started_at, **kwargs})
        try:
            result = target_fn(_bb(), **kwargs) if kwargs else target_fn(_bb())
            _write_status({
                "running": False, "kind": kind,
                "finished_at": time.time(), "ok": True,
                "result": result, **kwargs,
            })
        except pipeline.PipelineAborted:
            _write_status({
                "running": False, "kind": kind,
                "finished_at": time.time(), "ok": False,
                "error": "aborted", **kwargs,
            })
        except Exception as e:
            _write_status({
                "running": False, "kind": kind,
                "finished_at": time.time(), "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-1200:],
                **kwargs,
            })
        finally:
            _run_lock.release()

    # Guard against Thread.start() failure (e.g. OS thread exhaustion) —
    # without this, the lock would be stuck acquired forever.
    try:
        threading.Thread(target=_worker, daemon=True).start()
    except BaseException:
        _run_lock.release()
        raise
    return True


def _spawn_range(chapters: list[int]):
    """Launch a range job: serial run_chapter over each chapter, stop on first failure."""
    if not _run_lock.acquire(blocking=False):
        return False
    pipeline.CANCEL_EVENT.clear()

    def _worker():
        done: list[int] = []
        failed = None
        try:
            for ch in chapters:
                _write_status({
                    "running": True, "kind": "range", "chapter": ch,
                    "pending": [c for c in chapters if c > ch],
                    "done": done, "started_at": time.time(),
                })
                try:
                    pipeline.run_chapter(_bb(), chapter=ch)
                    done.append(ch)
                except pipeline.PipelineAborted:
                    failed = {"chapter": ch, "reason": "aborted"}
                    break
                except Exception as e:
                    failed = {
                        "chapter": ch,
                        "error": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc()[-1200:],
                    }
                    break
            _write_status({
                "running": False, "kind": "range", "done": done,
                "failed": failed, "finished_at": time.time(),
                "ok": failed is None,
            })
        finally:
            _run_lock.release()

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except BaseException:
        _run_lock.release()
        raise
    return True


@bp.post("/api/run")
def api_run():
    if READONLY_MODE:
        return jsonify({"started": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "").strip()

    # Backward compat: no mode + has chapter → treat as mode=chapter
    if not mode and "chapter" in data:
        mode = "chapter"

    # Range is a special case because it iterates; handle separately.
    if mode == "range":
        rng = data.get("range")
        try:
            chapters = _parse_range(rng) if isinstance(rng, str) else None
        except ValueError as e:
            return jsonify({"started": False, "reason": str(e)}), 400
        if not chapters:
            return jsonify({"started": False, "reason": "range required, format 'N-M'"}), 400
        if not _spawn_range(chapters):
            return jsonify({"started": False, "reason": "pipeline already running"}), 409
        return jsonify({"started": True, "kind": "range", "chapters": chapters}), 202

    if mode not in _MODE_DISPATCH:
        return jsonify({"started": False, "reason": f"unknown mode: {mode!r}"}), 400

    kind, fn_name, takes_chapter = _MODE_DISPATCH[mode]
    target_fn = getattr(pipeline, fn_name)

    kwargs: dict = {}
    if takes_chapter:
        ch = data.get("chapter")
        if ch is None:
            return jsonify({"started": False, "reason": f"chapter required for mode={mode}"}), 400
        try:
            ch = int(ch)
        except (TypeError, ValueError):
            return jsonify({"started": False, "reason": "chapter must be int"}), 400
        kwargs["chapter"] = ch

    if not _spawn_single(target_fn, kwargs, kind=kind):
        return jsonify({"started": False, "reason": "pipeline already running"}), 409
    return jsonify({"started": True, "kind": kind, **kwargs}), 202


@bp.post("/api/abort")
def api_abort():
    """Set pipeline.CANCEL_EVENT. Worker checks it between stages."""
    was_running = _run_lock.locked()
    pipeline.CANCEL_EVENT.set()
    return jsonify({"ok": True, "aborted": True, "was_running": was_running})


@bp.post("/api/audit")
def api_audit():
    """Thin alias dispatching to audit-only mode. Kept for backward
    compatibility with the existing frontend's 'Re-run Auditor' button.
    """
    if READONLY_MODE:
        return jsonify({"started": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    ch = data.get("chapter") if data else request.args.get("chapter")
    if ch is None:
        return jsonify({"started": False, "reason": "chapter required"}), 400
    try:
        ch = int(ch)
    except (TypeError, ValueError):
        return jsonify({"started": False, "reason": "chapter must be int"}), 400
    if not _spawn_single(pipeline.run_audit_only, {"chapter": ch}, kind="audit"):
        return jsonify({"started": False, "reason": "pipeline already running"}), 409
    return jsonify({"started": True, "kind": "audit", "chapter": ch}), 202


@bp.get("/api/status")
def api_status():
    return jsonify(_read_status())

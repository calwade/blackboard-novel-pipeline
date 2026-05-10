"""Flask web demo for the Blackboard Novel Pipeline.

Exists purely to make the architecture visible to humans in real time:
  - Left: the state/ filesystem as the single source of truth
  - Center: the artifact under inspection (chapter, debt, rules, agents.md)
  - Right: the Prompt Inspector — every LLM call, fresh-context, agent-colored

Every API handler is intentionally small; all heavy lifting lives in src/.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

from src import config, pipeline
from src.blackboard import Blackboard

app = Flask(__name__, static_folder="static", template_folder="templates")
bb = Blackboard()

# READONLY_MODE=1 disables /api/run and /api/audit. For hosted demos where
# we don't want evaluators to burn LLM budget or trigger concurrent runs.
READONLY_MODE: bool = os.environ.get("READONLY_MODE", "0") == "1"

# ---------- shared run-lock ----------
_run_lock = threading.Lock()
_STATUS_PATH = config.STATE_DIR / "pipeline_status.json"


def _write_status(obj: dict) -> None:
    try:
        _STATUS_PATH.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _read_status() -> dict:
    if not _STATUS_PATH.exists():
        return {"running": False}
    try:
        return json.loads(_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"running": False}


# ---------- path sandbox ----------
# Only these locations are legible to the browser.
_ALLOWED_ROOTS = (config.STATE_DIR.resolve(), config.RULES_DIR.resolve())
_ALLOWED_FILES = (config.PROJECT_ROOT.resolve() / "AGENTS.md",)


def _resolve_safe(rel: str) -> Path:
    """Turn a user-supplied path into an absolute path iff it stays in-sandbox."""
    if not rel or ".." in Path(rel).parts:
        abort(403, "path traversal rejected")
    # Normalize: treat both "state/..." (repo-relative) and bare "..." (state-relative).
    candidate = (config.PROJECT_ROOT / rel).resolve()
    for root in _ALLOWED_ROOTS:
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    if candidate in _ALLOWED_FILES:
        return candidate
    abort(403, "path outside sandbox")


# ---------- views ----------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    """Compact snapshot: progress + per-chapter artifact existence + counters."""
    try:
        progress = bb.read_json("progress.json")
    except (OSError, json.JSONDecodeError):
        progress = {}
    try:
        outline = bb.read_json("outline.json")
    except (OSError, json.JSONDecodeError):
        outline = {"chapters": []}

    chapters = []
    for ch_entry in outline.get("chapters", []):
        n = ch_entry["ch"]
        chapters.append(
            {
                "ch": n,
                "title": ch_entry.get("title", f"第 {n} 章"),
                "has_md": bb.exists(f"chapters/ch{n:03d}.md"),
                "has_plan": bb.exists(f"chapters/ch{n:03d}.plan.json"),
                "has_verdict": bb.exists(f"chapters/ch{n:03d}.verdict.json"),
                "has_summary": bb.exists(f"summaries/ch{n:03d}.md"),
                "has_slop_patch": bb.exists(f"fixes/ch{n:03d}.slop-patch.md"),
                "has_char_patch": bb.exists(f"fixes/ch{n:03d}.char-patch.md"),
            }
        )

    debt_count = len(bb.read_jsonl("debt.jsonl"))
    issue_count = len(bb.read_jsonl("issues.jsonl"))
    prompt_count = len(bb.read_jsonl("prompts_log.jsonl"))

    # Bookkeeping artifacts (global, overwrite-style — not per-chapter).
    # Reflects C-23 / C-24 / C-25: StatusCardUpdater, HookKeeper, ResourceLedger.
    # The absence of resource_schema.yaml is a FEATURE (non-numeric settings
    # opt out of the resource ledger), so we surface that explicitly.
    bookkeeping = {
        "has_status_card": bb.exists("current_status_card.md"),
        "has_pending_hooks": bb.exists("pending_hooks.md"),
        "has_resource_schema": bb.exists("resource_schema.yaml"),
        "has_resource_ledger": bb.exists("resource_ledger.md"),
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


@app.get("/api/file")
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


def _guess_mimetype(ext: str) -> str:
    return {
        ".md": "text/markdown",
        ".json": "application/json",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".jsonl": "application/x-ndjson",
        ".txt": "text/plain",
    }.get(ext.lower(), "text/plain")


@app.get("/api/prompts")
def api_prompts():
    limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    rows = bb.read_jsonl("prompts_log.jsonl")
    rows.reverse()  # newest first
    return jsonify(rows[:limit])


@app.get("/api/debt")
def api_debt():
    return jsonify(bb.read_jsonl("debt.jsonl"))


@app.get("/api/issues")
def api_issues():
    return jsonify(bb.read_jsonl("issues.jsonl"))


# ---------- pipeline controls ----------
def _spawn(target, chapter: int, kind: str):
    if not _run_lock.acquire(blocking=False):
        return False

    def _worker():
        _write_status(
            {
                "running": True,
                "kind": kind,
                "chapter": chapter,
                "started_at": time.time(),
            }
        )
        try:
            result = target(bb, chapter=chapter)
            _write_status(
                {
                    "running": False,
                    "kind": kind,
                    "chapter": chapter,
                    "finished_at": time.time(),
                    "ok": True,
                    "result": result,
                }
            )
        except Exception as e:
            _write_status(
                {
                    "running": False,
                    "kind": kind,
                    "chapter": chapter,
                    "finished_at": time.time(),
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc()[-1200:],
                }
            )
        finally:
            _run_lock.release()

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _chapter_arg() -> int:
    data = request.get_json(silent=True) or {}
    raw = request.args.get("chapter") or data.get("chapter")
    if raw is None:
        abort(400, "chapter required")
    try:
        return int(raw)
    except (TypeError, ValueError):
        abort(400, "chapter must be int")


@app.post("/api/run")
def api_run():
    if READONLY_MODE:
        return jsonify({"started": False, "reason": "readonly_mode"}), 403
    ch = _chapter_arg()
    ok = _spawn(pipeline.run_chapter, ch, kind="full")
    if not ok:
        return jsonify({"started": False, "reason": "pipeline already running"}), 409
    return jsonify({"started": True, "chapter": ch, "kind": "full"}), 202


@app.post("/api/audit")
def api_audit():
    if READONLY_MODE:
        return jsonify({"started": False, "reason": "readonly_mode"}), 403
    ch = _chapter_arg()
    ok = _spawn(pipeline.run_audit_only, ch, kind="audit")
    if not ok:
        return jsonify({"started": False, "reason": "pipeline already running"}), 409
    return jsonify({"started": True, "chapter": ch, "kind": "audit"}), 202


@app.get("/api/status")
def api_status():
    return jsonify(_read_status())


# ---------- errors ----------
@app.errorhandler(403)
def _h403(e):
    return jsonify({"error": "forbidden", "detail": str(e)}), 403


@app.errorhandler(404)
def _h404(e):
    return jsonify({"error": "not_found", "detail": str(e)}), 404


if __name__ == "__main__":
    # `flask --app web.app run` is the documented launcher; this is a fallback.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)

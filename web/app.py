"""Flask web demo for the Novelforge.

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


def _bb() -> Blackboard:
    """Fresh Blackboard bound to the CURRENT state dir.

    Cheap (one Path resolve + mkdir). Must not be cached across requests
    because Web UI can switch projects mid-session.
    """
    return Blackboard(root=config.STATE_DIR)


def _status_path() -> Path:
    return config.STATE_DIR / "pipeline_status.json"


def _allowed_roots() -> tuple[Path, ...]:
    return (config.STATE_DIR.resolve(), config.RULES_DIR.resolve())

# READONLY_MODE=1 disables /api/run and /api/audit. For hosted demos where
# we don't want evaluators to burn LLM budget or trigger concurrent runs.
READONLY_MODE: bool = os.environ.get("READONLY_MODE", "0") == "1"

# ---------- shared run-lock ----------
_run_lock = threading.Lock()


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


# ---------- path sandbox ----------
# Only these locations are legible to the browser.
#
# STATE_DIR is dynamic: after bootstrap it points to projects/<id>/state/.
# We also allow requests of the form "state/..." to map to that directory
# (so Web UI code and existing docs can keep talking about state/ paths
# regardless of which project is active).
# Allowed roots are resolved at call time via _allowed_roots() so they
# track the current STATE_DIR (including after project switches).
_ALLOWED_FILES = (config.PROJECT_ROOT.resolve() / "AGENTS.md",)  # still static


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


# ---------- project / genre management ----------
@app.get("/api/genres")
def api_genres():
    from src import bootstrap
    import yaml
    out = []
    for gid in bootstrap.list_genres():
        try:
            gyaml = yaml.safe_load(
                (config.GENRES_DIR / gid / "genre.yaml").read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            gyaml = {}
        out.append({
            "id": gid,
            "display_name": gyaml.get("display_name", gid),
            "genre": gyaml.get("genre"),
            "era": gyaml.get("era"),
            "tone": gyaml.get("tone"),
        })
    return jsonify({"genres": out})


@app.get("/api/projects")
def api_projects():
    from src import bootstrap
    import yaml
    active = config.get_active_project_id()
    out = []
    for pid in bootstrap.list_projects():
        pyaml_path = config.PROJECTS_DIR / pid / "project.yaml"
        try:
            pyaml = yaml.safe_load(pyaml_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            pyaml = {}
        out.append({
            "id": pid,
            "genre": pyaml.get("genre"),
            "display_name": pyaml.get("display_name", pid),
            "has_state": (config.PROJECTS_DIR / pid / "state").exists(),
            "is_active": (pid == active),
        })
    return jsonify({"active": active, "projects": out})


@app.post("/api/projects/activate")
def api_project_activate():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    pid = (data.get("id") or "").strip()
    if not pid:
        return jsonify({"ok": False, "reason": "id required"}), 400
    # Refuse if pipeline is running to avoid state mid-flight swap
    if not _run_lock.acquire(blocking=False):
        return jsonify({"ok": False, "reason": "pipeline running; try abort first"}), 409
    try:
        from src import bootstrap
        try:
            result = bootstrap.bootstrap_project(pid)
        except (FileNotFoundError, ValueError) as e:
            return jsonify({"ok": False, "reason": str(e)}), 400
        return jsonify({
            "ok": True,
            "active": result.project_id,
            "genre": result.genre_id,
            "copied_files": result.copied_files,
        })
    finally:
        _run_lock.release()


@app.post("/api/projects/new")
def api_project_new():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    pid = (data.get("id") or "").strip()
    genre = (data.get("genre") or "").strip()
    overwrite = bool(data.get("overwrite", False))
    if not pid or not genre:
        return jsonify({"ok": False, "reason": "id and genre required"}), 400
    from src import bootstrap
    try:
        project_dir = bootstrap.create_project(pid, genre, overwrite=overwrite)
    except ValueError as e:
        # invalid id/genre (e.g. path-traversal attempt) — hard reject
        return jsonify({"ok": False, "reason": str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    except FileExistsError as e:
        return jsonify({"ok": False, "reason": str(e)}), 409
    return jsonify({"ok": True, "project_dir": str(project_dir), "id": pid})


# ---------- project file editing ----------
_PROJECT_EDITABLE = {"project.yaml", "outline.json", "characters.yaml", "timeline.yaml"}


def _active_project_path(name: str) -> Path:
    """Resolve a file in the currently active project's source dir.

    Enforces the whitelist at the single boundary so callers can't smuggle
    arbitrary paths. Raises Flask 400/409 as appropriate.
    """
    if name not in _PROJECT_EDITABLE:
        abort(400, f"name must be one of {sorted(_PROJECT_EDITABLE)}")
    pid = config.get_active_project_id()
    if not pid:
        abort(409, "no active project")
    return config.PROJECTS_DIR / pid / name


@app.get("/api/project-files")
def api_project_file_get():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "reason": "name query parameter required"}), 400
    path = _active_project_path(name)
    if not path.exists():
        return jsonify({"ok": False, "reason": f"{name} not found in active project"}), 404
    return jsonify({
        "name": name,
        "content": path.read_text(encoding="utf-8"),
        "mtime": path.stat().st_mtime,
    })


@app.put("/api/project-files")
def api_project_file_put():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if "content" not in data:
        return jsonify({"ok": False, "reason": "content required"}), 400
    content = data["content"]
    if not isinstance(content, str):
        return jsonify({"ok": False, "reason": "content must be string"}), 400
    path = _active_project_path(name)

    # Atomic write
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)

    # Re-seed state/ so agents see the new content on next run.
    # preserve_progress=True — the user is editing source, not starting over.
    from src import bootstrap
    pid: str = config.get_active_project_id()  # type: ignore[assignment] — _active_project_path already validated
    try:
        bootstrap.bootstrap_project(pid, preserve_progress=True)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"ok": False, "reason": f"re-seed failed: {e}"}), 400
    return jsonify({"ok": True, "name": name, "re_seeded": True})


# ---------- env management ----------
_ENV_WRITABLE = {
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "PERPLEXITY_API_KEY",
    "PERPLEXITY_BASE_URL",
    "PERPLEXITY_MODEL",
}
_ENV_SENSITIVE = {"DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY"}


def _env_path() -> Path:
    return config._PROJECT_ROOT / ".env"


def _parse_env(text: str) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, ignore blanks and #comments.

    We avoid python-dotenv's parse here to keep write-back deterministic.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def _serialize_env(existing: dict[str, str], updates: dict[str, str]) -> str:
    """Merge updates into existing, write back in deterministic order.

    Whitelist keys come first (alphabetical), then any other keys the user
    might have added manually. Empty-string values mean "remove this key".
    """
    merged = dict(existing)
    for k, v in updates.items():
        if v == "":
            merged.pop(k, None)
        else:
            merged[k] = v
    lines: list[str] = []
    for k in sorted(_ENV_WRITABLE):
        if k in merged:
            lines.append(f"{k}={merged[k]}")
    for k, v in sorted(merged.items()):
        if k not in _ENV_WRITABLE:
            lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def _mask(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else value
    return f"****{tail}"


def _is_placeholder_key(value: str) -> bool:
    """Empty or the .env.example placeholder string both count as 'not set'."""
    return not value or value.startswith("dc-sk-put-yours")


@app.get("/api/env")
def api_env_get():
    env_file = _env_path()
    current = _parse_env(env_file.read_text(encoding="utf-8")) if env_file.exists() else {}
    out: dict[str, dict] = {}
    for k in sorted(_ENV_WRITABLE):
        v = current.get(k, "")
        if k in _ENV_SENSITIVE:
            out[k] = {
                "set": not _is_placeholder_key(v),
                "preview": _mask(v),
                "length": len(v),
            }
        else:
            out[k] = {"set": bool(v), "value": v}
    return jsonify(out)


@app.post("/api/env")
def api_env_post():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"ok": False, "reason": "json object with at least one key required"}), 400
    updates: dict[str, str] = {}
    for k, v in data.items():
        if k not in _ENV_WRITABLE:
            return jsonify({"ok": False, "reason": f"key not allowed: {k}"}), 400
        if not isinstance(v, str):
            return jsonify({"ok": False, "reason": f"value for {k} must be string"}), 400
        updates[k] = v

    env_file = _env_path()
    existing = _parse_env(env_file.read_text(encoding="utf-8")) if env_file.exists() else {}
    new_text = _serialize_env(existing, updates)

    # Atomic write
    tmp = env_file.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, env_file)

    # Live reload so later LLM calls in the same process see new values
    config.reload_env()
    return jsonify({"ok": True, "updated": sorted(updates.keys())})


# ---------- views ----------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
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
    rows = _bb().read_jsonl("prompts_log.jsonl")
    rows.reverse()  # newest first
    return jsonify(rows[:limit])


@app.get("/api/debt")
def api_debt():
    return jsonify(_bb().read_jsonl("debt.jsonl"))


@app.get("/api/issues")
def api_issues():
    return jsonify(_bb().read_jsonl("issues.jsonl"))


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
            result = target(_bb(), chapter=chapter)
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
@app.errorhandler(400)
def _h400(e):
    return jsonify({"ok": False, "reason": str(e)}), 400


@app.errorhandler(403)
def _h403(e):
    return jsonify({"error": "forbidden", "detail": str(e)}), 403


@app.errorhandler(404)
def _h404(e):
    return jsonify({"error": "not_found", "detail": str(e)}), 404


if __name__ == "__main__":
    # `flask --app web.app run` is the documented launcher; this is a fallback.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)

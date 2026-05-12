"""Flask web demo for the Novelforge.

Exists purely to make the architecture visible to humans in real time:
  - Left: the state/ filesystem as the single source of truth
  - Center: the artifact under inspection (chapter, debt, rules, agents.md)
  - Right: the Prompt Inspector — every LLM call, fresh-context, agent-colored

Every API handler is intentionally small; all heavy lifting lives in src/.
"""
from __future__ import annotations

import io
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

# ---------------------------------------------------------------------------
# Novels / material library config
# ---------------------------------------------------------------------------
# novels/ holds user-uploaded source material for genre extraction. The
# directory is in .gitignore (only the README is whitelisted) and we keep a
# single flat layout — no subdirs, no symlinks, no hidden files.
#
# NOVELS_DIR is a module attribute (not a function) so tests can monkeypatch
# it to tmp_path, matching the pattern we use for GENRES_DIR.
NOVELS_DIR: Path = config.PROJECT_ROOT / "novels"
# Max bytes per uploaded file. The overall Flask MAX_CONTENT_LENGTH is set
# higher (so multi-file uploads work) and per-file enforcement happens in
# the route handler.
NOVEL_MAX_BYTES: int = 50 * 1024 * 1024  # 50MB
# Accept one Flask request up to 200MB — roughly 4 × 50MB novels at once.
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


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
        gdir = config.GENRES_DIR / gid
        try:
            gyaml = yaml.safe_load(
                (gdir / "genre.yaml").read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            gyaml = {}

        # Count tracked genre files (genre.yaml / era.md / writing-style-extra.md /
        # iron-laws-extra.md / optional resource_schema.yaml). Ignore .build/.
        tracked_names = (
            "genre.yaml",
            "era.md",
            "writing-style-extra.md",
            "iron-laws-extra.md",
            "resource_schema.yaml",
        )
        file_count = sum(1 for n in tracked_names if (gdir / n).exists())

        has_build = (gdir / ".build" / "build_status.yaml").exists()

        out.append({
            "id": gid,
            "display_name": gyaml.get("display_name", gid),
            "genre": gyaml.get("genre"),
            "era": gyaml.get("era"),
            "tone": gyaml.get("tone"),
            "file_count": file_count,
            "has_build_status": has_build,
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
        # Reject newline/null injection — otherwise a malicious value like
        # "legit\nINJECTED_KEY=pwned" would smuggle extra lines into .env.
        if any(c in v for c in ("\n", "\r", "\0")):
            return jsonify({"ok": False, "reason": f"value for {k} contains illegal control chars"}), 400
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


@app.post("/api/run")
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


@app.post("/api/abort")
def api_abort():
    """Set pipeline.CANCEL_EVENT. Worker checks it between stages."""
    was_running = _run_lock.locked()
    pipeline.CANCEL_EVENT.set()
    return jsonify({"ok": True, "aborted": True, "was_running": was_running})


@app.post("/api/audit")
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


@app.get("/api/status")
def api_status():
    return jsonify(_read_status())


# ---------- genre pipeline ----------
# The genre pipeline is an independent long-lived job: its artifacts live
# under genres/<id>/.build/ (git-ignored). It runs on its own lock so a genre
# extract doesn't block a novel chapter run (different sandboxes).
#
# Cancellation: we mirror the novel pipeline's pattern — a module-level
# CANCEL_EVENT on src.genre_extractor.pipeline, checked at phase boundaries.
_genre_lock = threading.Lock()
_genre_task: dict = {"running": False}


def _genre_dir(genre_id: str) -> Path:
    from src import bootstrap as _bs
    _bs._validate_id("genre", genre_id)  # reject path-traversal / malformed
    return config.GENRES_DIR / genre_id


@app.post("/api/genres/new")
def api_genre_new():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    gid = (data.get("id") or "").strip()
    if not gid:
        return jsonify({"ok": False, "reason": "id required"}), 400

    from src.genre_extractor import pipeline as gpipe
    from src import bootstrap as _bs
    # Validate id up-front for a clean 400 (new_genre would also raise, but
    # its ValueError currently comes from the filesystem layer — less tidy).
    try:
        _bs._validate_id("genre", gid)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400

    try:
        result = gpipe.new_genre(
            gid,
            display_name=(data.get("name") or "").strip(),
            genre=(data.get("genre") or "").strip(),
            era=(data.get("era") or "").strip(),
            tone=(data.get("tone") or "").strip(),
        )
    except FileExistsError as e:
        return jsonify({"ok": False, "reason": str(e)}), 409
    except (ValueError, OSError) as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    return jsonify(result)


@app.post("/api/genres/<gid>/fill")
def api_genre_fill(gid: str):
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    gdir = _genre_dir(gid)
    if not gdir.exists():
        return jsonify({"ok": False, "reason": f"genre not found: {gid}"}), 404
    from src.genre_extractor import pipeline as gpipe
    try:
        return jsonify(gpipe.fill_genre(gid))
    except FileNotFoundError as e:
        return jsonify({"ok": False, "reason": str(e)}), 404
    except (ValueError, OSError) as e:
        return jsonify({"ok": False, "reason": str(e)}), 400


@app.post("/api/genres/<gid>/audit")
def api_genre_audit(gid: str):
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    # validate id before touching disk; accept missing dirs (audit_genre will
    # scaffold build_status for them)
    try:
        _genre_dir(gid)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    from src.genre_extractor import pipeline as gpipe
    try:
        return jsonify(gpipe.audit_genre(gid))
    except (ValueError, OSError) as e:
        return jsonify({"ok": False, "reason": str(e)}), 400


@app.post("/api/genres/<gid>/extract")
def api_genre_extract(gid: str):
    """Kick off extract_from_novel in a background thread.

    Body: {sources: [...], with_trial?: bool, dry_run?: bool}
    Returns 202 {started: true, started_at: ...} on success;
            409 if a genre build is already running;
            400 on bad input.
    """
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    gdir = _genre_dir(gid)
    if not gdir.exists():
        return jsonify({"ok": False, "reason": f"genre not found: {gid}"}), 404

    data = request.get_json(silent=True) or {}
    sources = data.get("sources") or []
    if not isinstance(sources, list) or not sources:
        return jsonify({"ok": False, "reason": "sources must be a non-empty list"}), 400
    # Validate each source exists synchronously — otherwise the worker would
    # raise FileNotFoundError deep inside extract_from_novel and the caller
    # would only see it in build_status post-mortem. Cleaner to 400 here.
    for s in sources:
        if not isinstance(s, str) or not Path(s).exists():
            return jsonify({"ok": False, "reason": f"source not found: {s!r}"}), 400

    with_trial = bool(data.get("with_trial", False))
    dry_run = bool(data.get("dry_run", False))

    if not _genre_lock.acquire(blocking=False):
        return jsonify({"started": False, "reason": "genre pipeline already running"}), 409

    from src.genre_extractor import pipeline as gpipe
    gpipe.CANCEL_EVENT.clear()

    started_at = time.time()
    _genre_task.update({
        "running": True,
        "genre_id": gid,
        "started_at": started_at,
        "dry_run": dry_run,
        "with_trial": with_trial,
        "sources": sources,
        "ok": None,
        "finished_at": None,
        "error": None,
    })

    def _worker():
        try:
            result = gpipe.extract_from_novel(
                gid, sources=sources, with_trial=with_trial, dry_run=dry_run,
            )
            _genre_task.update({
                "running": False,
                "finished_at": time.time(),
                "ok": True,
                "result": result,
            })
        except gpipe.GenrePipelineAborted:
            _genre_task.update({
                "running": False,
                "finished_at": time.time(),
                "ok": False,
                "error": "aborted",
            })
        except Exception as e:
            _genre_task.update({
                "running": False,
                "finished_at": time.time(),
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-1200:],
            })
        finally:
            _genre_lock.release()

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except BaseException:
        _genre_lock.release()
        raise

    return jsonify({
        "started": True,
        "genre_id": gid,
        "started_at": started_at,
        "dry_run": dry_run,
    }), 202


@app.get("/api/genres/<gid>/status")
def api_genre_status(gid: str):
    """Return build_status.yaml as JSON + in-memory task metadata.

    Poll target for the progress page. The build_status file is the source
    of truth (survives process restart); the in-memory task dict contains
    the ephemeral start time + final error if any.
    """
    import yaml
    try:
        gdir = _genre_dir(gid)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    if not gdir.exists():
        return jsonify({"ok": False, "reason": f"genre not found: {gid}"}), 404

    status_path = gdir / ".build" / "build_status.yaml"
    if not status_path.exists():
        return jsonify({
            "genre_id": gid,
            "phases": {},
            "task": _genre_task if _genre_task.get("genre_id") == gid else None,
            "has_build": False,
        })
    try:
        status = yaml.safe_load(status_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        return jsonify({"ok": False, "reason": f"failed to read status: {e}"}), 500

    status["has_build"] = True
    # Append ephemeral task metadata ONLY if it matches this genre — otherwise
    # we'd leak another genre's in-flight details.
    if _genre_task.get("genre_id") == gid:
        status["task"] = {
            k: _genre_task.get(k)
            for k in ("running", "started_at", "finished_at", "ok",
                      "error", "dry_run", "with_trial")
        }
    return jsonify(status)


@app.get("/api/genres/<gid>/issues")
def api_genre_issues(gid: str):
    """Return the last N entries of genre_issues.jsonl as JSON.

    A thin alternative to extending /api/file's sandbox to cover .build/.
    Each entry has: severity, file, message, genre_id, [source].
    Newest-first.
    """
    try:
        gdir = _genre_dir(gid)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    if not gdir.exists():
        return jsonify({"ok": False, "reason": f"genre not found: {gid}"}), 404
    try:
        limit = max(1, min(int(request.args.get("limit", 10)), 200))
    except (TypeError, ValueError):
        limit = 10

    issues_path = gdir / ".build" / "genre_issues.jsonl"
    if not issues_path.exists():
        return jsonify({"issues": [], "total": 0})

    out: list[dict] = []
    try:
        for line in issues_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip corrupt lines; jsonl is append-only and may
                          # momentarily have a partial last line during writes
    except OSError as e:
        return jsonify({"ok": False, "reason": str(e)}), 500

    out.reverse()  # newest first
    return jsonify({"issues": out[:limit], "total": len(out)})


@app.post("/api/genres/<gid>/abort")
def api_genre_abort(gid: str):
    """Set the genre pipeline CANCEL_EVENT. Worker stops at next phase boundary."""
    from src.genre_extractor import pipeline as gpipe
    was_running = _genre_lock.locked()
    gpipe.CANCEL_EVENT.set()
    return jsonify({"ok": True, "aborted": True, "was_running": was_running})


@app.delete("/api/genres/<gid>")
def api_genre_delete(gid: str):
    """Remove a genre directory. Refuses if any project still references it —
    that would leave those projects un-bootstrappable.
    """
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    import shutil
    import yaml as _yaml
    try:
        gdir = _genre_dir(gid)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    if not gdir.exists():
        return jsonify({"ok": False, "reason": f"genre not found: {gid}"}), 404

    # Dependent-project safety check
    dependents = []
    if config.PROJECTS_DIR.exists():
        for pdir in config.PROJECTS_DIR.iterdir():
            if not pdir.is_dir():
                continue
            pyaml = pdir / "project.yaml"
            if not pyaml.exists():
                continue
            try:
                data = _yaml.safe_load(pyaml.read_text(encoding="utf-8")) or {}
            except (OSError, _yaml.YAMLError):
                continue
            if data.get("genre") == gid:
                dependents.append(pdir.name)
    if dependents:
        return jsonify({
            "ok": False,
            "reason": f"genre {gid!r} still referenced by: {', '.join(dependents)}",
            "dependents": dependents,
        }), 409

    shutil.rmtree(gdir)
    return jsonify({"ok": True, "genre_id": gid})


# ---------- genre views (server-rendered HTML) ----------
@app.get("/genres")
def view_genres_index():
    return render_template("genres/index.html")


@app.get("/genres/new")
def view_genre_new():
    return render_template("genres/new.html")


@app.get("/genres/<gid>")
def view_genre_detail(gid: str):
    try:
        gdir = _genre_dir(gid)
    except ValueError:
        abort(404)
    if not gdir.exists():
        abort(404)
    return render_template("genres/detail.html", gid=gid)


@app.get("/genres/<gid>/extract")
def view_genre_extract_form(gid: str):
    try:
        gdir = _genre_dir(gid)
    except ValueError:
        abort(404)
    if not gdir.exists():
        abort(404)
    return render_template("genres/extract.html", gid=gid)


@app.get("/genres/<gid>/extract/progress")
def view_genre_extract_progress(gid: str):
    try:
        gdir = _genre_dir(gid)
    except ValueError:
        abort(404)
    if not gdir.exists():
        abort(404)
    return render_template("genres/progress.html", gid=gid)


# ---------- novels / material library ----------
# A thin HTTP face for novels/: a flat, UTF-8-only .txt dustbin that the
# genre pipeline's --extract-from-novel consumes. Invariants enforced
# across every route:
#   1. filenames NEVER escape novels/ (tested in test_web_novels_api.py)
#   2. we never read more than 1MB of a file on list (use ChapterStream for >5MB)
#   3. partial uploads never leak — .tmp + atomic rename pattern
import re as _novels_re

# Accept letters (incl. CJK), digits, dot, dash, underscore, space.
# Everything else becomes underscore. Kept as a compiled re because we hit
# it once per uploaded file, and the alternative (repeated str.translate) is
# less legible for the reviewer.
_NOVEL_NAME_KEEP = _novels_re.compile(
    r"[^"
    r"A-Za-z0-9"
    r"\u4e00-\u9fff"       # CJK Unified Ideographs
    r"\u3400-\u4dbf"       # CJK Extension A
    r"\u3040-\u309f"       # Hiragana (Japanese)
    r"\u30a0-\u30ff"       # Katakana
    r"\uac00-\ud7af"       # Hangul
    r"\s\-_.()"
    r"]"
)


def _human_size(n: int) -> str:
    """'1234567' → '1.2 MB'. Keeps one decimal; never returns '0.0 B'."""
    for unit, step in (("B", 1), ("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3)):
        if n < step * 1024 or unit == "GB":
            if unit == "B":
                return f"{n} B"
            return f"{n / step:.1f} {unit}"
    return f"{n} B"


def _sanitize_novel_name(raw: str) -> str:
    """Turn a user-supplied filename into a safe, same-directory name.

    We deliberately DON'T use werkzeug.secure_filename alone because it
    strips all non-ASCII (a Chinese 某某港综.txt becomes 'txt' — useless).

    Steps:
      1. drop directory components — os.path.basename handles both / and \\
      2. strip leading dots (prevents '.hidden' and '..')
      3. replace control chars + path separators + anything not in our
         permissive allow-list with '_'
      4. collapse runs of whitespace to single '_'
      5. if result is empty or just punctuation → fall back to 'upload.txt'
    """
    if not raw:
        return "upload.txt"
    # Step 1: take last path component (defends against any separator)
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    # Step 2: strip leading dots / whitespace — 'hidden' and '..' both
    #         collapse to empty below.
    name = name.lstrip(". \t\r\n")
    # Step 3: allow-list filter
    name = _NOVEL_NAME_KEEP.sub("_", name)
    # Step 4: collapse whitespace runs
    name = _novels_re.sub(r"\s+", "_", name).strip("_. ")
    if not name or name in {".", ".."}:
        return "upload.txt"
    # enforce .txt suffix at this layer? No — caller checks extension
    # separately so skipped-reason can say 'not a .txt file' clearly.
    return name


def _unique_novel_path(name: str) -> Path:
    """If novels/<name> exists, return novels/<stem>-1.txt (or -2, -3…).

    We append BEFORE the extension so tools still see the file as .txt.
    """
    target = NOVELS_DIR / name
    if not target.exists():
        return target
    stem, _, ext = name.rpartition(".")
    if not stem:                 # names with no dot like 'README'
        stem, ext = name, ""
    else:
        ext = "." + ext
    i = 1
    while True:
        candidate = NOVELS_DIR / f"{stem}-{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def _normalize_to_utf8(raw_bytes: bytes) -> tuple[bytes, dict]:
    """Detect the encoding of ``raw_bytes`` and return UTF-8 bytes + info.

    Returns:
        (utf8_bytes, info) where info keys are:
          - detected_encoding: str (e.g. 'utf_8', 'gb18030', 'big5')
          - confidence: float in [0.0, 1.0]  (charset_normalizer chaos inverse)
          - normalized: True if we actually decoded + re-encoded; False for
            pass-through UTF-8.
          - fallback_used: True if charset_normalizer gave up and we tried
            codecs from a hard-coded list until one decoded cleanly.
          - warning: optional str (currently used for BOM-stripping notice)

    Raises:
        ValueError("unsupported encoding"): every detection avenue failed.

    Strategy (in order):
      1. Try UTF-8 (with BOM variant) — fast path. Bytes are returned
         unchanged unless a BOM was present; BOM is stripped because it's
         just noise for downstream tools.
      2. Use charset_normalizer with an explicit cp_isolation list. Small
         samples (<8KB) often mis-detect Chinese as Korean cp949 without
         isolation; listing the encodings we actually care about fixes
         that.
      3. If (2) returns None or its decoded content is >5% U+FFFD
         replacement chars, fall back to hardcoded codec order:
         gb18030 (superset of gbk/gb2312) → big5 → shift_jis.
      4. Still nothing → raise.

    Large-file optimisation: detection runs on the first 200KB. The
    decision gets applied to the full byte string for the actual decode.
    charset_normalizer re-reading 10MB of text is measurably slower than
    decoding once under a known codec.
    """
    from charset_normalizer import from_bytes

    # Step 1a: BOM. Python's utf-8 decoder accepts BOM as U+FEFF and would
    # silently leak it into our decoded text, so check BEFORE the generic
    # decode. If BOM is present we strip it and re-validate the tail.
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        try:
            stripped = raw_bytes[3:]
            stripped.decode("utf-8")  # validate the rest
            return stripped, {
                "detected_encoding": "utf_8",
                "confidence": 1.0,
                "normalized": True,  # BOM removal counts as normalisation
                "fallback_used": False,
                "warning": "stripped UTF-8 BOM",
            }
        except UnicodeDecodeError:
            pass  # BOM + garbage — fall through to detection

    # Step 1b: pure UTF-8 fast path. Zero-copy return.
    try:
        raw_bytes.decode("utf-8")
        return raw_bytes, {
            "detected_encoding": "utf_8",
            "confidence": 1.0,
            "normalized": False,
            "fallback_used": False,
            "warning": None,
        }
    except UnicodeDecodeError:
        pass

    # Step 2: charset_normalizer with CJK isolation.
    # Large-file sampling: pass only the first 200KB for detection. Once
    # we have a codec verdict, decode the FULL raw_bytes with it — the
    # codec choice doesn't change mid-file for any real upload.
    DETECT_SAMPLE = 200 * 1024
    CP_ISOLATION = [
        "gb18030", "gbk", "gb2312",
        "big5", "big5hkscs", "cp950",
        "shift_jis", "cp932",
        "euc_jp", "euc_kr",
    ]
    sample = raw_bytes[:DETECT_SAMPLE] if len(raw_bytes) > DETECT_SAMPLE else raw_bytes
    best = from_bytes(sample, cp_isolation=CP_ISOLATION).best()

    fallback_used = False
    detected_encoding: str | None = None
    decoded_text: str | None = None

    if best is not None:
        detected_encoding = best.encoding
        # Decode the FULL buffer with the detected codec, not just the
        # sample. errors='replace' tolerates occasional mojibake (a ragged
        # ending, mid-file encoder glitches) without dropping the file.
        try:
            decoded_text = raw_bytes.decode(detected_encoding, errors="replace")
            # Sanity: if >5% is U+FFFD, charset_normalizer guessed wrong.
            # Fall through to the manual codec list.
            if decoded_text.count("\ufffd") > max(10, len(decoded_text) // 20):
                decoded_text = None
                detected_encoding = None
        except (LookupError, UnicodeDecodeError):
            decoded_text = None
            detected_encoding = None

    # Step 3: manual fallback list.
    # Each candidate must clear three gates before we accept it:
    #   (a) low replacement-char ratio (<5%) — codec matches the byte layout
    #   (b) reasonable printable concentration (≥50%) — not mojibake soup
    #   (c) contains ASCII whitespace (space / tab / newline / CR)
    #       Real text — any text — has line breaks and spaces. Random bytes
    #       decoded under gb18030 produce mostly CJK with essentially zero
    #       whitespace (tested: 4096 random bytes → 72 U+FFFD but 0 spaces),
    #       so this gate is what distinguishes a legit upload from junk.
    if decoded_text is None:
        fallback_used = True
        for codec in ("gb18030", "big5", "shift_jis"):
            try:
                candidate = raw_bytes.decode(codec, errors="replace")
            except (LookupError, UnicodeDecodeError):
                continue
            repl_ratio = candidate.count("\ufffd") / max(1, len(candidate))
            printable = sum(
                1 for c in candidate
                if (0x20 <= ord(c) <= 0x7e) or (0x4e00 <= ord(c) <= 0x9fff)
                or c in "\n\r\t"
            )
            printable_ratio = printable / max(1, len(candidate))
            whitespace_count = sum(candidate.count(w) for w in (" ", "\n", "\t", "\r"))
            has_whitespace = whitespace_count >= max(1, len(candidate) // 500)
            if repl_ratio < 0.05 and printable_ratio > 0.5 and has_whitespace:
                decoded_text = candidate
                detected_encoding = codec
                break

    if decoded_text is None or detected_encoding is None:
        raise ValueError("unsupported encoding")

    # Compute a rough confidence: 1.0 if charset_normalizer matched, else
    # (1 - replacement ratio) for fallback. Informational only; UI doesn't
    # currently act on it but the field is stable API.
    if best is not None and not fallback_used:
        # charset_normalizer doesn't expose a 0..1 confidence directly;
        # chaos=0 is perfect, 0.5+ is noise. Map chaos → confidence.
        try:
            chaos = float(best.chaos)
            confidence = max(0.0, 1.0 - min(chaos, 1.0))
        except (TypeError, ValueError):
            confidence = 0.8
    else:
        confidence = 1.0 - (decoded_text.count("\ufffd") / max(1, len(decoded_text)))

    return decoded_text.encode("utf-8"), {
        "detected_encoding": detected_encoding,
        "confidence": confidence,
        "normalized": True,
        "fallback_used": fallback_used,
        "warning": None,
    }


def _is_utf8_ok(path: Path, head_bytes: int = 8192) -> bool:
    """True iff the first head_bytes of the file decode as UTF-8.

    We use an incremental decoder so a chunk that happens to cut in the
    MIDDLE of a valid multi-byte sequence (common at 8KB/multi-MB boundaries
    when the file is mostly CJK) doesn't trigger a false negative.
    """
    import codecs
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    try:
        with path.open("rb") as f:
            chunk = f.read(head_bytes)
        # final=False tolerates an incomplete trailing sequence — we're only
        # sampling the head, not validating the whole file.
        decoder.decode(chunk, final=False)
        return True
    except (OSError, UnicodeDecodeError):
        return False


def _estimate_chapters(path: Path) -> tuple[int, str]:
    """Return (count, format_name). Uses ChapterStream for large files, and
    falls back to count_chapters on head-only content otherwise. If the file
    can't be decoded as UTF-8, return (1, 'none') — count_chapters's default
    for unparseable input.
    """
    from src.genre_extractor import chapter_detector, chapter_stream
    try:
        size = path.stat().st_size
    except OSError:
        return 1, "none"

    # Large file: use the streaming index (bounded memory).
    if size >= chapter_stream.STREAMING_THRESHOLD_BYTES:
        try:
            stream = chapter_stream.ChapterStream(path)
            count = stream.total_chapters
            # chapter_stream.detect_format reads head 1MB; cheap enough.
            head = path.read_bytes()[: 1024 * 1024].decode("utf-8", errors="ignore")
            fmt = chapter_detector.detect_format(head)
            return count, fmt
        except Exception:
            return 1, "none"

    # Small file: read fully (size < 5MB)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 1, "none"
    return chapter_detector.count_chapters(text), chapter_detector.detect_format(text)


@app.get("/api/novels")
def api_novels_list():
    NOVELS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    # Only top-level *.txt files; skip hidden and non-txt and subdirs.
    for p in sorted(NOVELS_DIR.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        if p.suffix.lower() != ".txt":
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        enc_ok = _is_utf8_ok(p)
        chapters, fmt = _estimate_chapters(p) if enc_ok else (0, "none")
        out.append({
            "name": p.name,
            "path": f"novels/{p.name}",
            "size_bytes": size,
            "size_human": _human_size(size),
            "encoding_ok": enc_ok,
            "estimated_chapters": chapters,
            "detected_format": fmt,
        })
    return jsonify({"novels": out})


@app.post("/api/novels/upload")
def api_novels_upload():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    NOVELS_DIR.mkdir(parents=True, exist_ok=True)

    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "reason": "no files uploaded (field 'files' missing)"}), 400

    uploaded: list[dict] = []
    skipped: list[dict] = []

    for fs in files:
        raw_name = fs.filename or ""
        name = _sanitize_novel_name(raw_name)

        # Extension check (after sanitisation so .. ./ etc. couldn't smuggle one in)
        if not name.lower().endswith(".txt"):
            skipped.append({
                "name": raw_name or name,
                "reason": "not a .txt file (only .txt accepted)",
            })
            continue

        # Read the full byte stream at once so size-check, encoding-detect and
        # atomic write all see the SAME bytes. For 50MB cap this is OK; if we
        # ever raise the cap we should switch to streaming + chunked detect.
        raw_bytes = fs.stream.read()
        original_size = len(raw_bytes)
        if original_size > NOVEL_MAX_BYTES:
            skipped.append({
                "name": raw_name,
                "reason": f"file too large ({_human_size(original_size)} > {_human_size(NOVEL_MAX_BYTES)})",
            })
            continue
        if original_size == 0:
            skipped.append({"name": raw_name, "reason": "empty file"})
            continue

        # Encoding: detect → decode → re-encode as UTF-8. If this fails, we
        # don't write anything — the file's bytes make no textual sense and
        # letting it into novels/ would just crash the pipeline later.
        try:
            utf8_bytes, enc_info = _normalize_to_utf8(raw_bytes)
        except ValueError as e:
            skipped.append({
                "name": raw_name,
                "reason": f"unsupported encoding — tried UTF-8 / GB18030 / Big5 / Shift-JIS ({e})",
            })
            continue

        target = _unique_novel_path(name)
        tmp = target.with_name("." + target.name + ".tmp")
        try:
            # Atomic write: temp file first, then rename. The bytes we write
            # are the UTF-8 normalised form (zero-copy when input was already
            # UTF-8 thanks to the fast path in _normalize_to_utf8).
            with tmp.open("wb") as out_f:
                out_f.write(utf8_bytes)
            os.replace(tmp, target)
        except OSError as e:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            skipped.append({"name": raw_name, "reason": f"write failed: {e}"})
            continue

        uploaded.append({
            "name": target.name,
            "path": f"novels/{target.name}",
            "size_bytes": len(utf8_bytes),
            "size_human": _human_size(len(utf8_bytes)),
            "original_size_bytes": original_size,
            "encoding_ok": True,  # on-disk bytes are now guaranteed UTF-8
            "detected_encoding": enc_info["detected_encoding"],
            "normalized": enc_info["normalized"],
            "fallback_used": enc_info["fallback_used"],
            "encoding_warning": enc_info.get("warning"),
        })

    # 201 iff at least one file landed; otherwise 200 so the UI can still
    # parse `skipped`.
    code = 201 if uploaded else 200
    return jsonify({"uploaded": uploaded, "skipped": skipped}), code


def _resolve_novel_or_abort(name: str) -> Path:
    """Translate a path segment into a novels/<name> Path, refusing anything
    that could escape. Flask routes with <string:name> don't accept '/' so
    the main attack surface is URL-encoded %2F and parent-references.
    """
    if not name or name in (".", ".."):
        abort(400, "invalid name")
    # Reject any separator or parent-ref even after URL-decode
    if "/" in name or "\\" in name or ".." in name:
        abort(403, "path traversal rejected")
    target = (NOVELS_DIR / name).resolve()
    try:
        target.relative_to(NOVELS_DIR.resolve())
    except ValueError:
        abort(403, "path outside novels/")
    return target


@app.delete("/api/novels/<path:name>")
def api_novels_delete(name: str):
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    target = _resolve_novel_or_abort(name)
    if not target.exists() or not target.is_file():
        return jsonify({"ok": False, "reason": "not found"}), 404
    try:
        target.unlink()
    except OSError as e:
        return jsonify({"ok": False, "reason": str(e)}), 500
    return jsonify({"deleted": True, "name": target.name})


@app.get("/api/novels/<path:name>/preview")
def api_novels_preview(name: str):
    target = _resolve_novel_or_abort(name)
    if not target.exists() or not target.is_file():
        return jsonify({"ok": False, "reason": "not found"}), 404

    # Read at most 2000 characters. We over-read bytes (4× chars) so CJK still
    # gives us ~2000 glyphs; trim to exactly 2000 after decode.
    try:
        with target.open("rb") as f:
            raw = f.read(8192)
        text = raw.decode("utf-8", errors="replace")
    except OSError as e:
        return jsonify({"ok": False, "reason": str(e)}), 500

    truncated = target.stat().st_size > len(raw) or len(text) > 2000
    head = text[:2000]
    return jsonify({"name": target.name, "head": head, "truncated": truncated})


@app.get("/novels")
def view_novels_index():
    return render_template("novels/index.html")


# ---------- errors ----------
# All error responses share the same envelope: {"ok": false, "reason": "..."}.
# This keeps the frontend parser simple and matches the shape that mutating
# routes (POST /api/projects/*, /api/env, PUT /api/project-files) return
# inline. Flask's default HTML error pages would break response.json() in JS.
@app.errorhandler(400)
def _h400(e):
    return jsonify({"ok": False, "reason": str(e)}), 400


@app.errorhandler(403)
def _h403(e):
    return jsonify({"ok": False, "reason": str(e)}), 403


@app.errorhandler(404)
def _h404(e):
    return jsonify({"ok": False, "reason": str(e)}), 404


@app.errorhandler(409)
def _h409(e):
    return jsonify({"ok": False, "reason": str(e)}), 409


if __name__ == "__main__":
    # `flask --app web.app run` is the documented launcher; this is a fallback.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)

"""Project management routes.

Covers:
  * /api/projects            — list with active flag
  * /api/projects/activate   — switch active book (bootstrap)
  * /api/projects/new        — 4-step wizard (skeleton-only; extract jobs
                                are now submitted separately via /api/jobs)
  * /api/projects/<pid>/draft-outline, /draft-characters
  * /api/project-files        — edit project.yaml / outline.json / etc.

Removed 2026-05-13 (superseded by the /api/jobs blueprint):
  * POST /api/projects/<pid>/extract-genre
  * GET  /api/projects/<pid>/extract-genre/progress
  * POST /api/projects/<pid>/extract-genre/abort
  * The asynchronous ``from_extract`` branch of POST /api/projects/new
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, abort, jsonify, request

from src import config

from web._shared import (
    READONLY_MODE,
    _PROJECT_EDITABLE,
    _run_lock,
)

bp = Blueprint("projects", __name__)


@bp.get("/api/projects")
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


@bp.post("/api/projects/activate")
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
            "source_preset": result.source_preset,
            "copied_files": result.copied_files,
        })
    finally:
        _run_lock.release()


@bp.post("/api/projects/new")
def api_project_new():
    """4-step wizard: create a project skeleton (name → genre → outline → chars).

    Required fields:
      id, display_name, protagonist_name, chapter_count_target

    Genre source (exactly one):
      from_preset=<id>  |  blank_genre=True

    Outline source (exactly one):
      outline_synopsis=<str> (LLM drafts)  |  blank_outline=True

    Characters source (exactly one):
      characters_brief=<str> (LLM drafts)  |  blank_characters=True

    The asynchronous ``from_extract`` branch has been removed. To populate
    a project's genre files by extracting from source novels, create the
    skeleton here (typically with ``blank_genre=True``) and then submit an
    ``extract-to-project`` job via ``POST /api/jobs``.
    """
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    body = request.get_json(silent=True) or {}

    # Validate required scalar fields up-front — create_project's own checks
    # would raise ValueError too, but doing it here gives crisper messages
    # and avoids creating an aborted on-disk skeleton for trivial mistakes.
    required = ("id", "display_name", "protagonist_name", "chapter_count_target")
    for f in required:
        if body.get(f) is None or body.get(f) == "":
            return jsonify({"ok": False, "reason": f"{f} required"}), 400

    pid = body["id"]

    # Reject the legacy ``from_extract`` async payload with a clear pointer
    # to the new flow (NovelDNA 先造 preset → create_project(from_preset=)).
    if body.get("from_extract") and body["from_extract"].get("sources"):
        return jsonify({
            "ok": False,
            "reason": (
                "from_extract 已不再接受。请先用 POST /api/jobs "
                "kind='from-novel' 从多本素材小说生成一个 preset，"
                "再通过 from_preset 新建作品。"
            ),
        }), 400

    # Sync path: create skeleton + bootstrap into state/.
    try:
        from src.bootstrap import bootstrap_project, create_project
        create_project(
            pid,
            display_name=body["display_name"],
            protagonist_name=body["protagonist_name"],
            chapter_count_target=int(body["chapter_count_target"]),
            from_preset=body.get("from_preset"),
            blank_genre=bool(body.get("blank_genre", False)),
            outline_synopsis=body.get("outline_synopsis"),
            blank_outline=bool(body.get("blank_outline", False)),
            characters_brief=body.get("characters_brief"),
            blank_characters=bool(body.get("blank_characters", False)),
            overwrite=bool(body.get("overwrite", False)),
        )
        bootstrap_project(pid)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({"ok": False, "reason": str(e)}), 404
    except FileExistsError as e:
        return jsonify({"ok": False, "reason": str(e)}), 409
    return jsonify({"ok": True, "project_id": pid})


@bp.post("/api/projects/<pid>/draft-outline")
def api_project_draft_outline(pid: str):
    """Regenerate outline.json from a synopsis via OutlineDrafter LLM call.

    Delegates to pipeline.run_draft_outline, which persists the new
    outline.json under projects/<pid>/ and re-bootstraps state/ if this
    project is currently active.
    """
    if not (config.PROJECTS_DIR / pid).exists():
        return jsonify({"ok": False, "reason": "project not found"}), 404
    body = request.get_json(silent=True) or {}
    synopsis = body.get("synopsis", "")
    from src.pipeline import run_draft_outline
    try:
        out = run_draft_outline(pid, synopsis=synopsis)
    except FileNotFoundError as e:
        return jsonify({"ok": False, "reason": str(e)}), 404
    except Exception as e:
        return jsonify({"ok": False, "reason": str(e)}), 500
    return jsonify(out)


@bp.post("/api/projects/<pid>/draft-characters")
def api_project_draft_characters(pid: str):
    """Regenerate characters.yaml from a brief via CharactersDrafter LLM call.

    Delegates to pipeline.run_draft_characters, which persists the new
    characters.yaml under projects/<pid>/ and re-bootstraps state/ if this
    project is currently active.
    """
    if not (config.PROJECTS_DIR / pid).exists():
        return jsonify({"ok": False, "reason": "project not found"}), 404
    body = request.get_json(silent=True) or {}
    brief = body.get("brief", "")
    from src.pipeline import run_draft_characters
    try:
        out = run_draft_characters(pid, brief=brief)
    except FileNotFoundError as e:
        return jsonify({"ok": False, "reason": str(e)}), 404
    except Exception as e:
        return jsonify({"ok": False, "reason": str(e)}), 500
    return jsonify(out)


# ---------- project file editing ----------

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


@bp.get("/api/project-files")
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


@bp.put("/api/project-files")
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

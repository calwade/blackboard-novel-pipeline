"""Jobs blueprint: /api/jobs CRUD + abort + log tailing + /jobs /jobs/<id> 页面."""
from __future__ import annotations

import threading
from typing import Any

from flask import Blueprint, abort, jsonify, render_template, request

from src.jobs import (
    GenrePipelineAborted,
    NullCancelToken,
    ThreadEventToken,
    get_job_logger,
    get_store,
    initial_job_record,
    new_job_id,
    read_log_tail,
)

# NOTE: ``acquire_target_lock`` will eventually live in ``web/_shared.py`` (see
# plan Task 8). 该函数当前尚未合入 ``_shared``，为使本 blueprint 可独立通过
# 单元测试，此处就地定义一份临时实现；T8 合入后应改回 ``from web._shared
# import acquire_target_lock``。
_TARGET_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_TARGET_LOCKS_META = threading.Lock()


def acquire_target_lock(target_type: str, target_id: str) -> threading.Lock | None:
    key = (target_type, target_id)
    with _TARGET_LOCKS_META:
        lock = _TARGET_LOCKS.setdefault(key, threading.Lock())
    if lock.acquire(blocking=False):
        return lock
    return None


bp = Blueprint("jobs", __name__)

# ---------- API ----------


@bp.get("/api/jobs")
def list_jobs():
    store = get_store()
    state = request.args.get("state")
    kind = request.args.get("kind")
    return jsonify({"jobs": store.list(state=state, kind=kind)})


@bp.post("/api/jobs")
def create_job():
    body = request.get_json(force=True, silent=True) or {}
    kind = body.get("kind")
    target = body.get("target")
    sources = body.get("sources") or []
    params = body.get("params") or {}

    if kind not in ("from-novel", "from-description", "blank", "extract-to-project"):
        return jsonify({"error": "unknown kind"}), 400
    if not isinstance(target, dict) or target.get("type") not in ("preset", "project"):
        return jsonify({"error": "bad target"}), 400

    # Per-target lock
    lock = acquire_target_lock(target["type"], target["id"])
    if lock is None:
        return jsonify({"error": "another job is already running for this target"}), 409

    store = get_store()
    job_id = new_job_id()
    label = _build_label(kind, target)
    rec = initial_job_record(
        job_id=job_id, kind=kind, target=target,
        label=label, sources=sources, params=params,
    )
    store.create(rec)

    cancel = ThreadEventToken()
    store.set_runtime(job_id, cancel=cancel, target_lock=lock)

    t = threading.Thread(target=_run_worker, args=(job_id,), daemon=True)
    t.start()

    return jsonify({"job_id": job_id}), 201


@bp.get("/api/jobs/<job_id>")
def get_job(job_id):
    rec = get_store().get(job_id)
    if rec is None:
        abort(404)
    return jsonify(rec)


@bp.post("/api/jobs/<job_id>/abort")
def abort_job(job_id):
    store = get_store()
    rec = store.get(job_id)
    if rec is None:
        abort(404)
    if rec["state"] != "running":
        return jsonify({"error": f"cannot abort job in state: {rec['state']}"}), 409
    token: ThreadEventToken | None = store.get_runtime(job_id, "cancel")
    if token is not None:
        token.cancel()
    store.update(job_id, state="aborting")
    return jsonify({"ok": True})


@bp.delete("/api/jobs/<job_id>")
def delete_job(job_id):
    store = get_store()
    try:
        store.delete(job_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"ok": True})


@bp.get("/api/jobs/<job_id>/log")
def job_log(job_id):
    offset = int(request.args.get("offset", 0))
    content, next_off = read_log_tail(job_id, offset)
    return jsonify({"content": content, "next_offset": next_off})


# ---------- 页面 ----------


@bp.get("/jobs")
def page_jobs_list():
    return render_template("jobs/index.html")


@bp.get("/jobs/<job_id>")
def page_jobs_detail(job_id):
    return render_template("jobs/detail.html", job_id=job_id)


# ---------- 内部 ----------


def _build_label(kind: str, target: dict) -> str:
    tid = target["id"]
    mapping = {
        "from-novel": f"素材库拆题材 → {tid}",
        "from-description": f"从描述生成题材 → {tid}",
        "blank": f"空壳题材 → {tid}",
        "extract-to-project": f"覆盖作品题材 → {tid}",
    }
    return mapping.get(kind, kind)


def _run_worker(job_id: str) -> None:
    store = get_store()
    rec = store.get(job_id)
    if rec is None:
        return
    logger = get_job_logger(job_id)
    cancel = store.get_runtime(job_id, "cancel") or NullCancelToken()
    target_lock: threading.Lock | None = store.get_runtime(job_id, "target_lock")

    def on_progress(
        *,
        phase: str | None = None,
        phase_index: int | None = None,
        sub_steps: dict | None = None,
        progress_text: str | None = None,
    ) -> None:
        updates: dict[str, Any] = {}
        if phase is not None:
            updates["phase"] = phase
        if phase_index is not None:
            updates["phase_index"] = phase_index
        if sub_steps is not None:
            updates["sub_steps"] = sub_steps
        if progress_text is not None:
            updates["progress_text"] = progress_text
            logger.info(f"[{phase or '-'}] {progress_text}")
        store.update(job_id, **updates)

    try:
        logger.info(f"job started: kind={rec['kind']} target={rec['target']}")
        _dispatch(rec, cancel=cancel, on_progress=on_progress, logger=logger)
        store.finish(job_id, "done")
        logger.info("job finished: done")
    except GenrePipelineAborted:
        store.finish(job_id, "aborted", error="用户中止")
        logger.info("job aborted by user")
    except Exception as e:  # noqa: BLE001
        store.finish(job_id, "failed", error=str(e))
        logger.exception("job failed")
    finally:
        if target_lock is not None:
            try:
                target_lock.release()
            except RuntimeError:
                pass


def _dispatch(rec: dict, *, cancel, on_progress, logger) -> None:
    kind = rec["kind"]
    target = rec["target"]
    params = rec.get("params", {})
    sources = rec.get("sources", [])

    if kind == "blank":
        from src.genre_extractor.blank_preset import create_blank_preset
        create_blank_preset(
            target["id"],
            display_name=params.get("display_name") or target["id"],
            tone=params.get("tone", ""),
            cancel=cancel,
            on_progress=on_progress,
        )
    elif kind == "from-description":
        from src.genre_extractor.from_description import extract_from_description
        extract_from_description(
            target["id"],
            description=params.get("description", ""),
            display_name=params.get("display_name") or target["id"],
            cancel=cancel,
            on_progress=on_progress,
        )
    elif kind == "from-novel":
        from src.genre_extractor.to_preset import extract_to_preset
        extract_to_preset(
            target["id"],
            sources=sources,
            display_name=params.get("display_name") or target["id"],
            with_trial=params.get("with_trial", False),
            cancel=cancel,
            on_progress=on_progress,
        )
    elif kind == "extract-to-project":
        from src.genre_extractor.to_project import extract_to_project
        extract_to_project(
            target["id"],
            sources=sources,
            cancel=cancel,
            on_progress=on_progress,
        )
    else:
        raise ValueError(f"unknown kind: {kind}")

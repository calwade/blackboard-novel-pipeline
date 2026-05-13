"""web/routes/jobs.py 基础 REST 行为."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(
    reason="requires T11: web/app.py registering jobs blueprint; "
           "unskip after integration"
)


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    from src import config
    from src.jobs import store as store_mod
    from src.jobs import logger as logger_mod
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path / ".jobs")
    monkeypatch.setattr(logger_mod, "LOGS_DIR", tmp_path / ".jobs" / "logs")
    store_mod._STORE_SINGLETON = None
    logger_mod._LOGGERS.clear()
    from web.app import create_app
    a = create_app()
    a.config["TESTING"] = True
    yield a


def test_list_jobs_empty(app):
    client = app.test_client()
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert r.get_json() == {"jobs": []}


def test_create_blank_job_returns_201(app, monkeypatch):
    # stub blank_preset 以加速
    def fake(_pid, *, display_name, tone, cancel, on_progress):
        on_progress(phase="validate", phase_index=4, progress_text="done")
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", fake,
    )
    client = app.test_client()
    r = client.post("/api/jobs", json={
        "kind": "blank",
        "target": {"type": "preset", "id": "p1"},
        "params": {"display_name": "P1"},
    })
    assert r.status_code == 201
    jid = r.get_json()["job_id"]
    # 等 worker 结束
    for _ in range(50):
        time.sleep(0.05)
        j = client.get(f"/api/jobs/{jid}").get_json()
        if j["state"] in ("done", "failed", "aborted"):
            break
    assert j["state"] == "done"


def test_create_same_target_twice_conflicts(app, monkeypatch):
    # 阻塞 worker，让第一个 job 不结束
    import threading
    barrier = threading.Event()
    def block(_pid, *, display_name, tone, cancel, on_progress):
        barrier.wait(timeout=5)
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", block,
    )
    client = app.test_client()
    r1 = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "same"},
        "params": {}})
    assert r1.status_code == 201
    r2 = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "same"},
        "params": {}})
    assert r2.status_code == 409
    barrier.set()


def test_abort_flips_state(app, monkeypatch):
    import threading
    from src.jobs.cancel import GenrePipelineAborted
    barrier = threading.Event()
    def block(_pid, *, display_name, tone, cancel, on_progress):
        barrier.wait(timeout=2)
        cancel.check()
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", block,
    )
    client = app.test_client()
    jid = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "abortme"},
        "params": {}}).get_json()["job_id"]
    r = client.post(f"/api/jobs/{jid}/abort")
    assert r.status_code == 200
    barrier.set()
    for _ in range(50):
        time.sleep(0.05)
        j = client.get(f"/api/jobs/{jid}").get_json()
        if j["state"] == "aborted":
            break
    assert j["state"] == "aborted"


def test_delete_running_rejected(app, monkeypatch):
    import threading
    barrier = threading.Event()
    def block(_pid, *, display_name, tone, cancel, on_progress):
        barrier.wait(timeout=5)
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", block,
    )
    client = app.test_client()
    jid = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "delme"},
        "params": {}}).get_json()["job_id"]
    r = client.delete(f"/api/jobs/{jid}")
    assert r.status_code == 409
    barrier.set()


def test_log_tail_incremental(app, monkeypatch):
    def quick(_pid, *, display_name, tone, cancel, on_progress):
        on_progress(phase="extract", phase_index=1, progress_text="hello")
        on_progress(phase="validate", phase_index=4, progress_text="world")
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", quick,
    )
    client = app.test_client()
    jid = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "tailme"},
        "params": {}}).get_json()["job_id"]
    for _ in range(30):
        time.sleep(0.05)
        j = client.get(f"/api/jobs/{jid}").get_json()
        if j["state"] == "done":
            break
    r = client.get(f"/api/jobs/{jid}/log?offset=0").get_json()
    assert "hello" in r["content"]
    assert "world" in r["content"]
    assert r["next_offset"] > 0
    r2 = client.get(f"/api/jobs/{jid}/log?offset={r['next_offset']}").get_json()
    assert r2["content"] == ""

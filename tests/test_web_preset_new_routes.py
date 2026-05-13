"""POST /api/presets/new-blank + /api/presets/new-from-description."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def app_(tmp_path: Path, monkeypatch):
    from src import config
    (tmp_path / "presets").mkdir()
    (tmp_path / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")
    from web import app as web_app
    return web_app.app.test_client()


# -------- new-blank (sync) --------

def test_new_blank_creates_preset(app_):
    r = app_.post("/api/presets/new-blank", json={
        "id": "myblank", "display_name": "My Blank", "tone": "dry",
    })
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["preset_id"] == "myblank"


def test_new_blank_409_on_duplicate(app_):
    r1 = app_.post("/api/presets/new-blank", json={"id": "dup", "display_name": "D", "tone": ""})
    assert r1.status_code == 200
    r2 = app_.post("/api/presets/new-blank", json={"id": "dup", "display_name": "D", "tone": ""})
    assert r2.status_code == 409


def test_new_blank_400_on_missing_id(app_):
    r = app_.post("/api/presets/new-blank", json={"display_name": "X", "tone": ""})
    assert r.status_code == 400


def test_new_blank_400_on_invalid_id(app_):
    r = app_.post("/api/presets/new-blank", json={
        "id": "Bad Id", "display_name": "X", "tone": "",
    })
    assert r.status_code == 400


# -------- new-from-description (async) --------

def test_new_from_description_schedules_job(app_, monkeypatch):
    captured = {}
    def fake_extract(pid, *, display_name, tone, description):
        captured.update(pid=pid, description=description)
        return {"preset_id": pid, "source": "description", "has_resource_schema": False}
    monkeypatch.setattr(
        "src.genre_extractor.from_description.extract_from_description",
        fake_extract,
    )
    r = app_.post("/api/presets/new-from-description", json={
        "id": "mypd", "display_name": "My PD", "tone": "dark",
        "description": "港综 1983 冷硬 …",
    })
    assert r.status_code == 202
    # Wait for background
    for _ in range(40):
        s = app_.get("/api/presets/mypd/status").get_json()
        if s.get("state") in ("done", "failed"):
            break
        time.sleep(0.05)
    assert captured.get("pid") == "mypd"


def test_new_from_description_400_on_empty_description(app_):
    r = app_.post("/api/presets/new-from-description", json={
        "id": "x", "display_name": "X", "tone": "", "description": "",
    })
    assert r.status_code == 400


def test_new_from_description_400_on_missing_fields(app_):
    r = app_.post("/api/presets/new-from-description", json={"id": "x"})
    assert r.status_code == 400


def test_new_from_description_409_on_existing(app_):
    # Pre-create
    (app_.application.root_path).__str__()  # noop
    from src import config
    (config.PRESETS_DIR / "dup").mkdir()
    (config.PRESETS_DIR / "dup" / "genre.yaml").write_text("id: dup\n", encoding="utf-8")

    r = app_.post("/api/presets/new-from-description", json={
        "id": "dup", "display_name": "D", "tone": "", "description": "…",
    })
    assert r.status_code == 409

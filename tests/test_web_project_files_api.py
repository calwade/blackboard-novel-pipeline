"""/api/project-files: edit the 4 source-of-truth files of the active project."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from web.app import app
from src import config


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_rejects_unknown_name(client):
    resp = client.get("/api/project-files?name=iron-laws-extra.md")
    assert resp.status_code == 400


def test_get_rejects_missing_name(client):
    resp = client.get("/api/project-files")
    assert resp.status_code == 400


def test_put_rejects_unknown_name(client):
    resp = client.put(
        "/api/project-files",
        json={"name": "evil.sh", "content": "rm -rf /"},
    )
    assert resp.status_code == 400


def test_put_rejects_missing_content(client):
    resp = client.put("/api/project-files", json={"name": "project.yaml"})
    assert resp.status_code == 400


def test_put_rejects_nonstring_content(client):
    resp = client.put(
        "/api/project-files",
        json={"name": "project.yaml", "content": 123},
    )
    assert resp.status_code == 400


def test_get_roundtrips_with_active_project(client):
    """If an active project exists, GET returns its content; otherwise 409."""
    resp = client.get("/api/project-files?name=project.yaml")
    if config.get_active_project_id() is None:
        assert resp.status_code == 409
    else:
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "project.yaml"
        assert isinstance(data["content"], str)
        assert len(data["content"]) > 0
        assert "mtime" in data


def test_put_roundtrip_preserves_progress(client, tmp_path, monkeypatch):
    """PUT must re-seed state/ BUT preserve progress.completed_chapters."""
    pid = config.get_active_project_id()
    if pid is None:
        pytest.skip("no active project in test env")

    # Read original content so we can restore after test
    get = client.get("/api/project-files?name=project.yaml")
    assert get.status_code == 200
    original = get.get_json()["content"]

    # Seed progress.json with a non-trivial completion list
    from src import bootstrap as bootstrap_mod
    state_dir = config.PROJECTS_DIR / pid / "state"
    progress_path = state_dir / "progress.json"
    original_progress = (
        json.loads(progress_path.read_text(encoding="utf-8"))
        if progress_path.exists() else {}
    )
    fake_progress = {
        "current_chapter": 7,
        "completed_chapters": [1, 2, 3, 4, 5, 6, 7],
        "in_flight": None,
        "last_update": None,
        "total_llm_calls": 42,
    }
    progress_path.write_text(json.dumps(fake_progress), encoding="utf-8")

    try:
        # Trivial edit: append a harmless comment
        edited = original.rstrip() + "\n# edited by test\n"
        put = client.put(
            "/api/project-files",
            json={"name": "project.yaml", "content": edited},
        )
        assert put.status_code == 200, put.get_json()
        assert put.get_json()["re_seeded"] is True

        # Verify the project.yaml was written
        reget = client.get("/api/project-files?name=project.yaml")
        assert "# edited by test" in reget.get_json()["content"]

        # CRITICAL: progress must be preserved
        new_progress = json.loads(progress_path.read_text(encoding="utf-8"))
        assert new_progress["current_chapter"] == 7, "progress was RESET by re-seed — preserve_progress=True broken"
        assert new_progress["completed_chapters"] == [1, 2, 3, 4, 5, 6, 7]
        assert new_progress["total_llm_calls"] == 42
    finally:
        # Restore both project.yaml and progress.json
        client.put("/api/project-files", json={"name": "project.yaml", "content": original})
        progress_path.write_text(json.dumps(original_progress), encoding="utf-8")

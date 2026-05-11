"""Web API: project lifecycle + dynamic state resolution."""
from __future__ import annotations

import json

import pytest

from web.app import app
from src import config


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def restore_state_dir(monkeypatch):
    """Ensure config.STATE_DIR is re-resolved to its original root after a test
    has monkeypatched the STATE_DIR env var. Prevents stale pointers to
    tmp_path-based state dirs from leaking into later tests in the same
    process.
    """
    yield
    monkeypatch.delenv("STATE_DIR", raising=False)
    config.refresh_state_dir()


def test_state_endpoint_returns_dict(client):
    """Basic smoke — /api/state should work regardless of which project is active."""
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "progress" in data
    assert "chapters" in data


def test_bb_is_not_cached_across_requests(client, monkeypatch, tmp_path, restore_state_dir):
    """After refresh_state_dir, /api/state should see the NEW state/ contents."""
    # Create a fake state/ dir with a distinctive progress.json
    fake_state = tmp_path / "fake_state"
    fake_state.mkdir()
    for sub in ("chapters", "summaries", "fixes"):
        (fake_state / sub).mkdir()
    (fake_state / "progress.json").write_text(
        json.dumps({"current_chapter": 999, "completed_chapters": [99]}),
        encoding="utf-8",
    )
    (fake_state / "outline.json").write_text(
        json.dumps({"title": "fake", "chapters": []}),
        encoding="utf-8",
    )
    (fake_state / "issues.jsonl").write_text("", encoding="utf-8")
    (fake_state / "debt.jsonl").write_text("", encoding="utf-8")
    (fake_state / "prompts_log.jsonl").write_text("", encoding="utf-8")

    monkeypatch.setenv("STATE_DIR", str(fake_state))
    config.refresh_state_dir()

    resp = client.get("/api/state")
    data = resp.get_json()
    assert data["progress"]["current_chapter"] == 999, (
        "web did not pick up new STATE_DIR — bb is still cached"
    )


# ---------------------------------------------------------------------------
# Project / Genre management endpoints
# ---------------------------------------------------------------------------

def test_list_genres(client):
    resp = client.get("/api/genres")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "genres" in data
    ids = [g["id"] for g in data["genres"]]
    assert "gangster-hk-1983" in ids
    for g in data["genres"]:
        assert "display_name" in g
        assert "id" in g


def test_list_projects(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "projects" in data
    assert "active" in data
    ids = [p["id"] for p in data["projects"]]
    assert "gangster-hk-1983-linjiayao" in ids
    for p in data["projects"]:
        assert "genre" in p
        assert "display_name" in p
        assert "has_state" in p
        assert "is_active" in p


def test_activate_unknown_project_returns_400(client):
    resp = client.post("/api/projects/activate", json={"id": "does-not-exist-xyz"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "reason" in data


def test_activate_missing_id_returns_400(client):
    resp = client.post("/api/projects/activate", json={})
    assert resp.status_code == 400


def test_new_project_requires_genre(client):
    resp = client.post("/api/projects/new", json={"id": "temp-test-proj"})
    assert resp.status_code == 400


def test_new_project_requires_id(client):
    resp = client.post("/api/projects/new", json={"genre": "gangster-hk-1983"})
    assert resp.status_code == 400


def test_new_project_rejects_unknown_genre(client):
    resp = client.post(
        "/api/projects/new",
        json={"id": "temp-test-xyz", "genre": "nonexistent-genre-xyz"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_new_project_creates_and_then_rejects_duplicate(client, tmp_path, monkeypatch):
    """Roundtrip: new project should succeed, then a second call without overwrite=True returns 409."""
    from src import bootstrap as bootstrap_mod
    # Redirect PROJECTS_DIR for this test so we don't dirty the real dir.
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(bootstrap_mod.config, "PROJECTS_DIR", tmp_path)

    resp = client.post(
        "/api/projects/new",
        json={"id": "temp-new-xyz", "genre": "gangster-hk-1983"},
    )
    assert resp.status_code == 200, resp.get_json()
    assert (tmp_path / "temp-new-xyz" / "project.yaml").exists()

    # Second call without overwrite
    resp2 = client.post(
        "/api/projects/new",
        json={"id": "temp-new-xyz", "genre": "gangster-hk-1983"},
    )
    assert resp2.status_code == 409

    # Third call with overwrite=True should succeed
    resp3 = client.post(
        "/api/projects/new",
        json={"id": "temp-new-xyz", "genre": "gangster-hk-1983", "overwrite": True},
    )
    assert resp3.status_code == 200

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


def test_state_endpoint_returns_dict(client):
    """Basic smoke — /api/state should work regardless of which project is active."""
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "progress" in data
    assert "chapters" in data


def test_bb_is_not_cached_across_requests(client, monkeypatch, tmp_path):
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

"""/api/projects/<id>/draft-{outline,characters} endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app_with_book(tmp_path: Path, monkeypatch):
    from src import config, bootstrap
    (tmp_path / "presets" / "alpha").mkdir(parents=True)
    for f in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        (tmp_path / "presets" / "alpha" / f).write_text("x\n", encoding="utf-8")
    (tmp_path / "presets" / "alpha" / "genre.yaml").write_text("id: alpha\n", encoding="utf-8")
    (tmp_path / "presets" / "alpha" / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")
    bootstrap.create_project(
        "mybook", display_name="B", protagonist_name="H", chapter_count_target=3,
        from_preset="alpha", blank_outline=True, blank_characters=True,
    )
    from web import app as web_app
    return web_app.app.test_client()


def test_draft_outline(app_with_book, monkeypatch):
    monkeypatch.setattr(
        "src.agents.outline_drafter.OutlineDrafter.run",
        lambda self, *, synopsis, chapter_count_target, display_name: {
            "title": display_name,
            "chapters": [{"index": 1, "title": "c1", "beats": ["x"]}],
        },
    )
    r = app_with_book.post("/api/projects/mybook/draft-outline", json={
        "synopsis": "something",
    })
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["chapters"][0]["title"] == "c1"


def test_draft_characters(app_with_book, monkeypatch):
    monkeypatch.setattr(
        "src.agents.characters_drafter.CharactersDrafter.run",
        lambda self, *, brief, protagonist_name: {
            "protagonist": {"name": protagonist_name, "description": "d"},
            "supporting": [{"name": "A", "role": "r", "description": "d"}],
        },
    )
    r = app_with_book.post("/api/projects/mybook/draft-characters", json={
        "brief": "people",
    })
    assert r.status_code == 200
    assert len(r.get_json()["supporting"]) == 1


def test_draft_outline_404(app_with_book):
    r = app_with_book.post("/api/projects/nope/draft-outline", json={"synopsis": "x"})
    assert r.status_code == 404


def test_draft_characters_404(app_with_book):
    r = app_with_book.post("/api/projects/nope/draft-characters", json={"brief": "x"})
    assert r.status_code == 404

"""Post-creation: overwrite a book's genre files from novels pool."""
from __future__ import annotations

from pathlib import Path
import time

import pytest


@pytest.fixture
def app_with_book(tmp_path: Path, monkeypatch):
    from src import config, bootstrap
    preset = tmp_path / "presets" / "alpha"
    preset.mkdir(parents=True)
    for f in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        (preset / f).write_text("x\n", encoding="utf-8")
    (preset / "genre.yaml").write_text("id: alpha\n", encoding="utf-8")
    (preset / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()
    (tmp_path / "novels" / "seed.txt").write_text("x", encoding="utf-8")

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


def test_extract_genre_triggers_async(app_with_book, monkeypatch):
    captured = {}
    def fake_extract(book_id, *, sources, with_trial):
        captured.update(book_id=book_id, sources=sources)
    monkeypatch.setattr("src.genre_extractor.to_project.extract_to_project", fake_extract)

    r = app_with_book.post("/api/projects/mybook/extract-genre", json={
        "sources": ["seed.txt"],
    })
    assert r.status_code == 202

    for _ in range(40):
        s = app_with_book.get("/api/projects/mybook/extract-genre/progress").get_json()
        if s.get("state") == "done":
            break
        time.sleep(0.05)
    assert captured.get("book_id") == "mybook"


def test_extract_genre_404_for_missing_book(app_with_book):
    r = app_with_book.post("/api/projects/nope/extract-genre", json={"sources": ["x.txt"]})
    assert r.status_code == 404


def test_extract_genre_requires_sources(app_with_book):
    r = app_with_book.post("/api/projects/mybook/extract-genre", json={})
    assert r.status_code == 400


def test_extract_genre_abort_marks_aborted(app_with_book):
    from src import config
    # Seed a fake in-progress job
    from web import app as web_app
    with web_app._PROJECT_JOB_LOCK:
        web_app._PROJECT_JOBS["mybook"] = {"state": "running", "error": None}

    r = app_with_book.post("/api/projects/mybook/extract-genre/abort")
    assert r.status_code == 200

    s = app_with_book.get("/api/projects/mybook/extract-genre/progress").get_json()
    assert s["state"] == "aborted"


def test_extract_genre_rebootstraps_when_active(app_with_book, monkeypatch):
    """If the book is the active project, the extract worker should re-bootstrap."""
    from src import config
    config.set_active_project_id("mybook")

    bootstrap_calls = []
    def fake_extract(book_id, *, sources, with_trial):
        return None
    monkeypatch.setattr("src.genre_extractor.to_project.extract_to_project", fake_extract)
    monkeypatch.setattr(
        "src.bootstrap.bootstrap_project",
        lambda pid, **kw: bootstrap_calls.append((pid, kw)),
    )

    r = app_with_book.post("/api/projects/mybook/extract-genre", json={
        "sources": ["seed.txt"],
    })
    assert r.status_code == 202
    for _ in range(40):
        s = app_with_book.get("/api/projects/mybook/extract-genre/progress").get_json()
        if s.get("state") == "done":
            break
        time.sleep(0.05)
    assert bootstrap_calls, "bootstrap_project not called after extract"
    assert bootstrap_calls[-1][0] == "mybook"

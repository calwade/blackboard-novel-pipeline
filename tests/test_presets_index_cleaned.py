"""After Task 5, /presets index has a single '+ 新建 preset' button pointing to /presets/new."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app_(tmp_path, monkeypatch):
    from src import config
    (tmp_path / "presets").mkdir()
    (tmp_path / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    from web import app as web_app
    return web_app.app.test_client()


def test_presets_index_has_new_button(app_):
    r = app_.get("/presets")
    body = r.get_data(as_text=True)
    assert 'href="/presets/new"' in body


def test_presets_index_does_not_embed_new_form(app_):
    """The legacy embedded 'new-from-novel-form' block should be gone."""
    r = app_.get("/presets")
    body = r.get_data(as_text=True)
    assert 'new-from-novel-form' not in body
    assert 'extract-form-section' not in body

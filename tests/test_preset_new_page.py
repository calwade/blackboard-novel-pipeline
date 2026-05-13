"""GET /presets/new renders a 3-tab page."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app_(tmp_path: Path, monkeypatch):
    from src import config
    (tmp_path / "presets").mkdir()
    (tmp_path / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    from web import app as web_app
    return web_app.app.test_client()


def test_get_presets_new_200(app_):
    r = app_.get("/presets/new")
    assert r.status_code == 200


def test_presets_new_has_three_tabs(app_):
    r = app_.get("/presets/new")
    body = r.get_data(as_text=True)
    for tab_id in ("from-novel", "from-description", "blank"):
        assert f'data-tab="{tab_id}"' in body, f"missing tab data-tab=\"{tab_id}\""


def test_presets_new_has_three_panels(app_):
    r = app_.get("/presets/new")
    body = r.get_data(as_text=True)
    for panel_id in ("from-novel", "from-description", "blank"):
        assert f'data-panel="{panel_id}"' in body


def test_presets_new_panels_have_required_fields(app_):
    r = app_.get("/presets/new")
    body = r.get_data(as_text=True)
    # Each panel has an id input
    assert body.count('name="id"') >= 3
    # from-description panel has description textarea
    assert 'name="description"' in body
    # from-novel panel loads novels list (has a target div)
    assert 'id="picker-body"' in body or 'novels-pool-checkboxes' in body


def test_presets_js_wires_three_tabs():
    REPO = Path(__file__).resolve().parent.parent
    text = (REPO / "web" / "static" / "presets.js").read_text(encoding="utf-8")
    # Must call all three new endpoints
    assert "/api/presets/new-from-novel" in text
    assert "/api/presets/new-from-description" in text
    assert "/api/presets/new-blank" in text

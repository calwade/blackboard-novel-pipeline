"""run_draft_outline / run_draft_characters: post-creation regeneration."""
from __future__ import annotations

from pathlib import Path

import json
import pytest
import yaml


@pytest.fixture
def prepared_book(tmp_path, monkeypatch):
    from src import config, bootstrap
    # Minimal preset
    preset = tmp_path / "presets" / "alpha"
    preset.mkdir(parents=True)
    for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        (preset / fname).write_text(f"# {fname}\n", encoding="utf-8")
    (preset / "genre.yaml").write_text("id: alpha\n", encoding="utf-8")
    (preset / "novels").mkdir()
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
    return tmp_path


def test_run_draft_outline_overwrites_outline_json(prepared_book, monkeypatch):
    monkeypatch.setattr(
        "src.agents.outline_drafter.OutlineDrafter.run",
        lambda self, *, synopsis, chapter_count_target, display_name: {
            "title": display_name,
            "chapters": [{"index": 1, "title": "C1", "beats": ["a"]}],
        },
    )
    from src import pipeline
    out = pipeline.run_draft_outline("mybook", synopsis="some story")
    assert out["chapters"][0]["title"] == "C1"

    book_dir = prepared_book / "projects" / "mybook"
    data = json.loads((book_dir / "outline.json").read_text(encoding="utf-8"))
    assert len(data["chapters"]) == 1


def test_run_draft_characters_overwrites_characters_yaml(prepared_book, monkeypatch):
    monkeypatch.setattr(
        "src.agents.characters_drafter.CharactersDrafter.run",
        lambda self, *, brief, protagonist_name: {
            "protagonist": {"name": protagonist_name, "description": "from brief"},
            "supporting": [{"name": "X", "role": "r", "description": "d"}],
        },
    )
    from src import pipeline
    out = pipeline.run_draft_characters("mybook", brief="people")
    assert len(out["supporting"]) == 1

    book_dir = prepared_book / "projects" / "mybook"
    data = yaml.safe_load((book_dir / "characters.yaml").read_text(encoding="utf-8"))
    assert data["protagonist"]["description"] == "from brief"


def test_run_draft_outline_missing_book_raises(prepared_book):
    from src import pipeline
    with pytest.raises(FileNotFoundError, match="not found"):
        pipeline.run_draft_outline("doesnotexist", synopsis="x")

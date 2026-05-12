"""Phase 5 final-state assertions: docs, cleanup, overall acceptance."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_readme_describes_single_workflow():
    """README frames the project as one workflow (a book's lifecycle),
    not two independent pipelines."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "一本书" in text
    assert "preset" in text.lower() or "预设" in text
    assert "src/genre_pipeline" not in text


def test_readme_mentions_4_step_wizard():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "4 步" in text or "四步" in text or "向导" in text


def test_readme_cli_refers_to_new_commands():
    text = (README := REPO / "README.md").read_text(encoding="utf-8")
    assert "--extract-genre" in text
    assert "python -m src.genre_extractor --to-preset" in text
    assert "python -m src.genre_pipeline" not in text


def test_readme_no_stale_layering_language():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    # Old framing that the refactor killed
    assert "Genre + Project 两层" not in text
    assert "两层架构" not in text
    # Don't reference the Phase 0 decision scars
    assert "历史原因" not in text
    assert "2026-05-11 重构" not in text

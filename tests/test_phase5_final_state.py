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


def test_agents_md_describes_single_layer():
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "两层架构" not in text
    assert "projects/<project-id>/" in text or "projects/<book-id>/" in text
    assert "preset" in text.lower() or "预设" in text


def test_agents_md_state_map_has_drafter_agents():
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "OutlineDrafter" in text
    assert "CharactersDrafter" in text


def test_projects_readme_describes_self_contained_book():
    text = (REPO / "projects" / "README.md").read_text(encoding="utf-8")
    assert "source_preset" in text
    assert "era.md" in text  # mentions the inline genre files
    # No lingering reference to the old genres/ directory layering
    # (the word "genres" may appear in prose about history; just check that the
    # structural claim "一本书基于 genre=<id>" is gone)
    assert "genre = " not in text


def test_presets_readme_describes_seed_only():
    text = (REPO / "presets" / "README.md").read_text(encoding="utf-8")
    assert "preset" in text.lower() or "预设" in text
    # preset only acts at new-project time
    assert "运行时不参与" in text or "运行时不" in text


def test_web_ui_guide_routes_point_to_presets():
    text = (REPO / "docs" / "web-ui-guide.md").read_text(encoding="utf-8")
    # No stale /genres routes mentioned in URL tables
    assert "/genres" not in text
    # /presets is documented
    assert "/presets" in text
    # Draft endpoints
    assert "draft-outline" in text
    assert "draft-characters" in text
    # 4-step wizard mentioned
    assert "4 步" in text or "四步" in text
    # extract-genre endpoint
    assert "extract-genre" in text


def test_migration_script_removed_after_use():
    """Migration script is one-shot; deleted after merging."""
    assert not (REPO / "scripts" / "migrate_to_book_centric.py").exists()
    assert not (REPO / "tests" / "test_migration_script.py").exists()


def test_changelog_mentions_book_centric():
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "book-centric" in text.lower() or "一本书" in text


def test_old_genre_pipeline_spec_archived():
    assert not (REPO / "docs" / "superpowers" / "specs" / "genre-pipeline-design.md").exists()


def test_book_centric_spec_exists():
    assert (REPO / "docs" / "superpowers" / "specs" / "book-centric-workflow-design.md").exists()

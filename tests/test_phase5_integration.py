"""End-to-end integration smoke: each built-in project can be bootstrapped."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
BUILTIN_BOOKS = (
    "gangster-hk-1983-linjiayao",
    "xianxia-ascension-peichangning",
    "urban-romance-shenruowei",
)


@pytest.mark.parametrize("book_id", BUILTIN_BOOKS)
def test_builtin_project_bootstraps_cleanly(book_id: str):
    """Each built-in book must bootstrap successfully after migration, no LLM."""
    from src import bootstrap
    result = bootstrap.bootstrap_project(book_id)
    assert result.project_id == book_id
    state = result.state_dir
    for fname in (
        "era.md", "writing-style-extra.md", "iron-laws-extra.md",
        "setting.yaml", "outline.json", "characters.yaml", "timeline.yaml",
        "progress.json",
    ):
        assert (state / fname).exists(), f"{book_id}/state/{fname} missing"


@pytest.mark.parametrize("book_id", BUILTIN_BOOKS)
def test_builtin_project_yaml_has_source_preset(book_id: str):
    data = yaml.safe_load(
        (REPO / "projects" / book_id / "project.yaml").read_text(encoding="utf-8"),
    )
    assert data.get("source_preset") is not None


def test_no_references_to_genre_pipeline_outside_history():
    """src.genre_pipeline must not appear anywhere except CHANGELOG and docs/history/
    and docs/superpowers/plans/ (meta-plan references)."""
    result = subprocess.run(
        ["git", "grep", "-l", "genre_pipeline"],
        cwd=REPO, capture_output=True, text=True,
    )
    allowed_prefixes = ("docs/history/", "docs/superpowers/")
    offenders = [
        line for line in result.stdout.splitlines()
        if line
        and line != "CHANGELOG.md"
        and not any(line.startswith(p) for p in allowed_prefixes)
        and not line.startswith("tests/test_phase1_repo_state.py")  # self-asserts
        and not line.startswith("tests/test_phase5_final_state.py")  # self-asserts
        and not line.startswith("tests/test_phase5_integration.py")  # this file
    ]
    assert offenders == [], f"stale genre_pipeline references: {offenders}"


def test_no_orphaned_genres_dir():
    assert not (REPO / "genres").exists()


def test_no_test_ui_smoke_project():
    assert not (REPO / "projects" / "test-ui-smoke").exists()


def test_gitignore_has_presets_build():
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "presets/*/.build/" in text


def test_presets_dir_has_three_builtins():
    for preset_id in ("gangster-hk-1983", "xianxia-ascension", "urban-romance-contemporary"):
        d = REPO / "presets" / preset_id
        assert d.exists()
        assert (d / "genre.yaml").exists()
        assert (d / "novels").exists()


def test_all_builtin_books_have_inlined_genre_files():
    for book_id in BUILTIN_BOOKS:
        book_dir = REPO / "projects" / book_id
        for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
            assert (book_dir / fname).exists(), f"{book_id}/{fname} missing"

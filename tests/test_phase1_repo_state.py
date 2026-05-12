"""Phase 1 checkpoint: real repo layout after migration.

Runs against the actual repository (not a fixture). Ensures migration ran
and left the tree in the expected shape.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
BUILTIN_PRESETS = ("gangster-hk-1983", "xianxia-ascension", "urban-romance-contemporary")
BUILTIN_PROJECTS = {
    "gangster-hk-1983-linjiayao": "gangster-hk-1983",
    "xianxia-ascension-peichangning": "xianxia-ascension",
    "urban-romance-shenruowei": "urban-romance-contemporary",
}
REQUIRED_GENRE_FILES = ("era.md", "writing-style-extra.md", "iron-laws-extra.md")


def test_genres_dir_removed():
    assert not (REPO / "genres").exists(), "genres/ must be deleted post-migration"


def test_presets_dir_has_3_builtin():
    for gid in BUILTIN_PRESETS:
        assert (REPO / "presets" / gid / "genre.yaml").exists()
        for fname in REQUIRED_GENRE_FILES:
            assert (REPO / "presets" / gid / fname).exists()


def test_presets_have_empty_novels_dir():
    for gid in BUILTIN_PRESETS:
        novels = REPO / "presets" / gid / "novels"
        assert novels.exists()
        assert (novels / ".gitkeep").exists()


def test_novels_pool_still_exists():
    assert (REPO / "novels").exists()
    assert (REPO / "novels" / "README.md").exists()


def test_test_ui_smoke_removed():
    assert not (REPO / "projects" / "test-ui-smoke").exists()


@pytest.mark.parametrize("pid,expected_preset", BUILTIN_PROJECTS.items())
def test_projects_have_genre_files_inlined(pid: str, expected_preset: str):
    p = REPO / "projects" / pid
    for fname in REQUIRED_GENRE_FILES:
        assert (p / fname).exists(), f"{pid}/{fname} missing post-migration"


@pytest.mark.parametrize("pid,expected_preset", BUILTIN_PROJECTS.items())
def test_projects_yaml_uses_source_preset(pid: str, expected_preset: str):
    data = yaml.safe_load((REPO / "projects" / pid / "project.yaml").read_text(encoding="utf-8"))
    assert data.get("source_preset") == expected_preset
    assert "genre" not in data


def test_gitignore_uses_presets():
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "presets/*/.build/" in text
    # No stale "genres/..." lines (but allow "genres" appearing in prose comments)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("genres"), f"stale genres line in .gitignore: {line}"

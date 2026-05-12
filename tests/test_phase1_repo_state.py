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


def test_presets_readme_exists():
    assert (REPO / "presets" / "README.md").exists()
    assert "题材预设库" in (REPO / "presets" / "README.md").read_text(encoding="utf-8")


def test_projects_readme_no_genre_keyword():
    t = (REPO / "projects" / "README.md").read_text(encoding="utf-8")
    # "genre = X" YAML-ish patterns should be gone
    assert "genre = " not in t
    assert "source_preset" in t


def test_genre_pipeline_module_gone():
    assert not (REPO / "src" / "genre_pipeline").exists()
    assert (REPO / "src" / "genre_extractor" / "__init__.py").exists()


def test_no_stale_genre_pipeline_references():
    """Everywhere except CHANGELOG.md and docs/history/ must use src.genre_extractor.

    Exemptions (meta-references to the refactor itself, cleaned in phase 5):
      - docs/superpowers/plans/  (this-task & future-phase plans quote old name)
      - docs/superpowers/specs/genre-pipeline-design.md  (old design spec, archived in phase 5)
      - tests/test_phase1_repo_state.py  (this file literally asserts on the string)
    """
    import subprocess
    result = subprocess.run(
        ["git", "grep", "-l", "genre_pipeline"],
        capture_output=True, text=True, cwd=REPO,
    )
    EXEMPT_PREFIXES = (
        "docs/history/",
        "docs/superpowers/plans/",
    )
    EXEMPT_FILES = {
        "CHANGELOG.md",
        "docs/superpowers/specs/genre-pipeline-design.md",
        "tests/test_phase1_repo_state.py",
        # Phase 5 final-state test also asserts on the string (negatively).
        "tests/test_phase5_final_state.py",
    }
    offenders = [
        line for line in result.stdout.splitlines()
        if line
        and line not in EXEMPT_FILES
        and not any(line.startswith(p) for p in EXEMPT_PREFIXES)
    ]
    assert offenders == [], f"stale genre_pipeline references in: {offenders}"


def test_genre_extractor_imports_ok():
    import importlib
    for mod in ("src.genre_extractor", "src.genre_extractor.pipeline"):
        importlib.import_module(mod)

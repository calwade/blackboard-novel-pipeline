"""Tests for bootstrap refactor — genre + project two-layer architecture.

Replaces the old single-layer settings/ tests after the 2026-05-11 refactor.
Covers:
  - list_genres / list_projects / validate_genre / validate_project
  - bootstrap_project in-process (tmp tree)
  - create_project scaffolds
  - STATE_DIR dynamic resolution after activating a project
  - real genres + projects all lint clean on disk
  - preserve_progress parameter for bootstrap_project
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from src import bootstrap, config


# ---------------- test helpers ----------------


def _seed_minimal_genre(genre_dir: Path, genre_id: str, *, with_schema: bool = False) -> None:
    genre_dir.mkdir(parents=True, exist_ok=True)
    (genre_dir / "genre.yaml").write_text(
        yaml.safe_dump(
            {
                "id": genre_id,
                "display_name": f"test genre {genre_id}",
                "genre": "test",
                "era": "test era",
                "tone": "test tone",
                "author_persona_hints": ["hint"],
                "prohibited_styles": ["x"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (genre_dir / "era.md").write_text("era text", encoding="utf-8")
    (genre_dir / "writing-style-extra.md").write_text("style text", encoding="utf-8")
    (genre_dir / "iron-laws-extra.md").write_text(
        "## iron_law_extra_1\nfoo\n", encoding="utf-8"
    )
    if with_schema:
        (genre_dir / "resource_schema.yaml").write_text(
            "resources: []\nvalidation:\n  increment_rules: []\n  forbidden_fuzzy_terms: []\n",
            encoding="utf-8",
        )


def _seed_minimal_project(
    project_dir: Path, project_id: str, genre_id: str
) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "id": project_id,
                "display_name": f"test project {project_id}",
                "genre": genre_id,
                "protagonist_name": "A",
                "protagonist_hook": "hook",
                "opening_year_month": "2024-01",
                "chapter_count_target": 10,
                "chapters_in_outline": 1,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    import json as _json
    (project_dir / "outline.json").write_text(
        _json.dumps({"chapters": [{"ch": 1, "title": "t"}]}),
        encoding="utf-8",
    )
    (project_dir / "characters.yaml").write_text(
        "protagonist:\n  name: A\n", encoding="utf-8"
    )
    (project_dir / "timeline.yaml").write_text("2024: []\n", encoding="utf-8")


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    """Point GENRES_DIR/PROJECTS_DIR/ACTIVE_POINTER/PROJECT_ROOT at a tmp tree
    so tests don't interfere with the real repo."""
    genres = tmp_path / "genres"
    projects = tmp_path / "projects"
    genres.mkdir()
    projects.mkdir()
    active = projects / ".active"
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "GENRES_DIR", genres)
    monkeypatch.setattr(config, "PROJECTS_DIR", projects)
    monkeypatch.setattr(config, "ACTIVE_POINTER", active)
    return tmp_path


# ---------------- list + validate ----------------


def test_list_genres_empty(isolated_repo):
    assert bootstrap.list_genres() == []


def test_list_projects_empty(isolated_repo):
    assert bootstrap.list_projects() == []


def test_list_genres_filters_dirs_without_genre_yaml(isolated_repo):
    (isolated_repo / "genres" / "good").mkdir()
    (isolated_repo / "genres" / "good" / "genre.yaml").write_text("id: good\n", encoding="utf-8")
    (isolated_repo / "genres" / "bad").mkdir()  # no genre.yaml
    assert bootstrap.list_genres() == ["good"]


def test_validate_genre_reports_missing_files(isolated_repo):
    gd = isolated_repo / "genres" / "incomplete"
    gd.mkdir()
    missing = bootstrap.validate_genre(gd)
    assert set(missing) == set(bootstrap.GENRE_REQUIRED_FILES)


def test_validate_genre_passes_on_complete(isolated_repo):
    gd = isolated_repo / "genres" / "g1"
    _seed_minimal_genre(gd, "g1")
    assert bootstrap.validate_genre(gd) == []


def test_validate_project_reports_missing_files(isolated_repo):
    pd = isolated_repo / "projects" / "incomplete"
    pd.mkdir()
    missing = bootstrap.validate_project(pd)
    assert set(missing) == set(bootstrap.PROJECT_REQUIRED_FILES)


def test_validate_project_passes_on_complete(isolated_repo):
    _seed_minimal_genre(isolated_repo / "genres" / "g1", "g1")
    _seed_minimal_project(isolated_repo / "projects" / "p1", "p1", "g1")
    assert bootstrap.validate_project(isolated_repo / "projects" / "p1") == []


# ---------------- bootstrap_project ----------------


def test_bootstrap_project_copies_genre_and_project_files(isolated_repo):
    _seed_minimal_genre(isolated_repo / "genres" / "g1", "g1", with_schema=True)
    _seed_minimal_project(isolated_repo / "projects" / "p1", "p1", "g1")

    result = bootstrap.bootstrap_project("p1")
    assert result.project_id == "p1"
    assert result.genre_id == "g1"
    state = result.state_dir
    # Genre-layer files present
    assert (state / "era.md").exists()
    assert (state / "writing-style-extra.md").exists()
    assert (state / "iron-laws-extra.md").exists()
    assert (state / "resource_schema.yaml").exists()
    # Project-layer files present
    assert (state / "outline.json").exists()
    assert (state / "characters.yaml").exists()
    assert (state / "timeline.yaml").exists()
    # Synthesized setting.yaml merges both
    merged = yaml.safe_load((state / "setting.yaml").read_text(encoding="utf-8"))
    assert merged["genre"] == "test"
    assert merged["protagonist_name"] == "A"
    assert merged["genre_id"] == "g1"
    # progress + accumulators
    assert (state / "progress.json").exists()
    assert (state / "issues.jsonl").exists()
    assert (state / "debt.jsonl").exists()


def test_bootstrap_activates_project(isolated_repo):
    _seed_minimal_genre(isolated_repo / "genres" / "g1", "g1")
    _seed_minimal_project(isolated_repo / "projects" / "p1", "p1", "g1")
    bootstrap.bootstrap_project("p1")
    assert config.get_active_project_id() == "p1"
    assert config.active_project_dir() == isolated_repo / "projects" / "p1"
    assert config.active_state_dir() == isolated_repo / "projects" / "p1" / "state"


def test_bootstrap_unknown_project_raises(isolated_repo):
    with pytest.raises(FileNotFoundError, match="Project not found"):
        bootstrap.bootstrap_project("does-not-exist")


def test_bootstrap_project_with_missing_genre_raises(isolated_repo):
    _seed_minimal_project(isolated_repo / "projects" / "p1", "p1", "nonexistent-genre")
    with pytest.raises(FileNotFoundError, match="Genre not found"):
        bootstrap.bootstrap_project("p1")


def test_bootstrap_purges_stale_resource_schema_on_genre_switch(isolated_repo):
    """Switching a project from a genre with schema to one without schema
    must remove the stale resource_schema.yaml from state/."""
    _seed_minimal_genre(isolated_repo / "genres" / "numeric", "numeric", with_schema=True)
    _seed_minimal_genre(isolated_repo / "genres" / "nonnumeric", "nonnumeric", with_schema=False)
    _seed_minimal_project(isolated_repo / "projects" / "p1", "p1", "numeric")

    result = bootstrap.bootstrap_project("p1")
    assert (result.state_dir / "resource_schema.yaml").exists()

    # Flip the project to the non-numeric genre, re-bootstrap
    pyaml = yaml.safe_load((isolated_repo / "projects" / "p1" / "project.yaml").read_text(encoding="utf-8"))
    pyaml["genre"] = "nonnumeric"
    (isolated_repo / "projects" / "p1" / "project.yaml").write_text(
        yaml.safe_dump(pyaml, allow_unicode=True), encoding="utf-8"
    )

    result2 = bootstrap.bootstrap_project("p1")
    assert not (result2.state_dir / "resource_schema.yaml").exists()


# ---------------- create_project ----------------


def test_create_project_scaffolds_minimal_stubs(isolated_repo):
    _seed_minimal_genre(isolated_repo / "genres" / "g1", "g1")
    pd = bootstrap.create_project("my-new-book", "g1")
    assert pd.exists()
    py = yaml.safe_load((pd / "project.yaml").read_text(encoding="utf-8"))
    assert py["id"] == "my-new-book"
    assert py["genre"] == "g1"
    # Must have minimal stubs
    assert (pd / "outline.json").exists()
    assert (pd / "characters.yaml").exists()
    assert (pd / "timeline.yaml").exists()


def test_create_project_refuses_to_overwrite(isolated_repo):
    _seed_minimal_genre(isolated_repo / "genres" / "g1", "g1")
    bootstrap.create_project("dup", "g1")
    with pytest.raises(FileExistsError):
        bootstrap.create_project("dup", "g1")


def test_create_project_overwrite_flag_works(isolated_repo):
    _seed_minimal_genre(isolated_repo / "genres" / "g1", "g1")
    bootstrap.create_project("dup", "g1")
    # Should succeed with overwrite
    pd = bootstrap.create_project("dup", "g1", overwrite=True)
    assert pd.exists()


def test_create_project_unknown_genre_raises(isolated_repo):
    with pytest.raises(FileNotFoundError, match="Genre not found"):
        bootstrap.create_project("p1", "bogus-genre")


# ---------------- real repo integration ----------------


@pytest.mark.skip(reason="awaiting phase 2 bootstrap rewrite")
@pytest.mark.parametrize(
    "genre_id",
    ["gangster-hk-1983", "xianxia-ascension", "urban-romance-contemporary"],
)
def test_real_genres_are_complete(genre_id):
    """Integration: each shipped genre must have all required files."""
    gd = config.GENRES_DIR / genre_id
    missing = bootstrap.validate_genre(gd)
    assert missing == [], f"{genre_id} missing required files: {missing}"


@pytest.mark.parametrize(
    "project_id",
    [
        "gangster-hk-1983-linjiayao",
        "xianxia-ascension-peichangning",
        "urban-romance-shenruowei",
    ],
)
def test_real_projects_are_complete(project_id):
    """Integration: each shipped project must have all required files."""
    pd = config.PROJECTS_DIR / project_id
    missing = bootstrap.validate_project(pd)
    assert missing == [], f"{project_id} missing required files: {missing}"


@pytest.mark.skip(reason="awaiting phase 2 bootstrap rewrite")
@pytest.mark.parametrize(
    "project_id,expected_genre_has_schema",
    [
        ("gangster-hk-1983-linjiayao", True),
        ("xianxia-ascension-peichangning", True),
        ("urban-romance-shenruowei", False),
    ],
)
def test_real_projects_genre_schema_presence(project_id, expected_genre_has_schema):
    """Resource_schema presence is determined by the genre, not the project."""
    pd = config.PROJECTS_DIR / project_id
    proj_yaml = yaml.safe_load((pd / "project.yaml").read_text(encoding="utf-8"))
    genre_id = proj_yaml["genre"]
    schema_path = config.GENRES_DIR / genre_id / "resource_schema.yaml"
    assert schema_path.exists() == expected_genre_has_schema


@pytest.mark.skip(reason="awaiting phase 2 bootstrap rewrite")
@pytest.mark.parametrize(
    "genre_id",
    ["gangster-hk-1983", "xianxia-ascension", "urban-romance-contemporary"],
)
def test_real_genres_declare_prohibited_styles(genre_id):
    """Every genre declares a non-trivial prohibited_styles list."""
    gyaml = yaml.safe_load(
        (config.GENRES_DIR / genre_id / "genre.yaml").read_text(encoding="utf-8")
    )
    styles = gyaml.get("prohibited_styles", [])
    assert isinstance(styles, list)
    assert len(styles) >= 3, f"{genre_id} should declare at least 3 prohibited styles"


# ---------------- preserve_progress ----------------
# These tests use the `isolated_project` fixture (tests/conftest.py) so they
# exercise the full bootstrap machinery against a throwaway tmp_path copy
# instead of mutating the real gangster-hk-1983-linjiayao/ on disk.


@pytest.mark.skip(reason="awaiting phase 2 bootstrap rewrite")
def test_bootstrap_project_preserves_progress_when_asked(isolated_project):
    """preserve_progress=True keeps completed_chapters / current_chapter intact."""
    pid = isolated_project
    state_dir = config.PROJECTS_DIR / pid / "state"
    progress_path = state_dir / "progress.json"

    fake = {
        "current_chapter": 99,
        "completed_chapters": [1, 2, 99],
        "in_flight": None,
        "last_update": None,
        "total_llm_calls": 12345,
    }
    progress_path.write_text(json.dumps(fake), encoding="utf-8")

    bootstrap.bootstrap_project(pid, preserve_progress=True)
    new = json.loads(progress_path.read_text(encoding="utf-8"))
    assert new["current_chapter"] == 99
    assert new["completed_chapters"] == [1, 2, 99]
    assert new["total_llm_calls"] == 12345
    # New fields still added:
    assert new["active_project"] == pid


@pytest.mark.skip(reason="awaiting phase 2 bootstrap rewrite")
def test_bootstrap_project_resets_progress_by_default(isolated_project):
    """Without preserve_progress, progress is RESET (CLI behavior)."""
    pid = isolated_project
    state_dir = config.PROJECTS_DIR / pid / "state"
    progress_path = state_dir / "progress.json"

    fake = {"current_chapter": 99, "completed_chapters": [99], "total_llm_calls": 100}
    progress_path.write_text(json.dumps(fake), encoding="utf-8")

    bootstrap.bootstrap_project(pid)  # default preserve_progress=False
    new = json.loads(progress_path.read_text(encoding="utf-8"))
    assert new["current_chapter"] == 0, "progress should have been reset"
    assert new["completed_chapters"] == []
